-- DWD 层表结构
-- 与 ODS 的区别：这里可以加主键、加约束、加索引，因为数据已经清洗过

-- 用户维度
CREATE TABLE IF NOT EXISTS dwd.dim_user (
    user_id       BIGINT PRIMARY KEY,
    user_name     VARCHAR(64),
    phone         VARCHAR(32),
    city          VARCHAR(64),
    register_date DATE,
    etl_time      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 商品维度
-- 存在的意义：让 DWS/ADS 不再直接读 ods.products
--   1. 上游改字段名/加过滤条件时，只改这一处的 ETL
--   2. 承接商品侧的脏数据（重复 product_id、品类为空、价格异常）
--   3. 沉淀派生属性（price_band 价格段），业务分析直接用，不用每次算
CREATE TABLE IF NOT EXISTS dwd.dim_product (
    product_id   BIGINT PRIMARY KEY,
    product_name VARCHAR(128),
    category     VARCHAR(64),
    price        DECIMAL(10, 2) COMMENT '标价，非成交价',
    price_band   VARCHAR(16) COMMENT '派生：低价<100 / 中价<1000 / 高价>=1000',
    etl_time     DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_category (category)
);

-- 订单事实（订单粒度：一行 = 一个订单）
CREATE TABLE IF NOT EXISTS dwd.fact_order (
    order_no     VARCHAR(32) PRIMARY KEY,
    user_id      BIGINT,
    order_status VARCHAR(16),
    pay_amount   DECIMAL(10, 2),
    is_paid      TINYINT COMMENT '1=已支付(paid/shipped/finished)，0=未支付',
    created_at   DATETIME,
    paid_at      DATETIME,
    created_date DATE COMMENT '冗余日期列，避免查询时对 created_at 做函数运算',
    paid_date    DATE COMMENT 'GMV 按天归属用这一列',
    etl_time     DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_user (user_id),
    KEY idx_created_date (created_date),
    KEY idx_paid_date (paid_date)
);

-- 订单行事实（订单行粒度：一行 = 一个订单里的一个商品）
CREATE TABLE IF NOT EXISTS dwd.fact_order_line (
    order_no     VARCHAR(32),
    product_id   BIGINT,
    quantity     INT,
    unit_price   DECIMAL(10, 2),
    line_amount  DECIMAL(10, 2) COMMENT '= quantity * unit_price',
    created_date DATE COMMENT '从订单冗余下来，方便按天算商品销量',
    KEY idx_order (order_no),
    KEY idx_product (product_id),
    KEY idx_created_date (created_date)
);
