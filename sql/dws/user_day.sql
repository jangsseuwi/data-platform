-- DWS：用户日汇总
--
-- 数据来源：dwd.fact_order（订单事实）+ dwd.dim_user（用户维度）
-- 时间锚点：created_date（下单日期）
--
-- 核心写法：条件聚合
--   SUM(CASE WHEN is_paid = 1 THEN 1 ELSE 0 END)  -> 满足条件的行数
--   SUM(CASE WHEN is_paid = 1 THEN pay_amount ELSE 0 END) -> 满足条件的金额合计
--   这种"一次扫描算出多个指标"的写法是汇总层的基本功

TRUNCATE TABLE dws.user_day;

INSERT INTO dws.user_day
    (stat_date, user_id, order_cnt, order_amount, paid_order_cnt, paid_amount, is_new)
SELECT
    o.created_date                        AS stat_date,
    o.user_id,
    COUNT(*)                              AS order_cnt,
    SUM(o.pay_amount)                     AS order_amount,
    SUM(CASE WHEN o.is_paid = 1 THEN 1 ELSE 0 END)            AS paid_order_cnt,
    SUM(CASE WHEN o.is_paid = 1 THEN o.pay_amount ELSE 0 END) AS paid_amount,
    CASE WHEN u.register_date = o.created_date THEN 1 ELSE 0 END AS is_new
FROM dwd.fact_order o
JOIN dwd.dim_user u ON o.user_id = u.user_id
AND o.created_date < CURDATE()
GROUP BY o.created_date, o.user_id, u.register_date;

-- ========== 验收 ==========

-- ① 行数：用户日组合数
SELECT COUNT(*) AS user_day_rows FROM dws.user_day;

-- ② 总下单数必须等于 DWD 订单数（这两条不相等说明 JOIN 丢数据了）
SELECT
    (SELECT SUM(order_cnt) FROM dws.user_day)   AS dws_orders,
    (SELECT COUNT(*) FROM dwd.fact_order)       AS dwd_orders;

-- ③ 总金额必须等于 DWD 订单金额合计
SELECT
    (SELECT SUM(order_amount) FROM dws.user_day) AS dws_amount,
    (SELECT SUM(pay_amount) FROM dwd.fact_order) AS dwd_amount;

-- ④ 新客数（当天注册且当天有下单的用户数）
SELECT SUM(is_new) AS new_user_orders FROM dws.user_day;

-- ⑤ 看一眼数据长什么样
SELECT * FROM dws.user_day ORDER BY stat_date DESC, order_amount DESC LIMIT 10;
