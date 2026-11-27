"""
造数脚本：生成电商业务数据，并注入可控的脏数据。

设计原则：
  1. 数据量可配置（默认 10 万订单）
  2. 脏数据按比例注入，且每类都能被后续的质量规则抓到
  3. 正常订单必须满足：pay_amount == sum(quantity * unit_price)
  4. 用批量插入，不要逐条 insert
  5. 固定随机种子，保证每次造出来的数据一样，质量报告的数字才可复现

数据真实性（v2 改造）：
  - 用户下单服从帕累托：20% 的重度用户贡献约 80% 的订单（有复购，才能算留存/复购率）
  - 商品价格按品类长尾分布：食品 9.9 起，电脑可到 9999
  - 品类有权重：手机 35% / 电脑 20% / 家电 15% / 食品 15% / 图书 10% / 服饰 5%
  - 时间窗口对齐整天，避免首日只有几个小时的数据

用法：
    python etl/gen_data.py --orders 100000
    python etl/gen_data.py --orders 10000 --seed 7
"""

import argparse
import random
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

import pymysql
from faker import Faker

fake = Faker("zh_CN")

# ---------- 连接配置 ----------
DB = dict(
    host="127.0.0.1",
    port=3307,          # 注意是 3307，不是 3306
    user="root",
    password="root123",
    charset="utf8mb4",
)

# ---------- 规模 ----------
N_USERS = 20_000
N_PRODUCTS = 2_000

# ---------- 脏数据比例（相对订单总数） ----------
DIRTY_RATE = {
    "null_user":       0.010,
    "negative_amount": 0.005,
    "bad_status":      0.002,
    "time_travel":     0.001,
    "duplicate_order": 0.003,
}

ORDER_STATUS = ["created", "paid", "shipped", "finished", "cancelled"]
ORDER_STATUS_WEIGHTS = [10, 25, 20, 40, 5]

# 品类 → (最低价, 最高价)；权重决定商品的品类分布
CATEGORY_CONFIG = {
    "手机": (999, 5999),
    "电脑": (2999, 9999),
    "家电": (199, 2999),
    "食品": (9.9, 199),
    "图书": (19.9, 129),
    "服饰": (49, 599),
}
CATEGORY_WEIGHTS = [0.35, 0.20, 0.15, 0.15, 0.10, 0.05]

# 帕累托：重度用户占比 + 其下单权重
HEAVY_USER_RATIO = 0.20
HEAVY_USER_WEIGHT = 12


def bulk_insert(conn, table, columns, rows, chunk=5000):
    """分批批量插入。一次 executemany 5000 行，比逐条快两个数量级。"""
    if not rows:
        return 0
    sql = "INSERT INTO {} ({}) VALUES ({})".format(
        table, ", ".join(columns), ", ".join(["%s"] * len(columns))
    )
    total = 0
    with conn.cursor() as cur:
        for i in range(0, len(rows), chunk):
            part = rows[i:i + chunk]
            cur.executemany(sql, part)
            total += len(part)
    conn.commit()
    return total


def reset_ods(conn):
    """清空 ODS 四张表，保证脚本可重复执行。"""
    with conn.cursor() as cur:
        for t in ("ods.order_items", "ods.orders", "ods.products", "ods.users"):
            cur.execute("TRUNCATE TABLE " + t)
    conn.commit()


def gen_users(n):
    """生成用户。返回 (rows, user_ids, user_weights)。"""
    rows = []
    ids = []
    for i in range(1, n + 1):
        ids.append(i)
        rows.append((
            i,
            fake.name(),
            fake.phone_number(),
            fake.city(),
            fake.date_time_between(start_date="-2y", end_date="now"),
        ))

    # 帕累托：抽 20% 的用户当"重度用户"，下单权重是普通用户的 12 倍
    heavy = set(random.sample(ids, int(n * HEAVY_USER_RATIO)))
    weights = [HEAVY_USER_WEIGHT if i in heavy else 1 for i in ids]
    return rows, ids, weights


def gen_products(n):
    """生成商品。返回 (rows, products)，products 是 [(product_id, price)]。"""
    rows = []
    ps = []
    categories = list(CATEGORY_CONFIG.keys())
    for i in range(1, n + 1):
        category = random.choices(categories, weights=CATEGORY_WEIGHTS, k=1)[0]
        low, high = CATEGORY_CONFIG[category]
        # 长尾：平方让便宜商品更多（random()^2 偏向 0）
        price = round(low + (high - low) * (random.random() ** 2), 2)
        ps.append((i, price))
        rows.append((i, fake.word() + fake.word(), category, price))
    return rows, ps


