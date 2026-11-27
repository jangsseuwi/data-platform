-- DWS：品类日汇总
--
-- 数据来源：dwd.fact_order_line + dwd.fact_order + dwd.dim_product
-- 时间锚点：created_date
--
-- 【口径】同样只统计【已支付】订单，保证和 GMV / product_day 一致
--
-- 和 product_day 的区别：
--   product_day 一行一个商品，粒度细
--   category_day 一行一个品类，是 product_day 的上卷（roll-up）

TRUNCATE TABLE dws.category_day;

INSERT INTO dws.category_day (stat_date, category, sale_qty, sale_amount, sku_cnt)
SELECT
    l.created_date                       AS stat_date,
    p.category,
    SUM(l.quantity)                      AS sale_qty,
    SUM(l.line_amount)                   AS sale_amount,
    COUNT(DISTINCT l.product_id)         AS sku_cnt
FROM dwd.fact_order_line l
JOIN dwd.fact_order o ON l.order_no = o.order_no
JOIN dwd.dim_product p ON l.product_id = p.product_id
WHERE o.is_paid = 1
AND o.created_date < CURDATE()
GROUP BY l.created_date, p.category;

-- ========== 验收 ==========

-- ① 行数
SELECT COUNT(*) AS category_day_rows FROM dws.category_day;

-- ② 守恒：品类合计 = 商品合计 = GMV
SELECT
    (SELECT ROUND(SUM(sale_amount),2) FROM dws.category_day) AS cat_amount,
    (SELECT ROUND(SUM(sale_amount),2) FROM dws.product_day)  AS prod_amount,
    (SELECT ROUND(SUM(pay_amount),2) FROM dwd.fact_order WHERE is_paid = 1) AS gmv;

-- ③ 品类结构
SELECT category,
       ROUND(SUM(sale_amount),2) AS amount,
       SUM(sale_qty) AS qty
FROM dws.category_day
GROUP BY category
ORDER BY amount DESC;
