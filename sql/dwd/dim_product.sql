-- DWD：商品维度清洗
--
-- 处理规则：
--   1. 按 product_id 去重，保留 etl_time 最新的一条
--   2. product_name / category 为空时兜底为 'unknown'
--   3. price 为负或空时置 0（维度表可以兜底，事实表不行）
--   4. 派生 price_band：把连续的价格离散成三段，方便做价格段分析
--
-- 为什么要有这一层：
--   dws.category_day 和 ads.top_products 都需要"品类"这个属性。
--   如果它们各自 JOIN ods.products，一旦上游改字段、或需要加过滤条件，
--   就要改 N 个地方。统一走 dim_product，只改一处。
--
-- 可重复执行：TRUNCATE + INSERT

TRUNCATE TABLE dwd.dim_product;

INSERT INTO dwd.dim_product
    (product_id, product_name, category, price, price_band)
SELECT
    t.product_id,
    t.product_name,
    t.category,
    t.price,
    CASE
        WHEN t.price < 100   THEN '低价'
        WHEN t.price < 1000  THEN '中价'
        ELSE                      '高价'
    END AS price_band
FROM (
    SELECT
        p.product_id,
        IFNULL(NULLIF(TRIM(p.product_name), ''), 'unknown') AS product_name,
        IFNULL(NULLIF(TRIM(p.category), ''), 'unknown')     AS category,
        CASE WHEN p.price IS NULL OR p.price < 0 THEN 0 ELSE p.price END AS price,
        ROW_NUMBER() OVER (
            PARTITION BY p.product_id
            ORDER BY p.etl_time DESC
        ) AS rn
    FROM ods.products p
) t
WHERE t.rn = 1;

-- ========== 验收 ==========

-- ① 商品数（去重后）
SELECT COUNT(*) AS product_cnt FROM dwd.dim_product;

-- ② 有没有兜底过的脏值（造数数据应该是 0）
SELECT COUNT(*) AS unknown_category
FROM dwd.dim_product WHERE category = 'unknown';

-- ③ 价格段分布
SELECT price_band, COUNT(*) AS cnt
FROM dwd.dim_product
GROUP BY price_band
ORDER BY cnt DESC;

-- ④ 品类分布（应该和 ods.products 一致）
SELECT category, COUNT(*) AS cnt
FROM dwd.dim_product
GROUP BY category
ORDER BY cnt DESC;
