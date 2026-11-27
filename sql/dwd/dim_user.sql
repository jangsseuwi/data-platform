-- DWD：用户维度清洗
--
-- 目标：一行一个用户，属性可直接用于报表展示和分组
--
-- 处理规则：
--   1. 按 user_id 去重，保留 etl_time 最新的一条（防止上游重复推送）
--   2. register_at -> register_date（冗余日期列，方便按注册日算新客）
--   3. user_name 为空时兜底为 'unknown'
--      维度表可以兜底，因为名字缺失不影响基于 user_id 的统计；
--      事实表不行——金额错了必须丢弃，不能瞎填。
--
-- 可重复执行：先 TRUNCATE 再 INSERT，跑多少遍结果都一样

TRUNCATE TABLE dwd.dim_user;

INSERT INTO dwd.dim_user
    (user_id, user_name, phone, city, register_date)
SELECT
    user_id,
    -- 三层兜底：TRIM 去掉首尾空格 -> NULLIF 把空串变成 NULL -> IFNULL 填默认值
    -- 只用 IFNULL 处理不了空串：IFNULL('', 'unknown') 返回的是 '' 而不是 'unknown'
    IFNULL(NULLIF(TRIM(user_name), ''), 'unknown') AS user_name,
    phone,
    IFNULL(NULLIF(TRIM(city), ''), 'unknown')      AS city,
    DATE(register_at)                              AS register_date
FROM (
    SELECT
        u.*,
        ROW_NUMBER() OVER (
            PARTITION BY user_id
            ORDER BY etl_time DESC
        ) AS rn
    FROM ods.users u
) t
WHERE t.rn = 1;

-- ========== 验收 ==========

-- 1. 用户总数（去掉重复后）
SELECT COUNT(*) AS user_cnt FROM dwd.dim_user;

-- 2. 有没有兜底过的脏名字（造数数据应该是 0）
SELECT COUNT(*) AS unknown_name_cnt
FROM dwd.dim_user
WHERE user_name = 'unknown';

-- 3. 注册日期有没有 NULL（有说明上游数据有问题）
SELECT COUNT(*) AS null_register_date
FROM dwd.dim_user
WHERE register_date IS NULL;
