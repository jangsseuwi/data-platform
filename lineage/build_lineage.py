"""
血缘解析 + DAG 一致性检查

做三件事：
  1. 扫描 sql/**/*.sql，解析出「表 A → 表 B」的依赖边
  2. 生成 docs/lineage.md（Mermaid 图）和 docs/lineage.json
  3. 和 scripts/run_pipeline.py 里声明的任务依赖做比对，发现「SQL 里有依赖但 DAG 没声明」

双引擎：
  - sqlglot：真正的语法树解析，能区分物理表 / CTE / 子查询别名
  - regex：兜底，靠「库名.表名」的特征识别，注释和别名可能误判

用法：
    python lineage/build_lineage.py                 # 自动选引擎
    python lineage/build_lineage.py --engine regex  # 强制正则
"""

import argparse
import importlib.util
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAYERS = ("ods", "dwd", "dws", "ads")
QUALIFIED = r"(?:" + "|".join(LAYERS) + r")\.[A-Za-z_][A-Za-z0-9_]*"

RE_CREATE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(" + QUALIFIED + r")", re.I)
RE_INSERT = re.compile(r"INSERT\s+INTO\s+(" + QUALIFIED + r")", re.I)
RE_TABLE = re.compile(r"\b(" + QUALIFIED + r")\b", re.I)

ENGINE = "regex"


def strip_comments(text):
    """去掉 -- 开头的整行注释，避免注释里的表名被误判"""
    return "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("--"))


# ------------------------------------------------------------------
# 引擎 1：正则
# ------------------------------------------------------------------
def parse_regex(text):
    text = strip_comments(text)
    creates, edges = set(), []

    for m in RE_CREATE.finditer(text):
        creates.add(m.group(1).lower())

    for stmt in text.split(";"):
        m = RE_INSERT.search(stmt)
        if not m:
            continue
        target = m.group(1).lower()
        for src in {t.lower() for t in RE_TABLE.findall(stmt)}:
            if src != target:
                edges.append((src, target))
    return creates, edges


# ------------------------------------------------------------------
# 引擎 2：sqlglot
# ------------------------------------------------------------------
def parse_sqlglot(text):
    import sqlglot
    from sqlglot import exp

    def name_of(node):
        if isinstance(node, exp.Schema):
            node = node.this
        if not isinstance(node, exp.Table):
            return None
        parts = [p for p in (node.catalog, node.db, node.name) if p]
        return ".".join(parts).lower()

    creates, edges = set(), []
    for stmt in sqlglot.parse(text, dialect="mysql"):
        if stmt is None:
            continue

        if isinstance(stmt, exp.Create):
            n = name_of(stmt.this)
            if n:
                creates.add(n)
            continue

        if not isinstance(stmt, exp.Insert):
            continue

        target = name_of(stmt.this)
        if not target or stmt.expression is None:
            continue

        # CTE 是临时表名，不是物理表，要排除
        cte_names = {c.alias_or_name.lower() for c in stmt.expression.find_all(exp.CTE)}
        for t in stmt.expression.find_all(exp.Table):
            src = name_of(t)
            if src and src not in cte_names and src != target:
                edges.append((src, target))
    return creates, edges


# ------------------------------------------------------------------
# 图与输出
# ------------------------------------------------------------------
def build_graph(edges):
    nodes, children = set(), defaultdict(set)
    for s, t in edges:
        nodes.update((s, t))
        children[s].add(t)
    return sorted(nodes), children


def render_mermaid(nodes, children):
    by_layer = defaultdict(list)
    for n in nodes:
        by_layer[n.split(".")[0]].append(n)

    lines = ["```mermaid", "graph LR"]
    for layer in LAYERS:
        if layer not in by_layer:
            continue
        lines.append(f"  subgraph {layer}")
        for n in sorted(by_layer[layer]):
            lines.append(f'    {n.replace(".", "_")}["{n}"]')
        lines.append("  end")
    for s in sorted(children):
        for t in sorted(children[s]):
            lines.append(f"  {s.replace('.', '_')} --> {t.replace('.', '_')}")
    lines.append("```")
    return "\n".join(lines)


def load_tasks():
    """把 run_pipeline.py 里的 TASKS 读进来（不执行 main）"""
    path = ROOT / "scripts" / "run_pipeline.py"
    spec = importlib.util.spec_from_file_location("run_pipeline", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.TASKS


def parse_file(path, engine):
    text = Path(path).read_text(encoding="utf-8")
    if engine == "sqlglot":
        try:
            return parse_sqlglot(text)
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] sqlglot 解析失败 {Path(path).name}: {e}，回退正则")
            return parse_regex(text)
    return parse_regex(text)


