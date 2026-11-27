# 数据字典（Data Dictionary）

> 技术视角的表/字段说明。业务口径请看 [`metrics.md`](metrics.md)。
>
> 本文档描述的是**结构**：这张表有什么字段、字段从哪来、粒度是什么。
> 指标怎么算，不在本文档范围内。

| 项 | 内容 |
|---|---|
| 版本 | v1.0 |
| 最后更新 | 2026-11-27 |
| 数据库 | MySQL 8.4 · `127.0.0.1:3307` |
| 表数量 | 14 张（ods 4 / dwd 4 / dws 3 / ads 3） |

---

## 一、表清单

| 层 | 表名 | 粒度（一行代表） | 行数 | 主键 | 更新方式 |
|---|---|---|---|---|---|
| ods | `ods.users` | 一次上游推送的用户记录 | 20,000 | 无 | 全量覆盖 |
| ods | `ods.products` | 一个商品 | 2,000 | 无 | 全量覆盖 |
| ods | `ods.orders` | 一次上游推送的订单记录 | 100,300 | 无 | 全量覆盖 |
| ods | `ods.order_items` | 一条订单商品明细 | 300,350 | 无 | 全量覆盖 |
| dwd | `dwd.dim_user` | 一个用户 | 20,000 | `user_id` | TRUNCATE + INSERT |
| dwd | `dwd.dim_product` | 一个商品 | 2,000 | `product_id` | TRUNCATE + INSERT |
| dwd | `dwd.fact_order` | 一个订单 | 98,200 | `order_no` | TRUNCATE + INSERT |
| dwd | `dwd.fact_order_line` | 一个订单里的一个商品 | 293,996 | 无（`order_no`+`product_id` 逻辑唯一） | TRUNCATE + INSERT |
| dws | `dws.user_day` | 一个用户在某一天的下单行为 | 90,969 | `(stat_date, user_id)` | TRUNCATE + INSERT |
| dws | `dws.product_day` | 一个商品在某一天的销售 | 135,164 | `(stat_date, product_id)` | TRUNCATE + INSERT |
| dws | `dws.category_day` | 一个品类在某一天的销售 | 540 | `(stat_date, category)` | TRUNCATE + INSERT |
| ads | `ads.gmv_daily` | 一天的 GMV | 91 | `stat_date` | TRUNCATE + INSERT |
| ads | `ads.top_products` | 某天某品类的一个名次 | 2,700 | `(stat_date, category, rank_no)` | TRUNCATE + INSERT |
| ads | `ads.user_retention` | 一个首购日 cohort 的留存 | 60 | `cohort_date` | TRUNCATE + INSERT |

> ODS 层故意**不建主键**：要容纳重复、空值等脏数据。
> 正确性由 DWD 层保证，详见 [`dirty-data.md`](dirty-data.md)。

---

## 二、ODS 层（原始层）

> 职责：原样保存上游数据，不做任何清洗。所有字段与上游一一对应。

### `ods.users`

| 字段 | 类型 | 含义 | 来源 |
|---|---|---|---|
| `user_id` | BIGINT | 用户唯一标识 | 上游用户系统 |
| `user_name` | VARCHAR(64) | 姓名 | 上游 |
| `phone` | VARCHAR(32) | 手机号 | 上游，未做格式标准化 |
| `city` | VARCHAR(64) | 城市 | 上游，存在「哈尔滨市 / 哈尔滨县」写法不一致 |
| `register_at` | DATETIME | 注册时间 | 上游 |
| `etl_time` | DATETIME | 入库时间 | 本层生成，用于去重时判断新旧 |

### `ods.products`

| 字段 | 类型 | 含义 | 来源 |
|---|---|---|---|
| `product_id` | BIGINT | 商品 ID | 上游商品系统 |
| `product_name` | VARCHAR(128) | 商品名 | 上游 |
| `category` | VARCHAR(64) | 品类 | 上游，6 类：手机/电脑/家电/食品/图书/服饰 |
| `price` | DECIMAL(10,2) | **标价**（非成交价） | 上游 |
| `etl_time` | DATETIME | 入库时间 | 本层生成 |

### `ods.orders`

