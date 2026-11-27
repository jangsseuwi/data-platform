-- DWD：订单事实清洗
-- 处理规则：
--   1. user_id 为空        -> 丢弃
--   2. pay_amount < 0      -> 丢弃
--   3. order_status 越界   -> 丢弃
--   4. paid_at < created_at-> 丢弃
--   5. order_no 重复       -> 保留 etl_time 最新的一条
--
-- 为什么要用窗口函数去重：
--   ODS 里同一个 order_no 可能有 2 行（重复订单脏数据），
--   直接 INSERT 会因为主键冲突报错，或者需要 GROUP BY 但又丢了其他列。
--   ROW_NUMBER 能"排序后取第一"，把整行保留下来。

TRUNCATE TABLE dwd.fact_order;

INSERT INTO dwd.fact_order
    (order_no, user_id, order_status, pay_amount, is_paid,
     created_at, paid_at, created_date, paid_date)
SELECT
    order_no,
    user_id,
    order_status,
    pay_amount,
    CASE WHEN order_status IN ('paid', 'shipped', 'finished') THEN 1 ELSE 0 END AS is_paid,
    created_at,
    paid_at,
    DATE(created_at) AS created_date,
    DATE(paid_at)    AS paid_date
FROM (
    SELECT
        o.*,
        ROW_NUMBER() OVER (
            PARTITION BY order_no
            ORDER BY etl_time DESC, created_at DESC
        ) AS rn
    FROM ods.orders o
    WHERE o.user_id IS NOT NULL
      AND o.pay_amount >= 0
      AND o.order_status IN ('created', 'paid', 'shipped', 'finished', 'cancelled')
      AND (o.paid_at IS NULL OR o.paid_at >= o.created_at)
) t
WHERE t.rn = 1;

-- 对账：ODS 总行数 - DWD 行数 = 被丢弃 + 被去重的行数
SELECT
    (SELECT COUNT(*) FROM ods.orders)  AS ods_rows,
    (SELECT COUNT(*) FROM dwd.fact_order) AS dwd_rows,
    (SELECT COUNT(*) FROM ods.orders) - (SELECT COUNT(*) FROM dwd.fact_order) AS dropped;
