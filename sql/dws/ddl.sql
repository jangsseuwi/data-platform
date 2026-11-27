-- DWS 层表结构（汇总层）
--
-- 设计原则：
--   1. 每张表锚定【一个】时间维度，避免粒度污染
--   2. 主键 = 维度组合，保证可重复执行（重跑不会重复）
--   3. 只存"可复用"的汇总，面向具体报表的放 ADS

-- 用户日汇总：一行 = 一个用户在某一天的下单行为
-- 时间维度：created_date（下单日期）
CREATE TABLE IF NOT EXISTS dws.user_day (
    stat_date       DATE          NOT NULL COMMENT '统计日期 = 下单日期',
    user_id         BIGINT        NOT NULL,
    order_cnt       INT           NOT NULL DEFAULT 0 COMMENT '当天创建的订单数',
    order_amount    DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '当天创建订单的金额合计',
    paid_order_cnt  INT           NOT NULL DEFAULT 0 COMMENT '其中已支付的订单数',
    paid_amount     DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '其中已支付的金额合计',
    is_new          TINYINT       NOT NULL DEFAULT 0 COMMENT '1=当天注册的新客',
    PRIMARY KEY (stat_date, user_id),
    KEY idx_user (user_id)
);

-- 商品日汇总：一行 = 一个商品在某一天的销售情况
-- 时间维度：created_date（订单下单日期）
CREATE TABLE IF NOT EXISTS dws.product_day (
    stat_date    DATE          NOT NULL,
    product_id   BIGINT        NOT NULL,
    sale_qty     INT           NOT NULL DEFAULT 0 COMMENT '销量（件数）',
    sale_amount  DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '销售额',
    order_cnt    INT           NOT NULL DEFAULT 0 COMMENT '买过该商品的订单数（去重）',
    PRIMARY KEY (stat_date, product_id),
    KEY idx_product (product_id)
);

-- 品类日汇总：一行 = 一个品类在某一天的销售情况
-- 比 product_day 少一个维度层级，用于品类趋势和结构分析
CREATE TABLE IF NOT EXISTS dws.category_day (
    stat_date    DATE          NOT NULL,
    category     VARCHAR(64)   NOT NULL,
    sale_qty     INT           NOT NULL DEFAULT 0,
    sale_amount  DECIMAL(14,2) NOT NULL DEFAULT 0,
    sku_cnt      INT           NOT NULL DEFAULT 0 COMMENT '当天有销量的商品数（动销SKU）',
    PRIMARY KEY (stat_date, category)
);
