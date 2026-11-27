-- ADS：GMV 日报
--
-- 数据来源：dwd.fact_order（不从 dws.user_day 取！）
-- 原因：dws.user_day 锚定 created_date（下单日期），GMV 要按 paid_date（支付日期）统计。
--       两张表时间口径不同，混用会导致"今天的 GMV"含义不一致。
--
-- 口径：
--   gmv              = 当天支付订单的 pay_amount 合计
--   paid_order_cnt   = 当天支付的订单数
--   paid_user_cnt    = 当天支付的去重用户数（一人多单只算一次）
--   avg_order_amount = gmv / paid_order_cnt

TRUNCATE TABLE ads.gmv_daily;

INSERT INTO ads.gmv_daily
    (stat_date, gmv, paid_order_cnt, paid_user_cnt, avg_order_amount)
SELECT
    o.paid_date                            AS stat_date,
    SUM(o.pay_amount)                      AS gmv,
    COUNT(*)                               AS paid_order_cnt,
    COUNT(DISTINCT o.user_id)              AS paid_user_cnt,
    ROUND(SUM(o.pay_amount) / COUNT(*), 2) AS avg_order_amount
FROM dwd.fact_order o
WHERE o.is_paid = 1
  AND o.paid_date IS NOT NULL
  AND o.paid_date < CURDATE()
GROUP BY o.paid_date;

-- ========== 验收 ==========

-- ① 行数（天数）
SELECT COUNT(*) AS days FROM ads.gmv_daily;

-- ② 守恒：ADS 的 GMV 合计 必须等于 DWD 里已支付订单的金额合计
SELECT
    (SELECT SUM(gmv) FROM ads.gmv_daily) AS ads_gmv,
    (SELECT SUM(pay_amount) FROM dwd.fact_order WHERE is_paid = 1) AS dwd_paid_amount;

-- ③ 订单数守恒
SELECT
    (SELECT SUM(paid_order_cnt) FROM ads.gmv_daily) AS ads_orders,
    (SELECT COUNT(*) FROM dwd.fact_order WHERE is_paid = 1) AS dwd_paid_orders;
