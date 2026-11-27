"""
数据平台编排脚本（Orchestrator）

做了什么：
  1. 用 TASKS 列表声明"有哪些任务、各自依赖谁"
  2. 拓扑排序算出执行顺序（顺便检测循环依赖）
  3. 按顺序执行，任何一个失败就停下来
  4. 记录每个任务的耗时，最后打印汇总

为什么不用 Airflow：
  任务只有十几个、单人开发、几十秒跑完。Airflow 解决的是"几百任务、多人协作、
  可视化监控"，现在上它是过度设计。等任务规模上来了再迁。

用法：
    python scripts/run_pipeline.py                # 全量重跑（含重新造数）
    python scripts/run_pipeline.py --skip-gen     # 只重跑 ETL（数据没变时用）
    python scripts/run_pipeline.py --only top_products   # 只跑某个任务
"""

import argparse
import copy
import subprocess
import sys
import time
from pathlib import Path

import pymysql

DB = dict(host="127.0.0.1", port=3307, user="root",
          password="root123", charset="utf8mb4")

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------
# 任务声明：type 支持 sql / python
# deps 写的是任务名，不是文件名
# ---------------------------------------------------------------
TASKS = [
    # 0. 造数（可选跳过）
    {"name": "gen_data", "type": "python", "file": "etl/gen_data.py",
     "args": ["--orders", "100000"], "deps": []},

    # 1. DWD 建表
    {"name": "dwd_ddl", "type": "sql", "file": "sql/dwd/ddl.sql", "deps": ["gen_data"]},

    # 2. DWD 清洗：两个维度表 + 两个事实表
    #    dim_product 必须在 category_day / top_products 之前，
    #    因为这两个下游任务都要 JOIN 商品维度拿 category / product_name
    {"name": "dim_user", "type": "sql", "file": "sql/dwd/dim_user.sql", "deps": ["dwd_ddl"]},
    {"name": "dim_product", "type": "sql", "file": "sql/dwd/dim_product.sql",
     "deps": ["dwd_ddl"]},
    {"name": "fact_order", "type": "sql", "file": "sql/dwd/fact_order.sql", "deps": ["dwd_ddl"]},
    {"name": "fact_order_line", "type": "sql", "file": "sql/dwd/fact_order_line.sql",
     "deps": ["fact_order"]},

    # 3. DWS 建表 + 三个汇总
    {"name": "dws_ddl", "type": "sql", "file": "sql/dws/ddl.sql", "deps": ["dwd_ddl"]},
    {"name": "user_day", "type": "sql", "file": "sql/dws/user_day.sql",
     "deps": ["dim_user", "fact_order"]},
    {"name": "product_day", "type": "sql", "file": "sql/dws/product_day.sql",
     "deps": ["fact_order_line", "fact_order"]},
    {"name": "category_day", "type": "sql", "file": "sql/dws/category_day.sql",
     "deps": ["fact_order_line", "fact_order", "dim_product"]},

    # 4. ADS 建表 + 三张应用表
    {"name": "ads_ddl", "type": "sql", "file": "sql/ads/ddl.sql", "deps": ["dws_ddl"]},
    {"name": "ads_ddl_extra", "type": "sql", "file": "sql/ads/ddl_extra.sql",
     "deps": ["ads_ddl"]},
    {"name": "gmv_daily", "type": "sql", "file": "sql/ads/gmv_daily.sql",
     "deps": ["fact_order", "ads_ddl"]},
    {"name": "top_products", "type": "sql", "file": "sql/ads/top_products.sql",
     "deps": ["product_day", "ads_ddl_extra", "dim_product"]},
    {"name": "user_retention", "type": "sql", "file": "sql/ads/user_retention.sql",
     "deps": ["fact_order", "ads_ddl_extra"]},

    # 5. 最后跑质量校验，作为整条链路的守门员
    {"name": "quality_check", "type": "python", "file": "quality/check.py",
     "deps": ["gmv_daily", "top_products", "user_retention",
              "user_day", "product_day", "category_day"]},

    # 6. 血缘：每次跑完自动刷新依赖图
    #    同时校验「SQL 实际依赖」和「TASKS 声明的 deps」是否一致——
    #    不一致说明改了 SQL 忘了改调度，会导致乱序执行且不报错。
    {"name": "build_lineage", "type": "python", "file": "lineage/build_lineage.py",
     "deps": ["quality_check"]},
]


