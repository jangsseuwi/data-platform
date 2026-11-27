-- ODS 层表结构
-- 设计要点：故意不建主键、不加唯一约束、不加 NOT NULL
-- 因为 ODS 的职责是"原样保存源系统数据"，脏数据也必须能进来

CREATE TABLE IF NOT EXISTS ods.users (
    user_id      BIGINT,
    user_name    VARCHAR(64),
    phone        VARCHAR(32),
    city         VARCHAR(64),
    register_at  DATETIME,
    etl_time     DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ods.products (
    product_id   BIGINT,
    product_name VARCHAR(128),
    category     VARCHAR(64),
    price        DECIMAL(10, 2),
    etl_time     DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ods.orders (
    order_no     VARCHAR(32),
    user_id      BIGINT,
    order_status VARCHAR(16),
    pay_amount   DECIMAL(10, 2),
    created_at   DATETIME,
    paid_at      DATETIME,
    etl_time     DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ods.order_items (
    order_no     VARCHAR(32),
    product_id   BIGINT,
    quantity     INT,
    unit_price   DECIMAL(10, 2),
    etl_time     DATETIME DEFAULT CURRENT_TIMESTAMP
);
