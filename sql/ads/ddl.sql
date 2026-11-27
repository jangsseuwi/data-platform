-- ADS 层表结构（应用层）
--
-- 设计原则：
--   1. 一张表对应一个具体的报表/看板需求，不做通用设计
--   2. 列名即指标名，业务方看得懂
--   3. 金额统一 DECIMAL(16,2)，避免大额溢出

-- GMV 日报：一行 = 一天的收入情况
-- 时间锚点：paid_date（支付日期）—— 钱哪天到账算哪天
CREATE TABLE IF NOT EXISTS ads.gmv_daily (
    stat_date        DATE          NOT NULL COMMENT '统计日期 = 支付日期',
    gmv              DECIMAL(16,2) NOT NULL DEFAULT 0 COMMENT '当天支付金额合计',
    paid_order_cnt   INT           NOT NULL DEFAULT 0 COMMENT '当天支付的订单数',
    paid_user_cnt    INT           NOT NULL DEFAULT 0 COMMENT '当天支付的去重用户数',
    avg_order_amount DECIMAL(12,2) NOT NULL DEFAULT 0 COMMENT '客单价 = GMV / 支付订单数',
    PRIMARY KEY (stat_date)
);
