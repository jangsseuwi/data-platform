-- ADS：Top 商品榜（分品类，每天每品类 Top5）
--
-- 数据来源：dws.product_day（已按支付口径汇总）+ dwd.dim_product（拿品类和名称）
--
-- 为什么分品类：
--   全局 TopN 会被高单价品类（电脑、手机）包揽，图书/食品永远上不了榜，
--   榜单失去"发现黑马"的意义。分品类排名才能看出每个垂类的头部商品。
--
-- 排序并列时用 sale_amount 做第二排序键，保证结果稳定（可复现）

TRUNCATE TABLE ads.top_products;

INSERT INTO ads.top_products
    (stat_date, category, rank_no, product_id, product_name, sale_qty, sale_amount)
SELECT
    t.stat_date,
    t.category,
    t.rn          AS rank_no,
    t.product_id,
    t.product_name,
    t.sale_qty,
    t.sale_amount
FROM (
    SELECT
        pd.stat_date,
        p.category,
        p.product_name,
        pd.product_id,
        pd.sale_qty,
        pd.sale_amount,
        ROW_NUMBER() OVER (
            PARTITION BY pd.stat_date, p.category
            ORDER BY pd.sale_qty DESC, pd.sale_amount DESC
        ) AS rn
    FROM dws.product_day pd
    JOIN dwd.dim_product p ON pd.product_id = p.product_id
) t
WHERE t.rn <= 5;

-- ========== 验收 ==========

SELECT COUNT(*) AS top_rows FROM ads.top_products;

-- 每天每品类应该正好 5 条（有销量的品类）
SELECT stat_date, category, COUNT(*) AS cnt
FROM ads.top_products
GROUP BY stat_date, category
ORDER BY stat_date DESC, category
LIMIT 8;

-- 某个品类的榜单长什么样
SELECT * FROM ads.top_products
WHERE category = '电脑'
ORDER BY stat_date DESC, rank_no
LIMIT 5;
