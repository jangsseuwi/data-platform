-- ADS：用户留存（按首购日 cohort）
--
-- 数据来源：dwd.fact_order
--
-- 两个关键设计：
--   1. cohort 用【首次下单日期】，不用注册日期
--      注册时间跨 2 年、订单只有 90 天，按注册分群会出现大量"注册了但没下单"的空群
--   2. 剔除观察期不足的 cohort
--      最后 30 天的 cohort 没有足够时间观察到 D30，算进去会把留存率拉低
--
-- 留存定义（严格按"第 N 天"回访，不是"N 天内"）：
--   D1  = 首购后第 1 天有下单
--   D7  = 首购后第 7 天有下单
--   D30 = 首购后第 30 天有下单

TRUNCATE TABLE ads.user_retention;

INSERT INTO ads.user_retention
    (cohort_date, cohort_users, d1_users, d7_users, d30_users,
     d1_rate, d7_rate, d30_rate)
SELECT
    f.cohort_date,
    COUNT(DISTINCT f.user_id)                                        AS cohort_users,
    COUNT(DISTINCT CASE WHEN DATEDIFF(a.created_date, f.cohort_date) = 1  THEN f.user_id END) AS d1_users,
    COUNT(DISTINCT CASE WHEN DATEDIFF(a.created_date, f.cohort_date) = 7  THEN f.user_id END) AS d7_users,
    COUNT(DISTINCT CASE WHEN DATEDIFF(a.created_date, f.cohort_date) = 30 THEN f.user_id END) AS d30_users,
    ROUND(COUNT(DISTINCT CASE WHEN DATEDIFF(a.created_date, f.cohort_date) = 1  THEN f.user_id END) * 100.0
          / COUNT(DISTINCT f.user_id), 2)                            AS d1_rate,
    ROUND(COUNT(DISTINCT CASE WHEN DATEDIFF(a.created_date, f.cohort_date) = 7  THEN f.user_id END) * 100.0
          / COUNT(DISTINCT f.user_id), 2)                            AS d7_rate,
    ROUND(COUNT(DISTINCT CASE WHEN DATEDIFF(a.created_date, f.cohort_date) = 30 THEN f.user_id END) * 100.0
          / COUNT(DISTINCT f.user_id), 2)                            AS d30_rate
FROM (
    -- 每个用户的首次下单日期
    SELECT user_id, MIN(created_date) AS cohort_date
    FROM dwd.fact_order
    GROUP BY user_id
) f
LEFT JOIN (
    -- 用户的所有活跃日（去重，避免同一用户同一天多单导致重复计数）
    SELECT DISTINCT user_id, created_date
    FROM dwd.fact_order
) a ON f.user_id = a.user_id
WHERE f.cohort_date <= (
        SELECT MAX(created_date) FROM dwd.fact_order
      ) - INTERVAL 30 DAY
GROUP BY f.cohort_date
ORDER BY f.cohort_date;

-- ========== 验收 ==========

SELECT COUNT(*) AS cohort_days FROM ads.user_retention;

-- 整体留存水平（加权平均）
SELECT
    ROUND(SUM(d1_users)  * 100.0 / SUM(cohort_users), 2) AS avg_d1,
    ROUND(SUM(d7_users)  * 100.0 / SUM(cohort_users), 2) AS avg_d7,
    ROUND(SUM(d30_users) * 100.0 / SUM(cohort_users), 2) AS avg_d30
FROM ads.user_retention;

-- 看几个 cohort
SELECT * FROM ads.user_retention ORDER BY cohort_date DESC LIMIT 10;
