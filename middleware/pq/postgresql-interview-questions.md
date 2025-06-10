# PostgreSQL 高频面试题及解答

## 目录
- [基础概念题](#基础概念题)
- [架构原理题](#架构原理题)
- [性能优化题](#性能优化题)
- [事务与并发题](#事务与并发题)
- [高可用与备份题](#高可用与备份题)
- [Go语言集成题](#go语言集成题)
- [实战场景题](#实战场景题)

## 基础概念题

### 1. PostgreSQL与MySQL的主要区别是什么？

**答案：**

| 特性 | PostgreSQL | MySQL |
|------|------------|-------|
| **数据类型** | 支持丰富的数据类型（JSON、数组、自定义类型） | 基础数据类型为主 |
| **ACID支持** | 完全支持ACID | InnoDB引擎支持ACID |
| **并发控制** | MVCC多版本并发控制 | 锁机制+MVCC |
| **扩展性** | 高度可扩展，支持自定义函数、操作符 | 扩展性相对有限 |
| **全文搜索** | 内置全文搜索 | 需要额外配置 |
| **复制** | 流复制、逻辑复制 | 主从复制、组复制 |
| **性能** | 复杂查询性能优秀 | 简单查询性能优秀 |

### 2. 什么是MVCC？它是如何工作的？

**答案：**

MVCC（Multi-Version Concurrency Control）多版本并发控制是PostgreSQL的核心特性：

**工作原理：**
1. **版本管理**：每个事务看到数据的一个快照
2. **时间戳**：使用事务ID（XID）标识数据版本
3. **可见性规则**：根据事务开始时间决定数据可见性
4. **无锁读取**：读操作不阻塞写操作

**优势：**
- 读写不互相阻塞
- 高并发性能
- 事务隔离性好

**代码示例：**
```sql
-- 事务A
BEGIN;
SELECT * FROM users WHERE id = 1; -- 看到版本1

-- 事务B（并发执行）
BEGIN;
UPDATE users SET name = 'New Name' WHERE id = 1; -- 创建版本2
COMMIT;

-- 事务A继续
SELECT * FROM users WHERE id = 1; -- 仍然看到版本1
COMMIT;
```

### 3. PostgreSQL的WAL是什么？有什么作用？

**答案：**

WAL（Write-Ahead Logging）预写日志是PostgreSQL的核心组件：

**作用：**
1. **数据持久性**：确保已提交事务不丢失
2. **崩溃恢复**：系统崩溃后可以恢复数据
3. **流复制**：支持主从复制
4. **时间点恢复**：支持PITR恢复

**工作流程：**
```
1. 事务修改数据
2. 先写WAL日志到磁盘
3. 再修改数据页
4. 定期checkpoint刷新脏页
```

**配置参数：**
```sql
-- 查看WAL配置
SHOW wal_level;           -- 日志级别
SHOW max_wal_size;        -- 最大WAL大小
SHOW checkpoint_timeout;   -- checkpoint超时时间
```

## 架构原理题

### 4. 描述PostgreSQL的进程架构

**答案：**

PostgreSQL采用多进程架构：

**主要进程：**

1. **Postmaster（主进程）**
   - 监听客户端连接
   - 管理子进程
   - 处理信号和启动/关闭

2. **Backend进程**
   - 每个客户端连接对应一个backend进程
   - 处理SQL查询
   - 管理事务

3. **辅助进程**
   ```
   - WAL Writer: 写WAL日志
   - Background Writer: 写脏页
   - Checkpointer: 执行checkpoint
   - Autovacuum: 自动清理
   - Stats Collector: 收集统计信息
   ```

**进程通信：**
- 共享内存
- 信号量
- 管道

### 5. PostgreSQL的内存架构是怎样的？

**答案：**

**共享内存区域：**

1. **Shared Buffer Pool**
   ```sql
   -- 配置共享缓冲区
   shared_buffers = 256MB  -- 通常设置为内存的25%
   ```

2. **WAL Buffer**
   ```sql
   wal_buffers = 16MB      -- WAL缓冲区
   ```

3. **Lock Table**
   - 存储锁信息
   - 管理并发控制

**进程私有内存：**

1. **Work Memory**
   ```sql
   work_mem = 4MB          -- 排序、哈希操作内存
   ```

2. **Maintenance Work Memory**
   ```sql
   maintenance_work_mem = 64MB  -- 维护操作内存
   ```

**内存优化建议：**
```sql
-- 查看内存使用情况
SELECT 
    setting,
    unit,
    context
FROM pg_settings 
WHERE name IN (
    'shared_buffers',
    'work_mem',
    'maintenance_work_mem'
);
```

## 性能优化题

### 6. 如何优化PostgreSQL的查询性能？

**答案：**

**1. 索引优化**
```sql
-- 创建合适的索引
CREATE INDEX idx_user_email ON users(email);
CREATE INDEX idx_order_date ON orders(created_at);

-- 复合索引
CREATE INDEX idx_user_status_date ON users(status, created_at);

-- 部分索引
CREATE INDEX idx_active_users ON users(email) WHERE status = 'active';
```

**2. 查询重写**
```sql
-- 避免SELECT *
SELECT id, name, email FROM users WHERE status = 'active';

-- 使用LIMIT
SELECT * FROM orders ORDER BY created_at DESC LIMIT 10;

-- 优化JOIN
SELECT u.name, o.total
FROM users u
INNER JOIN orders o ON u.id = o.user_id
WHERE u.status = 'active';
```

**3. 统计信息更新**
```sql
-- 更新表统计信息
ANALYZE users;

-- 自动更新配置
SET autovacuum = on;
SET track_counts = on;
```

**4. 配置优化**
```sql
-- 查询规划器配置
SET random_page_cost = 1.1;     -- SSD存储
SET effective_cache_size = '1GB'; -- 系统缓存大小
```

### 7. 如何分析慢查询？

**答案：**

**1. 启用慢查询日志**
```sql
-- 配置慢查询记录
SET log_min_duration_statement = 1000;  -- 记录超过1秒的查询
SET log_statement = 'all';               -- 记录所有语句
SET log_duration = on;                   -- 记录执行时间
```

**2. 使用EXPLAIN分析**
```sql
-- 查看执行计划
EXPLAIN (ANALYZE, BUFFERS) 
SELECT * FROM users WHERE email = 'test@example.com';

-- 详细分析
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON)
SELECT u.name, COUNT(o.id) as order_count
FROM users u
LEFT JOIN orders o ON u.id = o.user_id
GROUP BY u.id, u.name;
```

**3. 性能监控查询**
```sql
-- 查看当前活跃查询
SELECT 
    pid,
    now() - pg_stat_activity.query_start AS duration,
    query,
    state
FROM pg_stat_activity
WHERE (now() - pg_stat_activity.query_start) > interval '5 minutes';

-- 查看表统计信息
SELECT 
    schemaname,
    tablename,
    seq_scan,
    seq_tup_read,
    idx_scan,
    idx_tup_fetch
FROM pg_stat_user_tables
ORDER BY seq_tup_read DESC;
```

## 事务与并发题

### 8. PostgreSQL支持哪些事务隔离级别？

**答案：**

PostgreSQL支持4种标准隔离级别：

**1. READ UNCOMMITTED（读未提交）**
```sql
BEGIN TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;
-- 可能读到脏数据
```

**2. READ COMMITTED（读已提交）- 默认级别**
```sql
BEGIN TRANSACTION ISOLATION LEVEL READ COMMITTED;
-- 只能读到已提交的数据
```

**3. REPEATABLE READ（可重复读）**
```sql
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ;
-- 事务期间读取的数据保持一致
```

**4. SERIALIZABLE（串行化）**
```sql
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;
-- 最高隔离级别，避免所有异常
```

**隔离级别对比：**

| 隔离级别 | 脏读 | 不可重复读 | 幻读 | 串行化异常 |
|----------|------|------------|------|------------|
| READ UNCOMMITTED | 可能 | 可能 | 可能 | 可能 |
| READ COMMITTED | 不可能 | 可能 | 可能 | 可能 |
| REPEATABLE READ | 不可能 | 不可能 | 不可能* | 可能 |
| SERIALIZABLE | 不可能 | 不可能 | 不可能 | 不可能 |

*PostgreSQL的REPEATABLE READ实际上避免了幻读

### 9. 如何处理死锁问题？

**答案：**

**死锁检测与处理：**

1. **死锁检测配置**
```sql
-- 死锁检测超时时间
SET deadlock_timeout = '1s';

-- 查看死锁检测设置
SHOW deadlock_timeout;
```

2. **死锁监控**
```sql
-- 查看锁等待情况
SELECT 
    blocked_locks.pid AS blocked_pid,
    blocked_activity.usename AS blocked_user,
    blocking_locks.pid AS blocking_pid,
    blocking_activity.usename AS blocking_user,
    blocked_activity.query AS blocked_statement,
    blocking_activity.query AS current_statement_in_blocking_process
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity 
    ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks 
    ON blocking_locks.locktype = blocked_locks.locktype
JOIN pg_catalog.pg_stat_activity blocking_activity 
    ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
```

3. **避免死锁的最佳实践**
```sql
-- 1. 按固定顺序访问资源
BEGIN;
SELECT * FROM table_a WHERE id = 1 FOR UPDATE;
SELECT * FROM table_b WHERE id = 1 FOR UPDATE;
COMMIT;

-- 2. 缩短事务时间
BEGIN;
-- 尽快完成操作
UPDATE users SET status = 'active' WHERE id = 1;
COMMIT;

-- 3. 使用适当的锁级别
SELECT * FROM users WHERE id = 1 FOR SHARE;  -- 共享锁
```

## 高可用与备份题

### 10. PostgreSQL的复制方式有哪些？

**答案：**

**1. 流复制（Streaming Replication）**

主服务器配置：
```sql
-- postgresql.conf
wal_level = replica
max_wal_senders = 3
wal_keep_segments = 64

-- pg_hba.conf
host replication replicator 192.168.1.0/24 md5
```

从服务器配置：
```sql
-- recovery.conf (PostgreSQL 12之前)
standby_mode = 'on'
primary_conninfo = 'host=192.168.1.100 port=5432 user=replicator'

-- postgresql.conf (PostgreSQL 12+)
primary_conninfo = 'host=192.168.1.100 port=5432 user=replicator'
```

**2. 逻辑复制（Logical Replication）**
```sql
-- 发布端
CREATE PUBLICATION my_publication FOR TABLE users, orders;

-- 订阅端
CREATE SUBSCRIPTION my_subscription 
CONNECTION 'host=192.168.1.100 dbname=mydb user=replicator' 
PUBLICATION my_publication;
```

**3. 复制方式对比**

| 特性 | 流复制 | 逻辑复制 |
|------|--------|----------|
| **数据同步** | 二进制级别 | 逻辑级别 |
| **版本要求** | 相同大版本 | 可跨版本 |
| **选择性复制** | 整个数据库 | 可选择表 |
| **冲突处理** | 无冲突 | 需要处理冲突 |
| **性能** | 高 | 相对较低 |

### 11. 如何进行PostgreSQL的备份和恢复？

**答案：**

**1. 逻辑备份（pg_dump）**
```bash
# 备份单个数据库
pg_dump -h localhost -U postgres -d mydb > mydb_backup.sql

# 备份所有数据库
pg_dumpall -h localhost -U postgres > all_databases.sql

# 自定义格式备份（推荐）
pg_dump -h localhost -U postgres -d mydb -Fc > mydb_backup.dump

# 并行备份（提高性能）
pg_dump -h localhost -U postgres -d mydb -Fd -j 4 -f mydb_backup_dir
```

**2. 物理备份（pg_basebackup）**
```bash
# 基础备份
pg_basebackup -h localhost -U postgres -D /backup/base -Ft -z -P

# 在线备份
pg_basebackup -h localhost -U postgres -D /backup/base -X stream -P
```

**3. 恢复操作**
```bash
# 从逻辑备份恢复
psql -h localhost -U postgres -d mydb < mydb_backup.sql

# 从自定义格式恢复
pg_restore -h localhost -U postgres -d mydb mydb_backup.dump

# 并行恢复
pg_restore -h localhost -U postgres -d mydb -j 4 mydb_backup.dump
```

**4. 时间点恢复（PITR）**
```sql
-- 配置连续归档
archive_mode = on
archive_command = 'cp %p /archive/%f'

-- 恢复到指定时间点
restore_command = 'cp /archive/%f %p'
recovery_target_time = '2024-01-15 14:30:00'
```

## Go语言集成题

### 12. 在Go中如何正确使用pq驱动连接PostgreSQL？

**答案：**

**1. 基本连接**
```go
package main

import (
    "database/sql"
    "fmt"
    "log"
    
    _ "github.com/lib/pq"
)

func main() {
    // 连接字符串
    connStr := "host=localhost port=5432 user=postgres " +
               "password=secret dbname=mydb sslmode=disable"
    
    // 打开连接
    db, err := sql.Open("postgres", connStr)
    if err != nil {
        log.Fatal(err)
    }
    defer db.Close()
    
    // 测试连接
    if err := db.Ping(); err != nil {
        log.Fatal(err)
    }
    
    fmt.Println("Connected to PostgreSQL!")
}
```

**2. 连接池配置**
```go
func setupDB() *sql.DB {
    db, err := sql.Open("postgres", connStr)
    if err != nil {
        log.Fatal(err)
    }
    
    // 连接池配置
    db.SetMaxOpenConns(25)                 // 最大打开连接数
    db.SetMaxIdleConns(5)                  // 最大空闲连接数
    db.SetConnMaxLifetime(5 * time.Minute) // 连接最大生存时间
    db.SetConnMaxIdleTime(1 * time.Minute) // 连接最大空闲时间
    
    return db
}
```

**3. 事务处理**
```go
func transferMoney(db *sql.DB, fromID, toID int, amount float64) error {
    tx, err := db.Begin()
    if err != nil {
        return err
    }
    defer tx.Rollback() // 确保回滚
    
    // 扣款
    _, err = tx.Exec(
        "UPDATE accounts SET balance = balance - $1 WHERE id = $2",
        amount, fromID,
    )
    if err != nil {
        return err
    }
    
    // 入账
    _, err = tx.Exec(
        "UPDATE accounts SET balance = balance + $1 WHERE id = $2",
        amount, toID,
    )
    if err != nil {
        return err
    }
    
    // 提交事务
    return tx.Commit()
}
```

### 13. 如何在Go中处理PostgreSQL的特殊数据类型？

**答案：**

**1. JSON类型处理**
```go
import (
    "database/sql/driver"
    "encoding/json"
    "github.com/lib/pq"
)

type User struct {
    ID       int             `json:"id"`
    Name     string          `json:"name"`
    Metadata json.RawMessage `json:"metadata"`
}

func insertUser(db *sql.DB, user User) error {
    query := `
        INSERT INTO users (name, metadata) 
        VALUES ($1, $2) 
        RETURNING id
    `
    
    err := db.QueryRow(query, user.Name, user.Metadata).Scan(&user.ID)
    return err
}

func getUserWithJSON(db *sql.DB, id int) (*User, error) {
    var user User
    query := "SELECT id, name, metadata FROM users WHERE id = $1"
    
    err := db.QueryRow(query, id).Scan(
        &user.ID,
        &user.Name,
        &user.Metadata,
    )
    
    return &user, err
}
```

**2. 数组类型处理**
```go
import "github.com/lib/pq"

func insertTags(db *sql.DB, userID int, tags []string) error {
    query := "UPDATE users SET tags = $1 WHERE id = $2"
    _, err := db.Exec(query, pq.Array(tags), userID)
    return err
}

func getUserTags(db *sql.DB, userID int) ([]string, error) {
    var tags pq.StringArray
    query := "SELECT tags FROM users WHERE id = $1"
    
    err := db.QueryRow(query, userID).Scan(&tags)
    return []string(tags), err
}
```

**3. 时间类型处理**
```go
import "time"

type Order struct {
    ID        int       `json:"id"`
    UserID    int       `json:"user_id"`
    CreatedAt time.Time `json:"created_at"`
    UpdatedAt *time.Time `json:"updated_at,omitempty"`
}

func insertOrder(db *sql.DB, order *Order) error {
    query := `
        INSERT INTO orders (user_id, created_at) 
        VALUES ($1, $2) 
        RETURNING id
    `
    
    err := db.QueryRow(query, order.UserID, order.CreatedAt).Scan(&order.ID)
    return err
}
```

## 架构层问题

### 16. 描述PostgreSQL的进程模型及其优势？

**答案：**

PostgreSQL采用多进程架构模型：

**核心组件：**
1. **Postmaster主进程**
   - 监听客户端连接请求
   - 管理所有子进程生命周期
   - 处理系统级信号和全局事务控制

2. **Backend Processes（后端进程）**
   - 每个客户端连接对应一个独立后端进程
   - 拥有私有内存区域处理查询执行
   - 维护会话级别的上下文信息

3. **辅助后台进程**
   ```
   - WAL Writer: 持久化事务日志
   - Background Writer: 刷新脏页到磁盘
   - Checkpointer: 触发检查点操作
   - Logical Replication Workers: 处理逻辑复制
   - Parallel Query Workers: 并行查询执行
   ```

**架构优势：**
- **内存隔离性**：单个会话异常不会影响其他会话
- **水平扩展能力**：支持数千并发连接
- **资源共享机制**：通过共享内存管理全局事务状态
- **稳定性保障**：postmaster进程可重启失败的子进程
- **资源控制能力**：可独立配置max_connections限制

### 17. 如何分析和解决序列化事务中的长事务问题？

**分析工具：**
```sql
-- 查看活跃事务
SELECT * FROM pg_stat_activity 
WHERE state = 'active' AND current_query NOT LIKE '%pg_stat_activity%';

-- 查看长时间运行的事务
SELECT pid, now() - query_start AS duration, query 
FROM pg_stat_statements 
WHERE now() - query_start > interval '5 minutes'
ORDER BY duration DESC;

-- 查看事务年龄
SELECT datname, age(datfrozenxid) FROM pg_database;
```

**解决方案：**
1. **超时设置**
```sql
-- 设置空闲事务超时（毫秒）
SET idle_in_transaction_session_timeout = 30000;

-- 设置语句超时
SET statement_timeout = '30s';
```

2. **监控告警**
```sql
-- 启用自动解释计划收集
SET auto_explain.log_min_duration = '5s';
SET auto_explain.log_analyze = true;
```

3. **优化策略**
```sql
-- 对OLAP查询使用低隔离级别
BEGIN TRANSACTION ISOLATION LEVEL READ COMMITTED;

-- 分批提交大事务
DO $$
DECLARE
    rec RECORD;
BEGIN
    FOR rec IN SELECT * FROM large_table WHERE processed = false
    LOOP
        -- 处理记录
        UPDATE large_table SET processed = true WHERE CURRENT OF cursor_name;
        
        -- 每处理1000条提交一次
        IF FOUND THEN
            PERFORM pg_sleep(0.1);
            COMMIT;
            BEGIN;
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;
```

4. **维护操作**
```sql
-- 执行vacuum防止膨胀
VACUUM VERBOSE ANALYZE your_table;

-- 查看表膨胀情况
SELECT 
    pg_class.relname AS object_name,
    pg_size_pretty(pg_class.reltuples::bigint) AS num_rows,
    pg_size_pretty(pg_class.relpages::bigint) AS num_pages,
    pg_size_pretty(pg_total_relation_size(pg_class.oid)) AS total_size
FROM pg_class
WHERE relkind = 'r'
ORDER BY pg_class.relpages DESC LIMIT 20;
```

## 分布式场景挑战

### 18. Citus扩展如何实现横向扩展？其主要限制是什么？

**Citus架构特性：**

**分布式机制：**
1. **分片管理**
   - 基于分布列将数据水平拆分
   - 支持哈希、范围、列表等多种分区策略
   - 自动路由查询到目标分片

2. **查询执行**
   - 协调节点解析SQL并生成分布式执行计划
   - 并行下发查询到worker节点
   - 结果合并和排序处理

3. **弹性扩展**
   ```sql
   -- 添加新节点
   SELECT master_add_node('worker1', 5432);
   
   -- 数据rebalance
   SELECT rebalance_table_shards('distributed_table');
   ```

**局限性分析：**

**性能瓶颈：**
- 跨分片JOIN需要多次网络传输，建议本地化关联
- 分布式事务仅支持两阶段提交协议
- 聚合查询需要在协调节点进行结果合并

**功能限制：**
- 不支持跨分片外键约束
- 序列生成器可能产生间隙
- DDL操作需手动在所有节点执行

**最佳实践：**
```sql
-- 创建分布式表
SELECT create_distributed_table('orders', 'tenant_id');

-- 查询示例（利用分片裁剪）
EXPLAIN SELECT * FROM orders 
WHERE tenant_id = 'company_123' AND created_at > NOW() - INTERVAL '1 week';

-- 避免跨分片JOIN的优化
WITH user_orders AS (
    SELECT * FROM orders WHERE tenant_id = 'company_123'
)
SELECT uo.*, p.name 
FROM user_orders uo
JOIN products p ON uo.product_id = p.id 
WHERE p.tenant_id = 'company_123';
```

## 4. 分布式事务深度解析
### 4.1 解释PostgreSQL如何实现跨节点事务一致性？
**考察点**：分布式系统ACID实现机制
**参考答案**：
1. 基于两阶段提交协议（PREPARE TRANSACTION + COMMIT PREPARED）
2. Citus扩展通过协调者节点管理全局事务状态
3. 使用GTID（全局事务标识符）同步复制

### 4.2 在金融交易系统中如何优化分布式事务性能？
**场景模拟**：支付系统每秒处理5000+笔跨行转账
**解决方案**：
1. 热点账户分片：将单账户拆分为多个逻辑子账户
2. 异步落盘：设置synchronous_commit=off降低IO压力
3. 连接池优化：使用pgBouncer的transaction模式
4. 批量提交：将多个事务合并为单个XACT批量处理

### 4.3 如何监控和预防悬挂事务？
**生产实践**：
```sql
-- 查询长时间未提交的prepared事务
SELECT xid, database, user, age(current_xid(), xid) AS idle_time
FROM pg_prepared_xacts 
WHERE now() - prepared > interval '5 minutes';
```
**处置方案**：
1. 设置idle_in_transaction_session_timeout参数自动终止
2. 配置监控告警（Prometheus+Grafana）
3. 定期清理悬挂事务：EXECUTE IMMEDIATE 'ROLLBACK PREPARED ''xact_id''';

## 实战场景题

### 14. 设计一个高并发的电商订单系统，如何保证数据一致性？

**答案：**

**1. 数据库设计**
```sql
-- 用户表
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    balance DECIMAL(10,2) DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 商品表
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    stock INTEGER NOT NULL,
    version INTEGER DEFAULT 1, -- 乐观锁版本号
    created_at TIMESTAMP DEFAULT NOW()
);

-- 订单表
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    total_amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW()
);

-- 订单项表
CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER REFERENCES orders(id),
    product_id INTEGER REFERENCES products(id),
    quantity INTEGER NOT NULL,
    price DECIMAL(10,2) NOT NULL
);
```

**2. Go实现（乐观锁）**
```go
type OrderService struct {
    db *sql.DB
}

func (s *OrderService) CreateOrder(userID int, items []OrderItem) error {
    tx, err := s.db.Begin()
    if err != nil {
        return err
    }
    defer tx.Rollback()
    
    // 1. 检查库存并更新（乐观锁）
    for _, item := range items {
        var currentStock, version int
        err := tx.QueryRow(
            "SELECT stock, version FROM products WHERE id = $1",
            item.ProductID,
        ).Scan(&currentStock, &version)
        
        if err != nil {
            return err
        }
        
        if currentStock < item.Quantity {
            return errors.New("insufficient stock")
        }
        
        // 乐观锁更新库存
        result, err := tx.Exec(`
            UPDATE products 
            SET stock = stock - $1, version = version + 1 
            WHERE id = $2 AND version = $3
        `, item.Quantity, item.ProductID, version)
        
        if err != nil {
            return err
        }
        
        rowsAffected, _ := result.RowsAffected()
        if rowsAffected == 0 {
            return errors.New("product was modified by another transaction")
        }
    }
    
    // 2. 创建订单
    var orderID int
    err = tx.QueryRow(`
        INSERT INTO orders (user_id, total_amount, status) 
        VALUES ($1, $2, 'pending') 
        RETURNING id
    `, userID, calculateTotal(items)).Scan(&orderID)
    
    if err != nil {
        return err
    }
    
    // 3. 创建订单项
    for _, item := range items {
        _, err = tx.Exec(`
            INSERT INTO order_items (order_id, product_id, quantity, price) 
            VALUES ($1, $2, $3, $4)
        `, orderID, item.ProductID, item.Quantity, item.Price)
        
        if err != nil {
            return err
        }
    }
    
    return tx.Commit()
}
```

**3. 悲观锁实现**
```go
func (s *OrderService) CreateOrderWithPessimisticLock(userID int, items []OrderItem) error {
    tx, err := s.db.Begin()
    if err != nil {
        return err
    }
    defer tx.Rollback()
    
    // 悲观锁锁定商品
    for _, item := range items {
        var currentStock int
        err := tx.QueryRow(
            "SELECT stock FROM products WHERE id = $1 FOR UPDATE",
            item.ProductID,
        ).Scan(&currentStock)
        
        if err != nil {
            return err
        }
        
        if currentStock < item.Quantity {
            return errors.New("insufficient stock")
        }
        
        // 更新库存
        _, err = tx.Exec(
            "UPDATE products SET stock = stock - $1 WHERE id = $2",
            item.Quantity, item.ProductID,
        )
        
        if err != nil {
            return err
        }
    }
    
    // 创建订单和订单项...
    
    return tx.Commit()
}
```

### 15. 如何设计PostgreSQL的分区表来处理大量历史数据？

**答案：**

**1. 时间分区设计**
```sql
-- 创建主表
CREATE TABLE orders (
    id BIGSERIAL,
    user_id INTEGER NOT NULL,
    total_amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (created_at);

-- 创建分区表
CREATE TABLE orders_2024_01 PARTITION OF orders
FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');

CREATE TABLE orders_2024_02 PARTITION OF orders
FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');

CREATE TABLE orders_2024_03 PARTITION OF orders
FOR VALUES FROM ('2024-03-01') TO ('2024-04-01');

-- 创建索引
CREATE INDEX idx_orders_2024_01_user_id ON orders_2024_01(user_id);
CREATE INDEX idx_orders_2024_01_status ON orders_2024_01(status);
```

**2. 自动分区管理**
```sql
-- 创建函数自动创建分区
CREATE OR REPLACE FUNCTION create_monthly_partition(
    table_name TEXT,
    start_date DATE
) RETURNS VOID AS $$
DECLARE
    partition_name TEXT;
    end_date DATE;
BEGIN
    partition_name := table_name || '_' || to_char(start_date, 'YYYY_MM');
    end_date := start_date + INTERVAL '1 month';
    
    EXECUTE format(
        'CREATE TABLE %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
        partition_name, table_name, start_date, end_date
    );
    
    -- 创建索引
    EXECUTE format(
        'CREATE INDEX idx_%s_user_id ON %I(user_id)',
        partition_name, partition_name
    );
END;
$$ LANGUAGE plpgsql;

-- 定期执行创建下个月分区
SELECT create_monthly_partition('orders', date_trunc('month', NOW() + INTERVAL '1 month'));
```

**3. Go中的分区查询优化**
```go
type OrderRepository struct {
    db *sql.DB
}

// 查询指定时间范围的订单（利用分区裁剪）
func (r *OrderRepository) GetOrdersByDateRange(
    userID int, 
    startDate, endDate time.Time,
) ([]Order, error) {
    query := `
        SELECT id, user_id, total_amount, status, created_at
        FROM orders
        WHERE user_id = $1 
        AND created_at >= $2 
        AND created_at < $3
        ORDER BY created_at DESC
    `
    
    rows, err := r.db.Query(query, userID, startDate, endDate)
    if err != nil {
        return nil, err
    }
    defer rows.Close()
    
    var orders []Order
    for rows.Next() {
        var order Order
        err := rows.Scan(
            &order.ID,
            &order.UserID,
            &order.TotalAmount,
            &order.Status,
            &order.CreatedAt,
        )
        if err != nil {
            return nil, err
        }
        orders = append(orders, order)
    }
    
    return orders, nil
}

// 分区维护：删除旧分区
func (r *OrderRepository) DropOldPartitions(monthsToKeep int) error {
    query := `
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE tablename LIKE 'orders_%'
        AND tablename < 'orders_' || to_char(NOW() - INTERVAL '%d months', 'YYYY_MM')
    `
    
    rows, err := r.db.Query(fmt.Sprintf(query, monthsToKeep))
    if err != nil {
        return err
    }
    defer rows.Close()
    
    for rows.Next() {
        var schema, table string
        if err := rows.Scan(&schema, &table); err != nil {
            return err
        }
        
        dropQuery := fmt.Sprintf("DROP TABLE %s.%s", schema, table)
        if _, err := r.db.Exec(dropQuery); err != nil {
            return err
        }
    }
    
    return nil
}
```

## 总结

这些面试题涵盖了PostgreSQL的核心概念、架构原理、性能优化、事务处理、高可用性、分布式方案以及Go语言集成等方面。在面试中，重点关注：

1. **理论基础**：MVCC、WAL、事务隔离级别、进程模型
2. **实践经验**：性能调优（索引优化、查询分析）、分区表、长事务处理
3. **架构设计**：高可用（流复制/逻辑复制）、备份恢复、监控方案
4. **分布式方案**：Citus扩展应用、分片策略、查询路由机制
5. **编程实现**：Go语言集成（连接池配置、特殊类型处理、事务管理）
6. **问题解决**：死锁处理、慢查询优化、并发控制、序列化异常应对

建议结合实际项目经验，准备具体的案例和解决方案，特别是分布式场景下的架构设计和性能优化实践，这样在面试中能够更好地展示技术深度和实战能力。