| 字段 | 类型 | 含义 | 说明 |
|---|---|---|---|
| `order_no` | VARCHAR(32) | 订单号，`SO` + 16 位数字 | **允许重复**（脏数据） |
| `user_id` | BIGINT | 下单用户 | **允许为空**（脏数据） |
| `order_status` | VARCHAR(16) | 订单状态 | created/paid/shipped/finished/cancelled；**允许 unknown** |
| `pay_amount` | DECIMAL(10,2) | 订单应付金额 | **允许为负**（脏数据） |
| `created_at` | DATETIME | 下单时间 | |
| `paid_at` | DATETIME | 支付时间 | 未支付为 NULL；**允许早于 created_at** |
| `etl_time` | DATETIME | 入库时间 | 去重依据 |

### `ods.order_items`

| 字段 | 类型 | 含义 | 说明 |
|---|---|---|---|
| `order_no` | VARCHAR(32) | 关联订单号 | 无外键约束 |
| `product_id` | BIGINT | 商品 ID | |
| `quantity` | INT | 购买件数 | |
| `unit_price` | DECIMAL(10,2) | **成交单价**（可能与标价不同） | |
| `etl_time` | DATETIME | 入库时间 | 去重依据 |

> 已知缺陷：本表**没有行 ID**，去重只能靠 `(order_no, product_id)` 组合。
> 真实系统应给明细表一个自增 `item_id`。

---

## 三、DWD 层（明细层）

> 职责：清洗、去重、补维度。可以建主键和索引，因为数据已可信。
> 清洗规则见各 SQL 文件头部注释。

### `dwd.dim_user`

| 字段 | 类型 | 含义 | 来源 / 派生逻辑 |
|---|---|---|---|
| `user_id` | BIGINT | 用户 ID，**主键** | `ods.users.user_id` 去重 |
| `user_name` | VARCHAR(64) | 姓名 | 空值/空串兜底为 `'unknown'` |
| `phone` | VARCHAR(32) | 手机号 | 原样 |
| `city` | VARCHAR(64) | 城市 | 空值兜底为 `'unknown'`，**未做标准化** |
| `register_date` | DATE | 注册日期 | `DATE(register_at)`，冗余列 |
| `etl_time` | DATETIME | 入库时间 | 本层生成 |

### `dwd.dim_product`

| 字段 | 类型 | 含义 | 来源 / 派生逻辑 |
|---|---|---|---|
| `product_id` | BIGINT | 商品 ID，**主键** | `ods.products` 去重（保留 `etl_time` 最新） |
| `product_name` | VARCHAR(128) | 商品名 | 空值/空串兜底为 `'unknown'` |
| `category` | VARCHAR(64) | 品类 | 空值兜底为 `'unknown'` |
| `price` | DECIMAL(10,2) | 标价（非成交价） | 负值或 NULL 置 0 |
| `price_band` | VARCHAR(16) | 价格段 | **派生**：`<100` 低价 / `<1000` 中价 / 其余高价 |
| `etl_time` | DATETIME | 入库时间 | 本层生成 |

> 为什么要单独建这张表：`dws.category_day` 和 `ads.top_products` 都需要「品类」属性，
> 各自 JOIN `ods.products` 会导致同一个字段在两处解析。统一走 `dim_product` 后，
> 上游改字段名、加过滤条件，只需改这一处的 ETL。

### `dwd.fact_order`

| 字段 | 类型 | 含义 | 来源 / 派生逻辑 |
|---|---|---|---|
| `order_no` | VARCHAR(32) | 订单号，**主键** | 重复时保留 `etl_time` 最新 |
| `user_id` | BIGINT | 下单用户 | 为空的订单已丢弃 |
| `order_status` | VARCHAR(16) | 状态 | 越界值已丢弃 |
| `pay_amount` | DECIMAL(10,2) | 订单金额 | 负值已丢弃 |
| `is_paid` | TINYINT | 是否已支付 | **派生**：status ∈ (paid, shipped, finished) → 1 |
| `created_at` | DATETIME | 下单时间 | |
| `paid_at` | DATETIME | 支付时间 | 早于 created_at 的已丢弃 |
| `created_date` | DATE | 下单日期 | **派生冗余**，避免查询时对 `created_at` 做函数运算 |
| `paid_date` | DATE | 支付日期 | **派生冗余**，GMV 按此归属 |

### `dwd.fact_order_line`

