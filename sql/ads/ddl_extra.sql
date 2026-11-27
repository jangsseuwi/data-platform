-- ADS 层表结构（应用层）—— 续

-- Top 商品榜：一行 = 某天某品类的一个名次
-- 分品类排名（否则电脑/手机包揽全局榜单，其他品类永远上不了榜）
CREATE TABLE IF NOT EXISTS ads.top_products (
    stat_date    DATE          NOT NULL,
    category     VARCHAR(64)   NOT NULL,
    rank_no      INT           NOT NULL COMMENT '品类内排名，从 1 开始',
    product_id   BIGINT        NOT NULL,
    product_name VARCHAR(128),
    sale_qty     INT           NOT NULL DEFAULT 0,
    sale_amount  DECIMAL(14,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (stat_date, category, rank_no)
);

-- 用户留存：一行 = 一个首购日 cohort 的留存表现
-- cohort 定义：按【首次下单日期】分组（不是注册日期）
CREATE TABLE IF NOT EXISTS ads.user_retention (
    cohort_date  DATE         NOT NULL COMMENT '首次下单日期',
    cohort_users INT          NOT NULL COMMENT '该 cohort 的用户数',
    d1_users     INT          NOT NULL DEFAULT 0 COMMENT '次日回访人数',
    d7_users     INT          NOT NULL DEFAULT 0,
    d30_users    INT          NOT NULL DEFAULT 0,
    d1_rate      DECIMAL(6,2) NOT NULL DEFAULT 0 COMMENT '次日留存率（%）',
    d7_rate      DECIMAL(6,2) NOT NULL DEFAULT 0,
    d30_rate     DECIMAL(6,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (cohort_date)
);
