# 性能分析与优化记录

> 原则：**先测量，再优化；没有数据的优化都是猜。**

| 项 | 内容 |
|---|---|
| 环境 | MySQL 8.4 · 本机 Docker · 10 万单数据集 |
| 工具 | `EXPLAIN ANALYZE`（MySQL 8.0.18+） |
| 全链路总耗时 | 16–18 秒（16 个任务） |

---

## 一、先找瓶颈：谁最慢

`run_pipeline.py` 自带耗时统计，跑一次就能看到：

```
fact_order_line       6.9s  ##############
fact_order            2.6s  #####
product_day           2.0s  ####
quality_check         1.6s  ###
user_day              1.2s  ##
...
```

`fact_order_line` 占全链路 **40%**，是唯一的优化靶子。其余任务都在 2 秒以内，优化它们收益很低。

> 这条经验普适：**先看总耗时分部，别平均用力**。优化 1 秒的十个小任务，不如优化 6 秒的一个大任务。

---

## 二、拆解 fact_order_line 的 6.9 秒

这个任务由两部分组成：

```
TRUNCATE  →  INSERT ... SELECT（读 30 万行、写 29 万行）
```

### 2.1 SELECT 部分（2.07 秒）

```sql
EXPLAIN ANALYZE
SELECT ... FROM (窗口函数去重) i JOIN dwd.fact_order o ON ...
```

结果逐行看：

| 步骤 | 累计耗时 | 说明 |
|---|---|---|
| Table scan on `ods.order_items` | 570ms | 扫描 30 万行 |
| Sort（`order_no, product_id, etl_time`） | 1015ms | **排序 30 万行，耗时大头** |
| Window aggregate（`ROW_NUMBER`） | 1097ms | 窗口函数计算 |
| Materialize | 1609ms | 把子查询结果物化到临时表 |
| Nested loop join（29 万次索引查找） | 2073ms | 关联订单表取 `created_date` |

**关键发现**：`Sort` 阶段占了近 1 秒。因为 `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)` 需要先按分区键排序。

### 2.2 INSERT 部分（4.1 秒）

SELECT 只要 2.07 秒，任务总耗时 6.2 秒——**差出来的 4.1 秒全在写入**。

`dwd.fact_order_line` 有 3 个二级索引（`idx_order`、`idx_product`、`idx_created_date`），
每插入一行要维护 3 次 B+ 树索引。29.4 万行 × 3 = **88 万次索引插入**。

---

## 三、优化实验：批量导入前先删索引

### 做法

```sql
ALTER TABLE dwd.fact_order_line
  DROP INDEX idx_order, DROP INDEX idx_product, DROP INDEX idx_created_date;

TRUNCATE; INSERT ...;

ALTER TABLE dwd.fact_order_line
  ADD INDEX idx_order (order_no),
  ADD INDEX idx_product (product_id),
  ADD INDEX idx_created_date (created_date);
```

原理：一次建索引（批量排序构建）比逐行维护索引快得多。

### 实测结果

| 方案 | 耗时 | 相对提升 |
|---|---|---|
| A：带索引插入（现状） | **6.20s** | — |
| B：删索引 → 插入 → 重建 | **4.71s** | **−24%** |

### 结论：**不采用**

理由不是“提升不够”，是**风险大于收益**：

1. **失败即裸奔**：如果 INSERT 中途失败，表会停在“没有索引”的状态。
   数据是对的，但下游查询全部退化成全表扫描——**这种故障不报错，只是变慢**，很难第一时间发现。
2. **收益有限**：省 1.5 秒，对一条 18 秒的链路意义不大。
3. **索引重建本身有风险**：大表 `ADD INDEX` 会长时间占用资源，可能阻塞其他操作。

**什么情况下值得用**：单表千万级以上、且是“一次性初始化导入”的离线场景。
这种场景通常用更彻底的方案（分区表 + `EXCHANGE PARTITION`），而不是手工删建索引。

> 面试价值：这个实验证明你知道「索引维护是写入瓶颈」，也知道「优化要看收益/风险比」，
> 而不是见到慢就上手段。

---

## 四、其他观察（未优化，记录备查）

| 观察 | 说明 | 为什么不动 |
|---|---|---|
| `Sort` 占 1 秒 | 给 `ods.order_items(order_no, product_id, etl_time)` 加索引可消除排序 | ODS 层建索引违背“原样保存、快速写入”的定位；且只省 1 秒 |
| `Materialize` 占 0.5 秒 | 子查询结果物化到临时表 | MySQL 对窗口函数的固定行为，改写成本高 |
| 29 万次 JOIN 查找 | 每次 0.0012ms，已走主键索引 | 已经是最优路径 |
| 全量重建 16–18 秒 | 数据量小，全量最简单 | 增量会引入迟到数据、分区覆盖等复杂度，当前不值得 |

---

## 五、可复用的分析方法

```sql
-- 1. 看执行计划的真实耗时（不是估算）
EXPLAIN ANALYZE <你的查询>;

-- 2. 看索引
SHOW INDEX FROM <表>;

-- 3. 看表大小
SELECT table_name,
       ROUND(data_length/1024/1024, 1) AS data_mb,
       ROUND(index_length/1024/1024, 1) AS index_mb
FROM information_schema.tables
WHERE table_schema = 'dwd';
```

**顺序很重要**：先全链路耗时分布 → 锁定最慢任务 → 拆 SELECT/写入 → 分别测量 → 再决定改不改。

---

## 六、这次分析得到的三个结论

1. **瓶颈在写入，不在查询**——SELECT 只占 1/3，索引维护占 2/3
2. **24% 的提升不值得承担“失败裸奔”的风险**——工程判断比优化技巧重要
3. **全量重建 18 秒，暂时不需要增量**——但数据量到千万级时必须重新评估

> 记录未采纳的优化方案，和记录采纳的一样重要。
> 它证明你**评估过**，而不是**没想到**。
