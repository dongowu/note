# PostgreSQL 性能调优与监控

## 目录
- [性能调优策略](#性能调优策略)
- [查询优化](#查询优化)
- [索引优化](#索引优化)
- [配置参数调优](#配置参数调优)
- [连接池优化](#连接池优化)
- [监控与诊断](#监控与诊断)
- [Go语言集成](#go语言集成)
- [高频面试题](#高频面试题)

## 性能调优策略

### 1. 整体调优思路

#### 性能瓶颈识别
```sql
-- 查看慢查询
SELECT query, calls, total_time, mean_time, rows
FROM pg_stat_statements
ORDER BY total_time DESC
LIMIT 10;

-- 查看表统计信息
SELECT schemaname, tablename, n_tup_ins, n_tup_upd, n_tup_del, n_live_tup, n_dead_tup
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC;

-- 查看索引使用情况
SELECT schemaname, tablename, indexname, idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;
```

#### 系统资源监控
```sql
-- 查看连接数
SELECT count(*) as total_connections,
       count(*) FILTER (WHERE state = 'active') as active_connections,
       count(*) FILTER (WHERE state = 'idle') as idle_connections
FROM pg_stat_activity;

-- 查看锁等待
SELECT blocked_locks.pid AS blocked_pid,
       blocked_activity.usename AS blocked_user,
       blocking_locks.pid AS blocking_pid,
       blocking_activity.usename AS blocking_user,
       blocked_activity.query AS blocked_statement,
       blocking_activity.query AS current_statement_in_blocking_process
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks ON blocking_locks.locktype = blocked_locks.locktype
AND blocking_locks.DATABASE IS NOT DISTINCT FROM blocked_locks.DATABASE
AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.GRANTED;
```

### 2. 硬件资源优化

#### CPU优化
- **多核利用**：PostgreSQL支持并行查询，合理配置`max_parallel_workers`
- **CPU亲和性**：绑定PostgreSQL进程到特定CPU核心
- **NUMA优化**：在NUMA架构下优化内存访问

#### 内存优化
- **共享缓冲区**：`shared_buffers`设置为系统内存的25%-40%
- **工作内存**：`work_mem`根据并发查询数量调整
- **维护内存**：`maintenance_work_mem`用于VACUUM、CREATE INDEX等操作

#### 存储优化
- **SSD vs HDD**：SSD显著提升随机I/O性能
- **RAID配置**：RAID10平衡性能和可靠性
- **文件系统**：ext4、XFS等文件系统优化

## 查询优化

### 1. 执行计划分析

#### EXPLAIN详解
```sql
-- 基本执行计划
EXPLAIN SELECT * FROM users WHERE age > 25;

-- 详细执行计划
EXPLAIN (ANALYZE, BUFFERS, VERBOSE) 
SELECT u.name, p.title 
FROM users u 
JOIN posts p ON u.id = p.user_id 
WHERE u.age > 25;

-- 执行计划输出解读
/*
Seq Scan on users u  (cost=0.00..1693.00 rows=5000 width=64) (actual time=0.123..12.456 rows=4832 loops=1)
  Filter: (age > 25)
  Rows Removed by Filter: 168
  Buffers: shared hit=693
*/
```

#### 常见执行节点
- **Seq Scan**：全表扫描，成本高
- **Index Scan**：索引扫描，高效
- **Index Only Scan**：仅索引扫描，最高效
- **Bitmap Heap Scan**：位图堆扫描，适合范围查询
- **Nested Loop**：嵌套循环连接
- **Hash Join**：哈希连接，适合大表连接
- **Merge Join**：归并连接，适合有序数据

### 2. SQL优化技巧

#### 查询重写
```sql
-- 避免SELECT *
-- 不好的写法
SELECT * FROM users WHERE age > 25;

-- 好的写法
SELECT id, name, email FROM users WHERE age > 25;

-- 使用EXISTS替代IN
-- 不好的写法
SELECT * FROM users WHERE id IN (SELECT user_id FROM posts WHERE status = 'published');

-- 好的写法
SELECT * FROM users u WHERE EXISTS (SELECT 1 FROM posts p WHERE p.user_id = u.id AND p.status = 'published');

-- 避免函数在WHERE子句中
-- 不好的写法
SELECT * FROM orders WHERE EXTRACT(YEAR FROM created_at) = 2023;

-- 好的写法
SELECT * FROM orders WHERE created_at >= '2023-01-01' AND created_at < '2024-01-01';
```

#### 分页优化
```sql
-- 传统分页（性能差）
SELECT * FROM posts ORDER BY created_at DESC LIMIT 20 OFFSET 10000;

-- 游标分页（性能好）
SELECT * FROM posts WHERE created_at < '2023-01-01 12:00:00' ORDER BY created_at DESC LIMIT 20;

-- 使用窗口函数优化
WITH ranked_posts AS (
    SELECT *, ROW_NUMBER() OVER (ORDER BY created_at DESC) as rn
    FROM posts
    WHERE status = 'published'
)
SELECT * FROM ranked_posts WHERE rn BETWEEN 101 AND 120;
```

## 索引优化

### 1. 索引类型选择

#### B-tree索引（默认）
```sql
-- 单列索引
CREATE INDEX idx_users_age ON users(age);

-- 复合索引
CREATE INDEX idx_users_age_status ON users(age, status);

-- 部分索引
CREATE INDEX idx_users_active ON users(email) WHERE status = 'active';

-- 表达式索引
CREATE INDEX idx_users_lower_email ON users(lower(email));
```

#### 特殊索引类型
```sql
-- GIN索引（全文搜索、数组）
CREATE INDEX idx_posts_content_gin ON posts USING gin(to_tsvector('english', content));
CREATE INDEX idx_tags_gin ON posts USING gin(tags);

-- GiST索引（几何数据、范围类型）
CREATE INDEX idx_locations_gist ON locations USING gist(coordinates);

-- Hash索引（等值查询）
CREATE INDEX idx_users_hash ON users USING hash(email);

-- BRIN索引（大表、有序数据）
CREATE INDEX idx_logs_brin ON logs USING brin(created_at);
```

### 2. 索引维护

#### 索引监控
```sql
-- 查看索引大小
SELECT schemaname, tablename, indexname, 
       pg_size_pretty(pg_relation_size(indexrelid)) as index_size
FROM pg_stat_user_indexes
ORDER BY pg_relation_size(indexrelid) DESC;

-- 查看未使用的索引
SELECT schemaname, tablename, indexname, idx_scan
FROM pg_stat_user_indexes
WHERE idx_scan = 0
ORDER BY pg_relation_size(indexrelid) DESC;

-- 查看索引膨胀
SELECT schemaname, tablename, indexname,
       pg_size_pretty(pg_relation_size(indexrelid)) as size,
       CASE WHEN pg_relation_size(indexrelid) > 0 
            THEN round(100.0 * pg_stat_get_live_tuples(indexrelid) / 
                      (pg_relation_size(indexrelid) / 8192.0))
            ELSE 0 END as bloat_ratio
FROM pg_stat_user_indexes;
```

#### 索引重建
```sql
-- 重建索引
REINDEX INDEX idx_users_email;
REINDEX TABLE users;
REINDEX DATABASE mydb;

-- 并发重建索引
CREATE INDEX CONCURRENTLY idx_users_email_new ON users(email);
DROP INDEX idx_users_email;
ALTER INDEX idx_users_email_new RENAME TO idx_users_email;
```

## 配置参数调优

### 1. 内存相关参数

```ini
# postgresql.conf

# 共享缓冲区（系统内存的25%-40%）
shared_buffers = 2GB

# 工作内存（每个查询操作可用内存）
work_mem = 64MB

# 维护工作内存
maintenance_work_mem = 512MB

# 有效缓存大小（系统总内存的50%-75%）
effective_cache_size = 6GB

# 自动vacuum工作内存
autovacuum_work_mem = 512MB
```

### 2. 检查点和WAL参数

```ini
# WAL缓冲区
wal_buffers = 64MB

# 检查点完成目标时间比例
checkpoint_completion_target = 0.9

# 最大WAL大小
max_wal_size = 4GB

# 最小WAL大小
min_wal_size = 1GB

# WAL写入模式
wal_sync_method = fdatasync

# 同步提交
synchronous_commit = on
```

### 3. 连接和并发参数

```ini
# 最大连接数
max_connections = 200

# 最大并行工作进程
max_parallel_workers = 8

# 每个查询最大并行工作进程
max_parallel_workers_per_gather = 4

# 并行维护工作进程
max_parallel_maintenance_workers = 4

# 后台写进程延迟
bgwriter_delay = 200ms

# 后台写进程LRU最大页数
bgwriter_lru_maxpages = 100
```

### 4. 自动vacuum参数

```ini
# 启用自动vacuum
autovacuum = on

# 自动vacuum最大工作进程
autovacuum_max_workers = 6

# vacuum阈值
autovacuum_vacuum_threshold = 50

# vacuum比例因子
autovacuum_vacuum_scale_factor = 0.1

# analyze阈值
autovacuum_analyze_threshold = 50

# analyze比例因子
autovacuum_analyze_scale_factor = 0.05
```

## 连接池优化

### 1. 连接池配置

#### PgBouncer配置
```ini
# pgbouncer.ini
[databases]
mydb = host=localhost port=5432 dbname=mydb

[pgbouncer]
# 监听地址和端口
listen_addr = 0.0.0.0
listen_port = 6432

# 连接池模式
pool_mode = transaction

# 最大客户端连接数
max_client_conn = 1000

# 默认连接池大小
default_pool_size = 25

# 最小连接池大小
min_pool_size = 5

# 保留连接数
reserve_pool_size = 5

# 服务器连接超时
server_connect_timeout = 15

# 服务器登录重试
server_login_retry = 15
```

### 2. Go语言连接池优化

```go
package main

import (
    "database/sql"
    "time"
    _ "github.com/lib/pq"
)

func setupDB() *sql.DB {
    db, err := sql.Open("postgres", 
        "host=localhost port=5432 user=myuser dbname=mydb sslmode=disable")
    if err != nil {
        panic(err)
    }
    
    // 设置连接池参数
    db.SetMaxOpenConns(100)        // 最大打开连接数
    db.SetMaxIdleConns(10)         // 最大空闲连接数
    db.SetConnMaxLifetime(time.Hour) // 连接最大生存时间
    db.SetConnMaxIdleTime(time.Minute * 30) // 连接最大空闲时间
    
    return db
}

// 连接池监控
func monitorDB(db *sql.DB) {
    stats := db.Stats()
    fmt.Printf("MaxOpenConnections: %d\n", stats.MaxOpenConnections)
    fmt.Printf("OpenConnections: %d\n", stats.OpenConnections)
    fmt.Printf("InUse: %d\n", stats.InUse)
    fmt.Printf("Idle: %d\n", stats.Idle)
    fmt.Printf("WaitCount: %d\n", stats.WaitCount)
    fmt.Printf("WaitDuration: %v\n", stats.WaitDuration)
}
```

## 监控与诊断

### 1. 系统监控

#### 关键指标监控
```sql
-- 数据库大小监控
SELECT pg_database.datname,
       pg_size_pretty(pg_database_size(pg_database.datname)) AS size
FROM pg_database
ORDER BY pg_database_size(pg_database.datname) DESC;

-- 表空间使用情况
SELECT spcname, pg_size_pretty(pg_tablespace_size(spcname)) AS size
FROM pg_tablespace;

-- 缓存命中率
SELECT datname,
       round(blks_hit::numeric / (blks_hit + blks_read) * 100, 2) AS cache_hit_ratio
FROM pg_stat_database
WHERE blks_read > 0;

-- 事务统计
SELECT datname, xact_commit, xact_rollback,
       round(xact_commit::numeric / (xact_commit + xact_rollback) * 100, 2) AS commit_ratio
FROM pg_stat_database;
```

#### 性能视图
```sql
-- 创建性能监控视图
CREATE VIEW performance_summary AS
SELECT 
    'Database Size' as metric,
    pg_size_pretty(sum(pg_database_size(datname))) as value
FROM pg_database
UNION ALL
SELECT 
    'Active Connections',
    count(*)::text
FROM pg_stat_activity 
WHERE state = 'active'
UNION ALL
SELECT 
    'Cache Hit Ratio',
    round(avg(blks_hit::numeric / (blks_hit + blks_read) * 100), 2)::text || '%'
FROM pg_stat_database 
WHERE blks_read > 0;
```

### 2. 日志分析

#### 日志配置
```ini
# postgresql.conf

# 启用日志记录
logging_collector = on

# 日志目录
log_directory = 'pg_log'

# 日志文件名模式
log_filename = 'postgresql-%Y-%m-%d_%H%M%S.log'

# 日志轮转
log_rotation_age = 1d
log_rotation_size = 100MB

# 记录慢查询
log_min_duration_statement = 1000  # 记录执行时间超过1秒的查询

# 记录锁等待
log_lock_waits = on

# 记录检查点
log_checkpoints = on

# 记录连接
log_connections = on
log_disconnections = on
```

#### 日志分析工具
```bash
# 使用pgBadger分析日志
pgbadger /var/log/postgresql/postgresql-*.log -o report.html

# 使用pg_stat_statements
CREATE EXTENSION pg_stat_statements;

# 查看统计信息
SELECT query, calls, total_time, mean_time, stddev_time, rows
FROM pg_stat_statements
ORDER BY total_time DESC
LIMIT 10;
```

## Go语言集成

### 1. 高性能数据库操作

```go
package main

import (
    "context"
    "database/sql"
    "fmt"
    "time"
    
    "github.com/jackc/pgx/v4/pgxpool"
    _ "github.com/lib/pq"
)

// 使用pgx连接池
type DBManager struct {
    pool *pgxpool.Pool
}

func NewDBManager(dsn string) (*DBManager, error) {
    config, err := pgxpool.ParseConfig(dsn)
    if err != nil {
        return nil, err
    }
    
    // 连接池配置
    config.MaxConns = 30
    config.MinConns = 5
    config.MaxConnLifetime = time.Hour
    config.MaxConnIdleTime = time.Minute * 30
    
    pool, err := pgxpool.ConnectConfig(context.Background(), config)
    if err != nil {
        return nil, err
    }
    
    return &DBManager{pool: pool}, nil
}

// 批量插入优化
func (db *DBManager) BatchInsert(users []User) error {
    ctx := context.Background()
    
    // 使用COPY进行批量插入
    conn, err := db.pool.Acquire(ctx)
    if err != nil {
        return err
    }
    defer conn.Release()
    
    _, err = conn.CopyFrom(
        ctx,
        pgx.Identifier{"users"},
        []string{"name", "email", "age"},
        pgx.CopyFromSlice(len(users), func(i int) ([]interface{}, error) {
            return []interface{}{users[i].Name, users[i].Email, users[i].Age}, nil
        }),
    )
    
    return err
}

// 预处理语句优化
func (db *DBManager) PreparedQuery() error {
    ctx := context.Background()
    
    // 准备语句
    stmt, err := db.pool.Prepare(ctx, "getUserByAge", 
        "SELECT id, name, email FROM users WHERE age > $1")
    if err != nil {
        return err
    }
    
    // 执行预处理语句
    rows, err := db.pool.Query(ctx, "getUserByAge", 25)
    if err != nil {
        return err
    }
    defer rows.Close()
    
    for rows.Next() {
        var user User
        err := rows.Scan(&user.ID, &user.Name, &user.Email)
        if err != nil {
            return err
        }
        fmt.Printf("User: %+v\n", user)
    }
    
    return rows.Err()
}
```

### 2. 事务管理优化

```go
// 事务管理器
type TxManager struct {
    db *sql.DB
}

func (tm *TxManager) WithTransaction(ctx context.Context, fn func(*sql.Tx) error) error {
    tx, err := tm.db.BeginTx(ctx, &sql.TxOptions{
        Isolation: sql.LevelReadCommitted,
        ReadOnly:  false,
    })
    if err != nil {
        return err
    }
    
    defer func() {
        if p := recover(); p != nil {
            tx.Rollback()
            panic(p)
        } else if err != nil {
            tx.Rollback()
        } else {
            err = tx.Commit()
        }
    }()
    
    err = fn(tx)
    return err
}

// 使用示例
func (tm *TxManager) TransferMoney(fromID, toID int, amount float64) error {
    return tm.WithTransaction(context.Background(), func(tx *sql.Tx) error {
        // 检查余额
        var balance float64
        err := tx.QueryRow("SELECT balance FROM accounts WHERE id = $1 FOR UPDATE", fromID).Scan(&balance)
        if err != nil {
            return err
        }
        
        if balance < amount {
            return fmt.Errorf("insufficient balance")
        }
        
        // 扣款
        _, err = tx.Exec("UPDATE accounts SET balance = balance - $1 WHERE id = $2", amount, fromID)
        if err != nil {
            return err
        }
        
        // 入账
        _, err = tx.Exec("UPDATE accounts SET balance = balance + $1 WHERE id = $2", amount, toID)
        return err
    })
}
```

### 3. 监控集成

```go
package main

import (
    "context"
    "database/sql"
    "time"
    
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
)

// Prometheus指标
var (
    dbConnections = promauto.NewGaugeVec(
        prometheus.GaugeOpts{
            Name: "postgresql_connections",
            Help: "The current number of database connections",
        },
        []string{"state"},
    )
    
    queryDuration = promauto.NewHistogramVec(
        prometheus.HistogramOpts{
            Name: "postgresql_query_duration_seconds",
            Help: "The duration of database queries",
            Buckets: prometheus.DefBuckets,
        },
        []string{"query_type"},
    )
    
    queryErrors = promauto.NewCounterVec(
        prometheus.CounterOpts{
            Name: "postgresql_query_errors_total",
            Help: "The total number of database query errors",
        },
        []string{"error_type"},
    )
)

// 监控装饰器
func MonitoredQuery(db *sql.DB, query string, args ...interface{}) (*sql.Rows, error) {
    start := time.Now()
    
    rows, err := db.Query(query, args...)
    
    duration := time.Since(start)
    queryDuration.WithLabelValues("select").Observe(duration.Seconds())
    
    if err != nil {
        queryErrors.WithLabelValues("query_error").Inc()
    }
    
    return rows, err
}

// 连接池监控
func MonitorConnectionPool(db *sql.DB) {
    go func() {
        ticker := time.NewTicker(30 * time.Second)
        defer ticker.Stop()
        
        for range ticker.C {
            stats := db.Stats()
            dbConnections.WithLabelValues("open").Set(float64(stats.OpenConnections))
            dbConnections.WithLabelValues("in_use").Set(float64(stats.InUse))
            dbConnections.WithLabelValues("idle").Set(float64(stats.Idle))
        }
    }()
}
```

## 高频面试题

### 1. 架构设计类

**Q: 如何设计一个高并发的PostgreSQL架构？**

A: 高并发PostgreSQL架构设计要点：

1. **读写分离**：
   - 主库处理写操作
   - 从库处理读操作
   - 使用流复制实现数据同步

2. **连接池优化**：
   - 使用PgBouncer进行连接池管理
   - 合理配置pool_mode（session/transaction/statement）
   - 设置合适的连接数限制

3. **分片策略**：
   - 水平分片：按用户ID、时间等维度分片
   - 垂直分片：按业务模块分离表
   - 使用Citus等分布式扩展

4. **缓存层**：
   - Redis缓存热点数据
   - 应用层缓存查询结果
   - CDN缓存静态资源

**Q: PostgreSQL的MVCC机制如何实现？**

A: MVCC（多版本并发控制）实现机制：

1. **版本管理**：
   - 每个事务有唯一的事务ID（XID）
   - 每行数据包含xmin（创建事务ID）和xmax（删除事务ID）
   - 通过比较事务ID判断数据可见性

2. **可见性规则**：
   - 数据行的xmin <= 当前事务ID且已提交
   - 数据行的xmax > 当前事务ID或未提交
   - 满足以上条件的数据对当前事务可见

3. **垃圾回收**：
   - VACUUM进程清理过期的行版本
   - 自动vacuum根据配置定期运行
   - 手动vacuum可立即清理

### 2. 性能优化类

**Q: 如何优化PostgreSQL的查询性能？**

A: 查询性能优化策略：

1. **索引优化**：
   - 为WHERE、ORDER BY、JOIN字段创建索引
   - 使用复合索引优化多字段查询
   - 选择合适的索引类型（B-tree、GIN、GiST等）

2. **查询重写**：
   - 避免SELECT *，只查询需要的字段
   - 使用EXISTS替代IN子查询
   - 合理使用LIMIT限制结果集

3. **统计信息更新**：
   - 定期运行ANALYZE更新表统计信息
   - 确保查询规划器有准确的数据分布信息

4. **参数调优**：
   - 调整work_mem提高排序和哈希操作性能
   - 优化shared_buffers提高缓存命中率
   - 配置effective_cache_size帮助规划器做出更好的决策

**Q: 如何处理PostgreSQL的锁竞争问题？**

A: 锁竞争处理方案：

1. **锁类型理解**：
   - 表级锁：ACCESS SHARE、ROW SHARE、ROW EXCLUSIVE等
   - 行级锁：FOR UPDATE、FOR SHARE
   - 咨询锁：应用层自定义锁

2. **减少锁竞争**：
   - 缩短事务持续时间
   - 避免长时间持有锁
   - 使用合适的隔离级别
   - 优化查询减少锁等待

3. **锁监控**：
   - 使用pg_locks视图监控锁状态
   - 识别锁等待和死锁情况
   - 设置lock_timeout避免无限等待

### 3. 运维管理类

**Q: 如何进行PostgreSQL的备份和恢复？**

A: 备份恢复策略：

1. **逻辑备份**：
   - pg_dump：单个数据库备份
   - pg_dumpall：整个集群备份
   - 适合小到中等规模数据库

2. **物理备份**：
   - pg_basebackup：基础备份
   - 连续归档：WAL日志备份
   - 支持时间点恢复（PITR）

3. **备份策略**：
   - 全量备份 + 增量备份
   - 定期测试恢复流程
   - 异地备份保证数据安全

**Q: 如何监控PostgreSQL的性能指标？**

A: 性能监控体系：

1. **系统级监控**：
   - CPU、内存、磁盘I/O使用率
   - 网络流量和连接数
   - 操作系统级别的资源监控

2. **数据库级监控**：
   - 查询性能：慢查询、执行计划
   - 连接状态：活跃连接、空闲连接
   - 缓存命中率：shared_buffers命中率
   - 锁等待：锁竞争和死锁情况

3. **监控工具**：
   - pg_stat_*系统视图
   - pgBadger日志分析
   - Prometheus + Grafana监控
   - 自定义监控脚本

### 4. Go集成类

**Q: 在Go中如何优化PostgreSQL的连接池？**

A: Go连接池优化策略：

1. **连接池配置**：
```go
db.SetMaxOpenConns(100)        // 最大连接数
db.SetMaxIdleConns(10)         // 最大空闲连接数
db.SetConnMaxLifetime(time.Hour) // 连接最大生存时间
```

2. **连接池监控**：
```go
stats := db.Stats()
fmt.Printf("OpenConnections: %d\n", stats.OpenConnections)
fmt.Printf("InUse: %d\n", stats.InUse)
```

3. **最佳实践**：
   - 根据并发量调整连接数
   - 监控连接池使用情况
   - 及时释放连接资源
   - 使用context控制超时

**Q: 如何在Go中实现高效的批量操作？**

A: 批量操作优化方案：

1. **COPY协议**：
```go
_, err = conn.CopyFrom(
    ctx,
    pgx.Identifier{"users"},
    []string{"name", "email"},
    pgx.CopyFromSlice(len(users), func(i int) ([]interface{}, error) {
        return []interface{}{users[i].Name, users[i].Email}, nil
    }),
)
```

2. **批量INSERT**：
```go
values := make([]interface{}, 0, len(users)*2)
for _, user := range users {
    values = append(values, user.Name, user.Email)
}

query := "INSERT INTO users (name, email) VALUES " + 
         strings.Repeat("(?, ?),", len(users))
query = query[:len(query)-1] // 移除最后的逗号
```

3. **事务批处理**：
```go
tx, err := db.Begin()
for _, user := range users {
    _, err = tx.Exec("INSERT INTO users (name, email) VALUES ($1, $2)", 
                     user.Name, user.Email)
}
tx.Commit()
```

## 总结

PostgreSQL性能调优是一个系统性工程，需要从硬件、配置、查询、索引、监控等多个维度进行优化。在Go语言环境下，合理使用连接池、预处理语句、批量操作等技术可以显著提升应用性能。持续的监控和调优是保证系统稳定运行的关键。