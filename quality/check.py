"""
数据质量校验器。

读 rules.yaml → 每条规则生成 SQL → 执行 → 实际值 vs 期望值 → 输出报告

用法：
    python quality/check.py
    python quality/check.py --report docs/quality-report.html
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import pymysql
import yaml

DB = dict(host="127.0.0.1", port=3307, user="root",
          password="root123", charset="utf8mb4")

ROOT = Path(__file__).resolve().parent.parent


# ---------------- 每种规则类型 → 一段 SQL ----------------
# 约定：所有 SQL 都返回单个数字（异常条数）

def sql_not_null(c):
    return f"SELECT COUNT(*) FROM {c['table']} WHERE {c['column']} IS NULL"


def sql_range(c):
    conds = []
    if c.get("min") is not None:
        conds.append(f"{c['column']} < {c['min']}")
    if c.get("max") is not None:
        conds.append(f"{c['column']} > {c['max']}")
    return f"SELECT COUNT(*) FROM {c['table']} WHERE {' OR '.join(conds)}"


def sql_unique(c):
    # 用「总行数 - 去重后的值个数」= 多出来的重复行数
    return (f"SELECT COUNT(*) - COUNT(DISTINCT {c['column']}) "
            f"FROM {c['table']}")


def sql_enum(c):
    values = ", ".join("'" + str(v) + "'" for v in c["allowed"])
    return (f"SELECT COUNT(*) FROM {c['table']} "
            f"WHERE {c['column']} IS NOT NULL AND {c['column']} NOT IN ({values})")


def sql_time_order(c):
    return (f"SELECT COUNT(*) FROM {c['table']} "
            f"WHERE {c['later_col']} IS NOT NULL "
            f"  AND {c['later_col']} < {c['earlier_col']}")


def sql_sum_match(c):
    l, r = c["left"], c["right"]
    return f"""
        SELECT COUNT(*) FROM (
            SELECT a.{l['key']}, a.{l['col']} AS v_left,
                   SUM(b.{r['col']}) AS v_right
            FROM {l['table']} a
            JOIN {r['table']} b ON a.{l['key']} = b.{r['key']}
            GROUP BY a.{l['key']}, a.{l['col']}
            HAVING ABS(a.{l['col']} - SUM(b.{r['col']})) > 0.01
        ) t
    """


def sql_referential(c):
    ch, pa = c["child"], c["parent"]
    return (f"SELECT COUNT(*) FROM {ch['table']} c "
            f"LEFT JOIN {pa['table']} p ON c.{ch['col']} = p.{pa['col']} "
            f"WHERE c.{ch['col']} IS NOT NULL AND p.{pa['col']} IS NULL")


def sql_change_rate(c):
    # 用窗口函数取上一行的值，统计波动超过阈值的天数
    t = c["threshold"]
    return f"""
        SELECT COUNT(*) FROM (
            SELECT {c['value_col']} AS v,
                   LAG({c['value_col']}) OVER (ORDER BY {c['date_col']}) AS prev
            FROM {c['table']}
        ) x
        WHERE prev IS NOT NULL AND prev > 0
          AND ABS(v - prev) / prev > {t}
    """


def sql_row_count(c):
    """
    完整性校验：表里有多少行。

    它和别的规则不一样——别的规则查"有多少条坏数据"，这条查"表是不是空的"。
    空表意味着上游 ETL 没跑成功，但下游 JOIN 只会得到 0 行，不会报错。
    """
    return f"SELECT COUNT(*) FROM {c['table']}"


BUILDERS = {
    "not_null": sql_not_null,
    "range": sql_range,
    "unique": sql_unique,
    "enum": sql_enum,
    "time_order": sql_time_order,
    "sum_match": sql_sum_match,
    "referential": sql_referential,
    "change_rate": sql_change_rate,
    "row_count": sql_row_count,
}


def run_checks(rules_path: str):
    rules = yaml.safe_load(Path(rules_path).read_text(encoding="utf-8"))
    conn = pymysql.connect(**DB)
    results = []

    for chk in rules["checks"]:
        builder = BUILDERS.get(chk["type"])
        if not builder:
            results.append({**chk, "actual": None, "status": "ERROR",
                            "msg": f"未知规则类型 {chk['type']}"})
            continue

        sql = builder(chk)
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                actual = cur.fetchone()[0]
        except Exception as e:
            results.append({**chk, "actual": None, "status": "ERROR", "msg": str(e)})
            continue

        # row_count 是"门槛型"规则：实际值 >= min_rows 就算通过，
        # 其余规则是"计数型"：实际值必须精确等于 expect
        if chk["type"] == "row_count":
            min_rows = chk.get("min_rows", 1)
            effect_expect = f">= {min_rows}"
            status = "PASS" if actual >= min_rows else "FAIL"
        else:
            effect_expect = chk.get("expect")
            if effect_expect is None:
                status = "INFO"
            elif actual == effect_expect:
                status = "PASS"
            else:
                status = "FAIL"

        results.append({**chk, "actual": int(actual), "status": status,
                        "msg": "", "expect": effect_expect})

    conn.close()
    return results


def render_html(results, out_path: Path):
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    info = sum(1 for r in results if r["status"] == "INFO")
    errors = sum(1 for r in results if r["status"] == "ERROR")

    checked = total - info - errors
    score = round(passed / checked * 100, 1) if checked else 100.0

    color = {"PASS": "#1a7f37", "FAIL": "#cf222e", "INFO": "#0969da", "ERROR": "#9a6700"}
    rows = []
    for r in results:
        st = r["status"]
        expect = "—" if r.get("expect") is None else r["expect"]
        rows.append(f"""
        <tr>
          <td>{r['id']}</td>
          <td>{r['name']}</td>
          <td><code>{r.get('severity', '')}</code></td>
          <td style="text-align:right">{r['actual'] if r['actual'] is not None else '—'}</td>
          <td style="text-align:right">{expect}</td>
          <td><span style="color:{color[st]};font-weight:600">{st}</span></td>
        </tr>""")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>数据质量报告</title>
<style>
  body{{font-family:-apple-system,"Segoe UI",sans-serif;margin:32px;color:#1f2328}}
  h1{{margin-bottom:4px}}
  .meta{{color:#656d76;font-size:13px;margin-bottom:24px}}
  .cards{{display:flex;gap:16px;margin-bottom:24px}}
  .card{{border:1px solid #d0d7de;border-radius:8px;padding:12px 20px;min-width:110px}}
  .card .n{{font-size:24px;font-weight:700}}
  .card .l{{font-size:12px;color:#656d76}}
  table{{border-collapse:collapse;width:100%;font-size:14px}}
  th,td{{border-bottom:1px solid #d8dee4;padding:8px 10px;text-align:left}}
  th{{background:#f6f8fa;font-weight:600}}
  code{{background:#f6f8fa;padding:1px 5px;border-radius:4px;font-size:12px}}
</style></head><body>
<h1>数据质量报告</h1>
<div class="meta">生成时间 {datetime.now():%Y-%m-%d %H:%M:%S} ·
数据库 127.0.0.1:3307 · 规则文件 quality/rules.yaml</div>

<div class="cards">
  <div class="card"><div class="n">{total}</div><div class="l">规则总数</div></div>
  <div class="card"><div class="n" style="color:#1a7f37">{passed}</div><div class="l">通过</div></div>
  <div class="card"><div class="n" style="color:#cf222e">{failed}</div><div class="l">失败</div></div>
  <div class="card"><div class="n" style="color:#0969da">{info}</div><div class="l">观察项</div></div>
  <div class="card"><div class="n">{score}%</div><div class="l">健康分</div></div>
</div>

<table>
<thead><tr>
  <th>ID</th><th>规则</th><th>级别</th><th style="text-align:right">实际</th>
  <th style="text-align:right">期望</th><th>结果</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</body></html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return score, passed, failed, info, total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules", default=str(ROOT / "quality" / "rules.yaml"))
    parser.add_argument("--report", default=str(ROOT / "docs" / "quality-report.html"))
    args = parser.parse_args()

    results = run_checks(args.rules)

    print(f"{'ID':<10}{'规则':<34}{'实际':>8}{'期望':>8}  结果")
    print("-" * 78)
    for r in results:
        expect = "—" if r.get("expect") is None else r["expect"]
        print(f"{r['id']:<10}{r['name']:<34}{str(r['actual']):>8}{str(expect):>8}  {r['status']}")
        if r["msg"]:
            print(f"          ↳ {r['msg']}")

    score, passed, failed, info, total = render_html(results, Path(args.report))
    print("-" * 78)
    print(f"共 {total} 条：通过 {passed}，失败 {failed}，观察 {info}，健康分 {score}%")
    print(f"报告已生成：{args.report}")

    # 失败时返回非 0，方便调度系统判断
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
