-- DWS：商品日汇总
--
-- 数据来源：dwd.fact_order_line + dwd.fact_order
-- 时间锚点：created_date（订单下单日期，在明细层已冗余）
--
-- 【口径】sale_qty / sale_amount 只统计【已支付】订单
--   为什么要 JOIN fact_order 过滤 is_paid：
--   明细表里包含所有订单（含取消、未支付）。如果不加过滤，
--   品类/商品的"销售额"会高于 GMV，两个数字永远对不上。
--   统一按支付口径，才能和 ads.gmv_daily 互相印证。

TRUNCATE TABLE dws.product_day;

INSERT INTO dws.product_day (stat_date, product_id, sale_qty, sale_amount, order_cnt)
SELECT
    l.created_date               AS stat_date,
    l.product_id,
    SUM(l.quantity)              AS sale_qty,
    SUM(l.line_amount)           AS sale_amount,
    COUNT(DISTINCT l.order_no)   AS order_cnt
FROM dwd.fact_order_line l
JOIN dwd.fact_order o ON l.order_no = o.order_no
WHERE o.is_paid = 1
AND o.created_date < CURDATE()
GROUP BY l.created_date, l.product_id;

-- ========== 验收 ==========

-- ① 行数
SELECT COUNT(*) AS product_day_rows FROM dws.product_day;

-- ② 守恒：已支付订单的明细金额合计，必须等于订单层 GMV
SELECT
    (SELECT ROUND(SUM(sale_amount),2) FROM dws.product_day) AS dws_amount,
    (SELECT ROUND(SUM(pay_amount),2) FROM dwd.fact_order WHERE is_paid = 1) AS dwd_gmv;

-- ③ 看一眼销量最高的商品日
SELECT * FROM dws.product_day ORDER BY sale_qty DESC LIMIT 5;