| 字段 | 类型 | 含义 | 来源 / 派生逻辑 |
|---|---|---|---|
| `order_no` | VARCHAR(32) | 关联订单 | 只保留 `dwd.fact_order` 中存在的订单 |
| `product_id` | BIGINT | 商品 ID | |
| `quantity` | INT | 件数 | |
| `unit_price` | DECIMAL(10,2) | 成交单价 | |
| `line_amount` | DECIMAL(10,2) | 行金额 | **派生**：`quantity * unit_price` |
| `created_date` | DATE | 下单日期 | **派生**：从订单冗余，供按天算销量使用 |

---

## 四、DWS 层（汇总层）

> 职责：按维度预聚合，供多个 ADS 指标复用。
> **口径统一为「已支付」**（`is_paid = 1`），与 ADS 的 GMV 可互相印证。

### `dws.user_day`

| 字段 | 类型 | 含义 |
|---|---|---|
| `stat_date` | DATE | 统计日期 = **下单日期** |
| `user_id` | BIGINT | 用户 |
| `order_cnt` | INT | 当天创建的订单数 |
| `order_amount` | DECIMAL(14,2) | 当天创建订单的金额合计（**含未支付**） |
| `paid_order_cnt` | INT | 其中已支付的订单数 |
| `paid_amount` | DECIMAL(14,2) | 其中已支付的金额 |
| `is_new` | TINYINT | 1 = 当天注册的新客（注册新客，非首购新客） |

### `dws.product_day` / `dws.category_day`

| 字段 | 商品日 | 品类日 | 含义 |
|---|---|---|---|
| `stat_date` | ✅ | ✅ | 统计日期 = 下单日期 |
| `product_id` | ✅ | — | 商品 |
| `category` | — | ✅ | 品类 |
| `sale_qty` | ✅ | ✅ | 销量（件），仅已支付 |
| `sale_amount` | ✅ | ✅ | 销售额，仅已支付 |
| `order_cnt` | ✅ | — | 买过该商品的去重订单数 |
| `sku_cnt` | — | ✅ | 当天有销量的商品数（动销 SKU） |

---

## 五、ADS 层（应用层）

> 职责：面向具体报表，一张表服务一个看板卡片。

### `ads.gmv_daily`

| 字段 | 类型 | 含义 |
|---|---|---|
| `stat_date` | DATE | 统计日期 = **支付日期**（与 DWS 的下单口径不同） |
| `gmv` | DECIMAL(16,2) | 当天支付金额合计 |
| `paid_order_cnt` | INT | 当天支付订单数 |
| `paid_user_cnt` | INT | 当天支付去重用户数 |
| `avg_order_amount` | DECIMAL(12,2) | 客单价 = gmv / paid_order_cnt |

### `ads.top_products`

| 字段 | 类型 | 含义 |
|---|---|---|
| `stat_date` | DATE | 统计日期 |
| `category` | VARCHAR(64) | 品类（**分品类排名**，不是全局榜） |
| `rank_no` | INT | 品类内排名 1–5 |
| `product_id` / `product_name` | BIGINT / VARCHAR | 商品 |
| `sale_qty` / `sale_amount` | INT / DECIMAL | 销量、销售额 |

### `ads.user_retention`

| 字段 | 类型 | 含义 |
|---|---|---|
| `cohort_date` | DATE | **首次下单日期**（不是注册日期） |
| `cohort_users` | INT | 该 cohort 用户数 |
| `d1_users` / `d7_users` / `d30_users` | INT | 首购后第 N 天回访人数 |
| `d1_rate` / `d7_rate` / `d30_rate` | DECIMAL(6,2) | 留存率（%） |

---

## 六、表之间的依赖关系

```
ods.users ─────────────┐
                       ├─▶ dwd.dim_user ──┐
ods.orders ──▶ dwd.fact_order ─────────────┼─▶ dws.user_day
                    │                      │
                    ├─▶ dwd.fact_order_line ──▶ dws.product_day ──▶ ads.top_products
                    │                      └─▶ dws.category_day
                    ├─▶ ads.gmv_daily
                    └─▶ ads.user_retention
ods.order_items ──▶ dwd.fact_order_line
ods.products ─────▶ dwd.dim_product ──▶ dws.category_day / ads.top_products
```

> 四层完整闭环：ODS 只被 DWD 读取，DWD 只被 DWS/ADS 读取，没有跨层引用。