def gen_orders(n, user_ids, user_weights, products):
    """
    生成订单 + 订单明细。

    关键约束：pay_amount == sum(quantity * unit_price)
    """
    # 今天零点之前的 90 个完整自然日，避免首日/末日数据残缺
    end = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    begin = end - timedelta(days=90)
    span_seconds = int((end - begin).total_seconds())

    # 一次性把 n 个订单分配给用户（按帕累托权重）
    assigned_users = random.choices(user_ids, weights=user_weights, k=n)

    order_rows = []
    item_rows = []

    for idx in range(n):
        order_no = "SO" + "".join(random.choices("0123456789", k=16))
        user_id = assigned_users[idx]
        created_at = begin + timedelta(seconds=random.randint(0, span_seconds - 1))

        status = random.choices(ORDER_STATUS, weights=ORDER_STATUS_WEIGHTS, k=1)[0]

        line_count = random.randint(1, 5)
        chosen = random.sample(products, line_count)

        total = Decimal("0")
        for product_id, price in chosen:
            quantity = random.randint(1, 3)
            unit_price = Decimal(str(price))
            total += unit_price * quantity
            item_rows.append((order_no, product_id, quantity, unit_price))

        pay_amount = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if status in ("paid", "shipped", "finished"):
            paid_at = created_at + timedelta(seconds=random.randint(60, 86400))
            if paid_at >= datetime.now():
                paid_at = datetime.now() - timedelta(seconds=60)
        else:
            paid_at = None

        order_rows.append((order_no, user_id, status, pay_amount, created_at, paid_at))

    return order_rows, item_rows


def inject_dirty(order_rows, item_rows, rates):
    """注入脏数据。用 used 集合做互斥抽样，保证每类命中数精确可对账。"""
    total = len(order_rows)
    used = set()
    stats = {}

    def take(rate, eligible=None):
        k = int(round(total * rate))
        pool = [
            i for i in range(total)
            if i not in used and (eligible is None or eligible(i))
        ]
        chosen = random.sample(pool, min(k, len(pool)))
        used.update(chosen)
        return chosen

    idx = take(rates["null_user"])
    for i in idx:
        row = list(order_rows[i])
        row[1] = None
        order_rows[i] = tuple(row)
    stats["null_user"] = len(idx)

    idx = take(rates["negative_amount"], eligible=lambda i: order_rows[i][3] > 0)
    for i in idx:
        row = list(order_rows[i])
        row[3] = -row[3]
        order_rows[i] = tuple(row)
    stats["negative_amount"] = len(idx)

    idx = take(rates["bad_status"])
    for i in idx:
        row = list(order_rows[i])
        row[2] = "unknown"
        order_rows[i] = tuple(row)
    stats["bad_status"] = len(idx)

    idx = take(rates["time_travel"], eligible=lambda i: order_rows[i][5] is not None)
    for i in idx:
        row = list(order_rows[i])
        row[5] = row[4] - timedelta(days=1)
        order_rows[i] = tuple(row)
    stats["time_travel"] = len(idx)

    items_by_order = defaultdict(list)
    for it in item_rows:
        items_by_order[it[0]].append(it)

    idx = take(rates["duplicate_order"])
    for i in idx:
        dup = order_rows[i]
        order_rows.append(dup)
        item_rows.extend(items_by_order[dup[0]])
    stats["duplicate_order"] = len(idx)

    print("  注入明细（原始订单数 {}）：".format(total))
    for name, cnt in stats.items():
        print("    {:16s} {:>6d} 条  ({:.2f}%)".format(name, cnt, cnt / total * 100))
    print("  最终订单行数：{}（含重复 {} 条）".format(len(order_rows), stats["duplicate_order"]))
    print("  最终明细行数：{}".format(len(item_rows)))
    return order_rows, item_rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--orders", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    Faker.seed(args.seed)

    conn = pymysql.connect(**DB)

    print("清空 ODS ...")
    reset_ods(conn)

    print("生成用户...")
    user_rows, user_ids, user_weights = gen_users(N_USERS)
    print("  插入", bulk_insert(conn, "ods.users",
                                ["user_id", "user_name", "phone", "city", "register_at"],
                                user_rows))

    print("生成商品...")
    product_rows, products = gen_products(N_PRODUCTS)
    print("  插入", bulk_insert(conn, "ods.products",
                                ["product_id", "product_name", "category", "price"],
                                product_rows))

    print("生成订单...")
    order_rows, item_rows = gen_orders(args.orders, user_ids, user_weights, products)

    print("注入脏数据...")
    order_rows, item_rows = inject_dirty(order_rows, item_rows, DIRTY_RATE)

    print("  插入 orders:", bulk_insert(
        conn, "ods.orders",
        ["order_no", "user_id", "order_status", "pay_amount", "created_at", "paid_at"],
        order_rows))
    print("  插入 order_items:", bulk_insert(
        conn, "ods.order_items",
        ["order_no", "product_id", "quantity", "unit_price"],
        item_rows))

    conn.close()
    print("完成")


if __name__ == "__main__":
    main()