def topological_order(tasks):
    """
    拓扑排序（Kahn 算法）。
    返回 (顺序列表, 每个任务被谁阻塞)。

    顺便能检测循环依赖：如果最后还有任务没有输出，说明它们互相等待。
    """
    by_name = {t["name"]: t for t in tasks}
    indegree = {t["name"]: 0 for t in tasks}
    children = {t["name"]: [] for t in tasks}

    for t in tasks:
        for d in t["deps"]:
            if d not in by_name:
                raise ValueError(f"任务 {t['name']} 依赖了不存在的任务 {d}")
            indegree[t["name"]] += 1
            children[d].append(t["name"])

    ready = [n for n, deg in indegree.items() if deg == 0]
    order = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for c in children[n]:
            indegree[c] -= 1
            if indegree[c] == 0:
                ready.append(c)

    if len(order) != len(tasks):
        stuck = [n for n, deg in indegree.items() if deg > 0]
        raise ValueError(f"存在循环依赖，以下任务无法执行：{stuck}")

    return order


def split_sql(text):
    """
    把 .sql 文件切成一条条语句。

    只去掉以 -- 开头的整行注释，然后按 ; 切分。
    我们的 SQL 文件里没有字符串内包含 ; 的情况，够用。
    （生产级做法是用 sqlparse 之类的解析器）
    """
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("--")]
    body = "\n".join(lines)
    return [s.strip() for s in body.split(";") if s.strip()]


def run_sql(task):
    path = ROOT / task["file"]
    if not path.exists():
        raise FileNotFoundError(path)
    statements = split_sql(path.read_text(encoding="utf-8"))
    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            for idx, stmt in enumerate(statements, 1):
                try:
                    cur.execute(stmt)
                except Exception as e:
                    # 把出错的语句一起抛出去，否则只看到一个错误码，不知道错在哪句
                    preview = " ".join(stmt.split())[:180]
                    raise RuntimeError(
                        f"{task['file']} 第 {idx}/{len(statements)} 条语句失败：{e}\n"
                        f"      语句：{preview}"
                    ) from e
                # 把 SELECT 的结果打出来（验收查询会用到）
                if cur.description:
                    rows = cur.fetchall()
                    for row in rows[:5]:
                        print("      " + " | ".join(str(c) for c in row))
        conn.commit()
    finally:
        conn.close()


def run_python(task):
    cmd = [sys.executable, str(ROOT / task["file"])] + task.get("args", [])
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "")[-800:]
        raise RuntimeError(f"退出码 {result.returncode}\n{tail}")


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-gen", action="store_true",
                        help="跳过造数（数据没变化、只改了 ETL 逻辑时用）")
    parser.add_argument("--only", nargs="*", default=None,
                        help="只跑指定任务（仍会按依赖顺序执行它们）")
    args = parser.parse_args()

    tasks = copy.deepcopy(TASKS)
    if args.skip_gen:
        tasks = [t for t in tasks if t["name"] != "gen_data"]
        # 跳过造数后，"依赖 gen_data" 这条边就不成立了，要一起摘掉
        for t in tasks:
            t["deps"] = [d for d in t["deps"] if d != "gen_data"]

    order = topological_order(tasks)
    if args.only:
        keep = set()
        # 只跑指定任务 + 它们的依赖（保证前提高于顺序，不会跑到一半缺数据）
        by_name = {t["name"]: t for t in tasks}

        def collect(name):
            if name in keep:
                return
            keep.add(name)
            for d in by_name[name]["deps"]:
                collect(d)

        for n in args.only:
            if n not in by_name:
                print(f"没有这个任务: {n}")
                return 2
            collect(n)
        order = [n for n in order if n in keep]

    print(f"执行顺序（{len(order)} 个任务）：")
    print("  " + " → ".join(order))
    print()

    by_name = {t["name"]: t for t in tasks}
    done, timings = [], []

    for i, name in enumerate(order, 1):
        task = by_name[name]
        print(f"[{i}/{len(order)}] {name:<16} ({task['type']}) ...", flush=True)
        t0 = time.perf_counter()
        try:
            if task["type"] == "sql":
                run_sql(task)
            else:
                run_python(task)
        except Exception as e:
            cost = time.perf_counter() - t0
            print(f"    [FAIL] 失败（{cost:.1f}s）")
            print(f"    {e}")
            print(f"\n链路中断：{name} 失败，后续 {len(order) - i} 个任务未执行")
            print(f"已完成的：{', '.join(done) or '无'}")
            return 1
        cost = time.perf_counter() - t0
        timings.append((name, cost))
        done.append(name)
        print(f"    [OK] 完成（{cost:.1f}s）")

    print()
    print("=" * 60)
    print("全部完成")
    print("=" * 60)
    total = sum(c for _, c in timings)
    for name, cost in sorted(timings, key=lambda x: -x[1]):
        bar = "#" * max(1, int(cost / total * 40))
        print(f"  {name:<18}{cost:>7.1f}s  {bar}")
    print(f"  {'合计':<18}{total:>7.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