def check_dag_consistency(tasks, file_edges, task_of_table):
    """
    核心检查：SQL 里实际读了哪些表 → 这些表由哪个任务产出 → 该任务必须出现在 deps 里。
    """
    declared = {t["name"]: set(t["deps"]) for t in tasks}
    problems = []

    for t in tasks:
        if t["type"] != "sql":
            continue
        key = t["file"].replace("\\", "/")
        required = set()
        for src, _ in file_edges.get(key, []):
            producer = task_of_table.get(src)
            if producer and producer != t["name"]:
                required.add(producer)
        missing = required - declared[t["name"]]
        if missing:
            problems.append((t["name"], sorted(missing)))
    return problems


def main():
    global ENGINE
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["auto", "sqlglot", "regex"], default="auto")
    parser.add_argument("--sql-dir", default=str(ROOT / "sql"))
    parser.add_argument("--out", default=str(ROOT / "docs"))
    args = parser.parse_args()

    if args.engine == "auto":
        try:
            import sqlglot  # noqa: F401
            ENGINE = "sqlglot"
        except ImportError:
            ENGINE = "regex"
            print("未安装 sqlglot，使用正则引擎（注释/CTE 可能误判）")
            print("安装：python -m pip install sqlglot")
    else:
        ENGINE = args.engine

    tasks = load_tasks()
    file_to_task = {t["file"].replace("\\", "/"): t["name"]
                    for t in tasks if t["type"] == "sql"}

    files = sorted(Path(args.sql_dir).rglob("*.sql"))
    all_edges = set()
    file_edges = {}

    for f in files:
        rel = str(f.relative_to(ROOT)).replace("\\", "/")
        creates, edges = parse_file(f, ENGINE)
        file_edges[rel] = edges
        all_edges |= set(edges)

    # 表 → 产出它的任务
    task_of_table = {}
    for f in files:
        rel = str(f.relative_to(ROOT)).replace("\\", "/")
        task = file_to_task.get(rel)
        if not task:
            continue
        creates, edges = parse_file(f, ENGINE)
        for _, tgt in edges:
            task_of_table[tgt] = task
    for f in files:
        rel = str(f.relative_to(ROOT)).replace("\\", "/")
        task = file_to_task.get(rel)
        if not task:
            continue
        creates, _ = parse_file(f, ENGINE)
        for c in creates:
            task_of_table.setdefault(c, task)

    edges = sorted(all_edges)
    nodes, children = build_graph(edges)
    problems = check_dag_consistency(tasks, file_edges, task_of_table)

    upstream = defaultdict(set)
    for s, t in edges:
        upstream[t].add(s)

    rows = [
        f"| `{n}` | {', '.join(sorted(upstream.get(n, []))) or '—'} "
        f"| {', '.join(sorted(children.get(n, []))) or '—'} |"
        for n in nodes
    ]

    if problems:
        dag_section = "### 发现问题\n\n" + "\n".join(
            f"- 任务 `{t}` 的 SQL 读了需要 **{', '.join(m)}** 产出的表，但 `deps` 里没声明"
            for t, m in problems)
    else:
        dag_section = "全部一致：每个任务的 SQL 依赖，都在 `deps` 里声明了。"

    md = f"""# 数据血缘图

> 自动生成，请勿手工编辑。脚本：`lineage/build_lineage.py`，引擎：**{ENGINE}**

## 血缘图

{render_mermaid(nodes, children)}

## 表级依赖明细

| 表 | 上游（数据来自） | 下游（被谁使用） |
|---|---|---|
{chr(10).join(rows)}

## 与 DAG 声明的一致性检查

{dag_section}

> 检查原理：解析每个任务的 SQL 实际读了哪些表 → 找到产出这些表的任务 →
> 比对 `run_pipeline.py` 里的 `deps`。缺失说明「SQL 改了但 DAG 没改」，会导致乱序执行。
"""

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "lineage.json").write_text(
        json.dumps({"engine": ENGINE, "nodes": nodes,
                    "edges": [{"from": s, "to": t} for s, t in edges],
                    "dag_problems": [{"task": t, "missing": m} for t, m in problems]},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "lineage.md").write_text(md, encoding="utf-8")

    print(f"扫描 {len(files)} 个 SQL 文件 · 引擎 {ENGINE}")
    print(f"节点 {len(nodes)} · 边 {len(edges)}")
    print()
    if problems:
        print("DAG 一致性：发现问题")
        for t, m in problems:
            print(f"  - {t}: 缺少依赖 {', '.join(m)}")
    else:
        print("DAG 一致性：全部一致")
    print()
    print("输出：docs/lineage.md, docs/lineage.json")


if __name__ == "__main__":
    main()
