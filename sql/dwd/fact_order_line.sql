-- DWD：订单行事实清洗
--
-- 粒度：一行 = 一个订单里的一个商品
--
-- 处理规则：
--   1. 只保留能在 dwd.fact_order 找到的订单明细
--      —— 订单在 DWD 被丢弃了（脏数据），它的明细也不该留下，否则会出现孤儿行
--   2. 明细去重：ODS 里重复订单的明细也被复制了一份，完全相同的两行必须去掉
--      分区键用 (order_no, product_id)，因为同一订单内同一个商品只会出现一次
--   3. line_amount = quantity * unit_price，落库时算好，避免下游反复计算
--   4. created_date 从订单冗余下来，方便按天算商品销量
--
-- 依赖：必须先跑 fact_order.sql（本脚本 JOIN 了 dwd.fact_order）
-- 可重复执行：先 TRUNCATE 再 INSERT

TRUNCATE TABLE dwd.fact_order_line;

INSERT INTO dwd.fact_order_line
    (order_no, product_id, quantity, unit_price, line_amount, created_date)
SELECT
    i.order_no,
    i.product_id,
    i.quantity,
    i.unit_price,
    i.quantity * i.unit_price AS line_amount,
    o.created_date
FROM (
    -- 明细去重：同一个 (order_no, product_id) 只留 etl_time 最新的一行
    SELECT
        it.*,
        ROW_NUMBER() OVER (
            PARTITION BY it.order_no, it.product_id
            ORDER BY it.etl_time DESC
        ) AS rn
    FROM ods.order_items it
) i
-- JOIN 同时起两个作用：过滤掉已作废订单的明细，并拿到 created_date
JOIN dwd.fact_order o ON i.order_no = o.order_no
WHERE i.rn = 1;

-- ========== 验收 ==========

-- ① 行数：应该 ≈ 29000（10 万单规模时 ≈ 290000），明显小于 9820 说明分区键写错了
SELECT COUNT(*) AS line_cnt FROM dwd.fact_order_line;

-- ② 孤儿检查：必须为 0
SELECT COUNT(*) AS orphan_cnt
FROM dwd.fact_order_line l
LEFT JOIN dwd.fact_order o ON l.order_no = o.order_no
WHERE o.order_no IS NULL;

-- ③ 金额对账：必须为 0
-- 这条同时验证了「去重是否正确」和「金额计算是否正确」
SELECT COUNT(*) AS mismatch_cnt
FROM (
    SELECT o.order_no, o.pay_amount, SUM(l.line_amount) AS s
    FROM dwd.fact_order o
    JOIN dwd.fact_order_line l ON o.order_no = l.order_no
    GROUP BY o.order_no, o.pay_amount
    HAVING ABS(o.pay_amount - s) > 0.01
) t;
