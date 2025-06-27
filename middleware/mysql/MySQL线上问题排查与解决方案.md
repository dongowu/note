# MySQL线上问题排查与解决方案

## 目录
1. [性能问题排查](#性能问题排查)
2. [CPU占用过高问题](#cpu占用过高问题)
3. [数据不一致问题](#数据不一致问题)
4. [主从复制不一致问题](#主从复制不一致问题)
5. [连接池满问题](#连接池满问题)
6. [综合监控与预防](#综合监控与预防)

---

## 性能问题排查

### 1. 执行速度变慢问题

#### 症状识别
- 查询响应时间明显增长
- 应用程序超时频繁
- 数据库连接等待时间过长
- 慢查询日志记录增多

#### 排查步骤

##### 1.1 慢查询分析
```sql
-- 开启慢查询日志
SET GLOBAL slow_query_log = 'ON';
SET GLOBAL long_query_time = 2;
SET GLOBAL log_queries_not_using_indexes = 'ON';

-- 查看慢查询配置
SHOW VARIABLES LIKE '%slow%';

-- 分析慢查询
SHOW PROCESSLIST;
```

##### 1.2 执行计划分析
```sql
-- 分析具体查询的执行计划
EXPLAIN SELECT * FROM users WHERE email = 'test@example.com';

-- 详细执行计划
EXPLAIN FORMAT=JSON SELECT * FROM users WHERE email = 'test@example.com';

-- 实际执行统计
EXPLAIN ANALYZE SELECT * FROM users WHERE email = 'test@example.com';
```

##### 1.3 索引优化检查
```sql
-- 检查表的索引使用情况
SHOW INDEX FROM users;

-- 查看索引统计信息
SELECT 
    TABLE_SCHEMA,
    TABLE_NAME,
    INDEX_NAME,
    CARDINALITY,
    SUB_PART,
    NULLABLE
FROM information_schema.STATISTICS 
WHERE TABLE_SCHEMA = 'your_database';

-- 检查未使用的索引
SELECT 
    object_schema,
    object_name,
    index_name
FROM performance_schema.table_io_waits_summary_by_index_usage 
WHERE index_name IS NOT NULL 
AND count_star = 0;
```

#### 解决方案

##### 1.1 索引优化
```sql
-- 创建复合索引
CREATE INDEX idx_user_email_status ON users(email, status);

-- 创建覆盖索引
CREATE INDEX idx_user_cover ON users(user_id, email, name, created_at);

-- 删除重复或无用索引
DROP INDEX idx_duplicate ON users;
```

##### 1.2 查询优化
```sql
-- 优化前：全表扫描
SELECT * FROM orders WHERE DATE(created_at) = '2024-01-01';

-- 优化后：使用范围查询
SELECT * FROM orders 
WHERE created_at >= '2024-01-01 00:00:00' 
AND created_at < '2024-01-02 00:00:00';

-- 优化前：子查询
SELECT * FROM users WHERE id IN (
    SELECT user_id FROM orders WHERE status = 'completed'
);

-- 优化后：JOIN查询
SELECT DISTINCT u.* 
FROM users u 
INNER JOIN orders o ON u.id = o.user_id 
WHERE o.status = 'completed';
```

##### 1.3 表结构优化
```sql
-- 分区表优化
CREATE TABLE orders_partitioned (
    id INT AUTO_INCREMENT,
    user_id INT,
    created_at DATETIME,
    status VARCHAR(20),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (YEAR(created_at)) (
    PARTITION p2023 VALUES LESS THAN (2024),
    PARTITION p2024 VALUES LESS THAN (2025),
    PARTITION p_future VALUES LESS THAN MAXVALUE
);

-- 表压缩
ALTER TABLE large_table ROW_FORMAT=COMPRESSED KEY_BLOCK_SIZE=8;
```

---

## CPU占用过高问题

### 症状识别
- MySQL进程CPU使用率持续超过80%
- 系统负载过高
- 查询响应时间增长
- 并发连接数异常

### 排查步骤

#### 2.1 系统层面监控
```bash
# 查看MySQL进程CPU使用情况
top -p $(pgrep mysqld)

# 查看MySQL线程详情
ps -eLf | grep mysqld

# 查看系统IO等待
iostat -x 1

# 查看内存使用情况
free -h
```

#### 2.2 MySQL内部监控
```sql
-- 查看当前运行的查询
SHOW FULL PROCESSLIST;

-- 查看性能统计
SELECT * FROM performance_schema.events_statements_summary_by_digest 
ORDER BY avg_timer_wait DESC LIMIT 10;

-- 查看锁等待情况
SELECT 
    r.trx_id waiting_trx_id,
    r.trx_mysql_thread_id waiting_thread,
    r.trx_query waiting_query,
    b.trx_id blocking_trx_id,
    b.trx_mysql_thread_id blocking_thread,
    b.trx_query blocking_query
FROM information_schema.innodb_lock_waits w
INNER JOIN information_schema.innodb_trx b ON b.trx_id = w.blocking_trx_id
INNER JOIN information_schema.innodb_trx r ON r.trx_id = w.requesting_trx_id;

-- 查看表锁情况
SHOW OPEN TABLES WHERE In_use > 0;
```

#### 2.3 配置参数检查
```sql
-- 查看关键配置参数
SHOW VARIABLES LIKE 'innodb_buffer_pool_size';
SHOW VARIABLES LIKE 'innodb_log_file_size';
SHOW VARIABLES LIKE 'innodb_flush_log_at_trx_commit';
SHOW VARIABLES LIKE 'sync_binlog';
SHOW VARIABLES LIKE 'max_connections';
SHOW VARIABLES LIKE 'thread_cache_size';
```

### 解决方案

#### 2.1 查询优化
```sql
-- 终止长时间运行的查询
KILL QUERY 123456;

-- 优化高CPU消耗的查询
-- 使用LIMIT限制结果集
SELECT * FROM large_table WHERE condition LIMIT 1000;

-- 避免全表扫描
SELECT * FROM users WHERE id > 1000 AND id < 2000;
```

#### 2.2 参数调优
```sql
-- 调整缓冲池大小（建议为物理内存的70-80%）
SET GLOBAL innodb_buffer_pool_size = 8589934592; -- 8GB

-- 调整线程缓存
SET GLOBAL thread_cache_size = 100;

-- 调整查询缓存（MySQL 5.7及以下）
SET GLOBAL query_cache_size = 268435456; -- 256MB
SET GLOBAL query_cache_type = 1;

-- 调整并发线程数
SET GLOBAL innodb_thread_concurrency = 16;
```

#### 2.3 硬件优化建议
```bash
# my.cnf配置优化
[mysqld]
# 基础配置
innodb_buffer_pool_size = 8G
innodb_log_file_size = 1G
innodb_flush_log_at_trx_commit = 2
sync_binlog = 0

# 并发配置
max_connections = 1000
thread_cache_size = 100
innodb_thread_concurrency = 16

# IO优化
innodb_io_capacity = 2000
innodb_io_capacity_max = 4000
innodb_flush_method = O_DIRECT
```

---

## 数据不一致问题

### 症状识别
- 同一数据在不同查询中结果不同
- 统计数据与明细数据不匹配
- 应用程序逻辑错误
- 数据完整性约束违反

### 排查步骤

#### 3.1 事务隔离级别检查
```sql
-- 查看当前隔离级别
SELECT @@transaction_isolation;

-- 查看会话隔离级别
SHOW VARIABLES LIKE 'transaction_isolation';

-- 查看当前活跃事务
SELECT 
    trx_id,
    trx_state,
    trx_started,
    trx_isolation_level,
    trx_mysql_thread_id
FROM information_schema.innodb_trx;
```

#### 3.2 锁等待分析
```sql
-- 查看锁等待详情
SELECT 
    waiting_pid,
    waiting_query,
    blocking_pid,
    blocking_query,
    wait_age,
    sql_kill_blocking_query
FROM sys.innodb_lock_waits;

-- 查看死锁信息
SHOW ENGINE INNODB STATUS\G
```

#### 3.3 数据一致性检查
```sql
-- 检查主键重复
SELECT id, COUNT(*) 
FROM users 
GROUP BY id 
HAVING COUNT(*) > 1;

-- 检查外键约束
SELECT 
    TABLE_NAME,
    CONSTRAINT_NAME,
    CONSTRAINT_TYPE
FROM information_schema.TABLE_CONSTRAINTS 
WHERE CONSTRAINT_TYPE = 'FOREIGN KEY';

-- 检查数据完整性
SELECT 
    u.id,
    u.email,
    COUNT(o.id) as order_count
FROM users u
LEFT JOIN orders o ON u.id = o.user_id
WHERE u.status = 'active'
GROUP BY u.id
HAVING order_count = 0;
```

### 解决方案

#### 3.1 事务管理优化
```sql
-- 设置合适的隔离级别
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;

-- 使用显式事务
START TRANSACTION;
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
UPDATE accounts SET balance = balance + 100 WHERE id = 2;
COMMIT;

-- 使用SELECT FOR UPDATE避免并发问题
START TRANSACTION;
SELECT balance FROM accounts WHERE id = 1 FOR UPDATE;
-- 执行业务逻辑
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
COMMIT;
```

#### 3.2 约束和触发器
```sql
-- 添加检查约束
ALTER TABLE accounts 
ADD CONSTRAINT chk_balance CHECK (balance >= 0);

-- 创建触发器保证数据一致性
DELIMITER //
CREATE TRIGGER update_user_stats 
AFTER INSERT ON orders
FOR EACH ROW
BEGIN
    UPDATE user_stats 
    SET order_count = order_count + 1,
        total_amount = total_amount + NEW.amount
    WHERE user_id = NEW.user_id;
END//
DELIMITER ;
```

#### 3.3 数据修复脚本
```sql
-- 修复重复数据
DELETE t1 FROM users t1
INNER JOIN users t2 
WHERE t1.id > t2.id AND t1.email = t2.email;

-- 修复统计数据
UPDATE user_stats us
SET order_count = (
    SELECT COUNT(*) 
    FROM orders o 
    WHERE o.user_id = us.user_id
),
total_amount = (
    SELECT COALESCE(SUM(amount), 0) 
    FROM orders o 
    WHERE o.user_id = us.user_id
);
```

---

## 主从复制不一致问题

### 症状识别
- 主从数据不同步
- 从库延迟过高
- 复制错误日志
- 应用读写分离异常

### 排查步骤

#### 4.1 复制状态检查
```sql
-- 主库状态检查
SHOW MASTER STATUS;

-- 从库状态检查
SHOW SLAVE STATUS\G

-- 检查复制延迟
SELECT 
    SECONDS_BEHIND_MASTER,
    MASTER_LOG_FILE,
    READ_MASTER_LOG_POS,
    RELAY_MASTER_LOG_FILE,
    EXEC_MASTER_LOG_POS
FROM information_schema.REPLICA_HOST_STATUS;
```

#### 4.2 复制错误分析
```sql
-- 查看复制错误
SHOW SLAVE STATUS\G
-- 重点关注：
-- Last_Error
-- Last_SQL_Error
-- Last_IO_Error

-- 查看错误日志
-- 在操作系统层面查看MySQL错误日志
tail -f /var/log/mysql/error.log
```

#### 4.3 数据一致性检查
```bash
# 使用pt-table-checksum检查数据一致性
pt-table-checksum --host=master_host --user=checksum_user --password=password \
    --databases=your_database --replicate=percona.checksums

# 使用pt-table-sync修复不一致数据
pt-table-sync --host=master_host --user=sync_user --password=password \
    --databases=your_database --dry-run
```

### 解决方案

#### 4.1 复制配置优化
```sql
-- 主库配置
[mysqld]
server-id = 1
log-bin = mysql-bin
binlog-format = ROW
sync_binlog = 1
innodb_flush_log_at_trx_commit = 1

-- 从库配置
[mysqld]
server-id = 2
relay-log = relay-bin
read_only = 1
slave_parallel_workers = 4
slave_parallel_type = LOGICAL_CLOCK
```

#### 4.2 复制错误处理
```sql
-- 跳过复制错误（谨慎使用）
STOP SLAVE;
SET GLOBAL sql_slave_skip_counter = 1;
START SLAVE;

-- 重置复制位置
STOP SLAVE;
CHANGE MASTER TO 
    MASTER_LOG_FILE='mysql-bin.000001',
    MASTER_LOG_POS=154;
START SLAVE;

-- 基于GTID的复制恢复
STOP SLAVE;
SET GTID_NEXT='3E11FA47-71CA-11E1-9E33-C80AA9429562:23';
BEGIN; COMMIT;
SET GTID_NEXT='AUTOMATIC';
START SLAVE;
```

#### 4.3 半同步复制配置
```sql
-- 主库启用半同步复制
INSTALL PLUGIN rpl_semi_sync_master SONAME 'semisync_master.so';
SET GLOBAL rpl_semi_sync_master_enabled = 1;
SET GLOBAL rpl_semi_sync_master_timeout = 1000;

-- 从库启用半同步复制
INSTALL PLUGIN rpl_semi_sync_slave SONAME 'semisync_slave.so';
SET GLOBAL rpl_semi_sync_slave_enabled = 1;
STOP SLAVE IO_THREAD;
START SLAVE IO_THREAD;
```

#### 4.4 监控脚本
```bash
#!/bin/bash
# 复制监控脚本

MASTER_HOST="192.168.1.100"
SLAVE_HOST="192.168.1.101"
USER="monitor"
PASSWORD="password"

# 检查从库延迟
DELAY=$(mysql -h$SLAVE_HOST -u$USER -p$PASSWORD -e "SHOW SLAVE STATUS\G" | grep "Seconds_Behind_Master" | awk '{print $2}')

if [ "$DELAY" = "NULL" ]; then
    echo "复制已停止！"
    # 发送告警
elif [ $DELAY -gt 60 ]; then
    echo "复制延迟过高：${DELAY}秒"
    # 发送告警
else
    echo "复制正常，延迟：${DELAY}秒"
fi
```

---

## 连接池满问题

### 症状识别
- "Too many connections"错误
- 应用程序连接超时
- 数据库连接数达到上限
- 新连接无法建立

### 排查步骤

#### 5.1 连接状态分析
```sql
-- 查看当前连接数
SHOW STATUS LIKE 'Threads_connected';
SHOW STATUS LIKE 'Max_used_connections';

-- 查看连接限制
SHOW VARIABLES LIKE 'max_connections';

-- 查看详细连接信息
SHOW FULL PROCESSLIST;

-- 按用户统计连接数
SELECT 
    USER,
    HOST,
    COUNT(*) as connection_count
FROM information_schema.PROCESSLIST 
GROUP BY USER, HOST 
ORDER BY connection_count DESC;

-- 按状态统计连接
SELECT 
    COMMAND,
    STATE,
    COUNT(*) as count
FROM information_schema.PROCESSLIST 
GROUP BY COMMAND, STATE 
ORDER BY count DESC;
```

#### 5.2 长时间连接分析
```sql
-- 查看长时间运行的连接
SELECT 
    ID,
    USER,
    HOST,
    DB,
    COMMAND,
    TIME,
    STATE,
    INFO
FROM information_schema.PROCESSLIST 
WHERE TIME > 300 -- 超过5分钟的连接
ORDER BY TIME DESC;

-- 查看Sleep状态的连接
SELECT 
    ID,
    USER,
    HOST,
    TIME
FROM information_schema.PROCESSLIST 
WHERE COMMAND = 'Sleep' AND TIME > 60
ORDER BY TIME DESC;
```

### 解决方案

#### 5.1 连接数优化
```sql
-- 增加最大连接数
SET GLOBAL max_connections = 2000;

-- 调整连接超时时间
SET GLOBAL wait_timeout = 600;
SET GLOBAL interactive_timeout = 600;

-- 优化线程缓存
SET GLOBAL thread_cache_size = 100;
```

#### 5.2 连接池配置优化
```java
// Java连接池配置示例（HikariCP）
HikariConfig config = new HikariConfig();
config.setJdbcUrl("jdbc:mysql://localhost:3306/database");
config.setUsername("user");
config.setPassword("password");

// 连接池大小配置
config.setMaximumPoolSize(20);  // 最大连接数
config.setMinimumIdle(5);       // 最小空闲连接数
config.setConnectionTimeout(30000);  // 连接超时时间
config.setIdleTimeout(600000);       // 空闲超时时间
config.setMaxLifetime(1800000);      // 连接最大生存时间

// 连接验证
config.setConnectionTestQuery("SELECT 1");
config.setValidationTimeout(5000);
```

#### 5.3 应用层优化
```python
# Python连接池示例（使用SQLAlchemy）
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

engine = create_engine(
    'mysql+pymysql://user:password@localhost/database',
    poolclass=QueuePool,
    pool_size=10,        # 连接池大小
    max_overflow=20,     # 超出pool_size后可创建的连接数
    pool_timeout=30,     # 获取连接的超时时间
    pool_recycle=3600,   # 连接回收时间
    pool_pre_ping=True   # 连接前验证
)
```

#### 5.4 监控和告警
```bash
#!/bin/bash
# 连接数监控脚本

HOST="localhost"
USER="monitor"
PASSWORD="password"

# 获取当前连接数
CURRENT_CONNECTIONS=$(mysql -h$HOST -u$USER -p$PASSWORD -e "SHOW STATUS LIKE 'Threads_connected';" | grep Threads_connected | awk '{print $2}')

# 获取最大连接数
MAX_CONNECTIONS=$(mysql -h$HOST -u$USER -p$PASSWORD -e "SHOW VARIABLES LIKE 'max_connections';" | grep max_connections | awk '{print $2}')

# 计算使用率
USAGE_RATE=$(echo "scale=2; $CURRENT_CONNECTIONS * 100 / $MAX_CONNECTIONS" | bc)

echo "当前连接数: $CURRENT_CONNECTIONS"
echo "最大连接数: $MAX_CONNECTIONS"
echo "使用率: ${USAGE_RATE}%"

# 告警阈值
if (( $(echo "$USAGE_RATE > 80" | bc -l) )); then
    echo "警告：连接数使用率超过80%"
    # 发送告警通知
fi
```

#### 5.5 紧急处理
```sql
-- 紧急情况下终止空闲连接
SELECT CONCAT('KILL ', ID, ';') as kill_command
FROM information_schema.PROCESSLIST 
WHERE COMMAND = 'Sleep' 
AND TIME > 300 
AND USER != 'root';

-- 终止长时间运行的查询
SELECT CONCAT('KILL QUERY ', ID, ';') as kill_command
FROM information_schema.PROCESSLIST 
WHERE TIME > 600 
AND COMMAND != 'Sleep'
AND USER != 'root';
```

---

## 综合监控与预防

### 6.1 性能监控指标

#### 关键性能指标（KPI）
```sql
-- 查询性能指标
SELECT 
    'QPS' as metric,
    VARIABLE_VALUE as value
FROM performance_schema.global_status 
WHERE VARIABLE_NAME = 'Queries';

-- TPS指标
SELECT 
    'TPS' as metric,
    VARIABLE_VALUE as value
FROM performance_schema.global_status 
WHERE VARIABLE_NAME IN ('Com_commit', 'Com_rollback');

-- 缓存命中率
SELECT 
    'Buffer Pool Hit Rate' as metric,
    ROUND((
        (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME = 'Innodb_buffer_pool_read_requests') -
        (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME = 'Innodb_buffer_pool_reads')
    ) * 100 / 
    (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME = 'Innodb_buffer_pool_read_requests'), 2) as hit_rate;
```

#### 监控脚本
```bash
#!/bin/bash
# MySQL综合监控脚本

HOST="localhost"
USER="monitor"
PASSWORD="password"
LOG_FILE="/var/log/mysql_monitor.log"

# 获取当前时间
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# 连接数监控
CONNECTIONS=$(mysql -h$HOST -u$USER -p$PASSWORD -e "SHOW STATUS LIKE 'Threads_connected';" | tail -1 | awk '{print $2}')

# QPS监控
QPS=$(mysql -h$HOST -u$USER -p$PASSWORD -e "SHOW STATUS LIKE 'Queries';" | tail -1 | awk '{print $2}')

# 慢查询监控
SLOW_QUERIES=$(mysql -h$HOST -u$USER -p$PASSWORD -e "SHOW STATUS LIKE 'Slow_queries';" | tail -1 | awk '{print $2}')

# 复制延迟监控
REPL_DELAY=$(mysql -h$HOST -u$USER -p$PASSWORD -e "SHOW SLAVE STATUS\G" | grep "Seconds_Behind_Master" | awk '{print $2}')

# 记录监控数据
echo "$TIMESTAMP,Connections:$CONNECTIONS,QPS:$QPS,SlowQueries:$SLOW_QUERIES,ReplDelay:$REPL_DELAY" >> $LOG_FILE

# 告警检查
if [ $CONNECTIONS -gt 800 ]; then
    echo "$TIMESTAMP: 警告 - 连接数过高: $CONNECTIONS" >> $LOG_FILE
fi

if [ "$REPL_DELAY" != "NULL" ] && [ $REPL_DELAY -gt 60 ]; then
    echo "$TIMESTAMP: 警告 - 复制延迟过高: $REPL_DELAY 秒" >> $LOG_FILE
fi
```

### 6.2 预防性维护

#### 定期维护任务
```sql
-- 定期分析表
ANALYZE TABLE users, orders, products;

-- 定期优化表
OPTIMIZE TABLE users, orders, products;

-- 检查表完整性
CHECK TABLE users, orders, products;

-- 修复表
REPAIR TABLE table_name;
```

#### 自动化维护脚本
```bash
#!/bin/bash
# MySQL自动维护脚本

HOST="localhost"
USER="maintenance"
PASSWORD="password"
DATABASE="your_database"

# 获取所有表
TABLES=$(mysql -h$HOST -u$USER -p$PASSWORD -D$DATABASE -e "SHOW TABLES;" | tail -n +2)

for TABLE in $TABLES; do
    echo "维护表: $TABLE"
    
    # 分析表
    mysql -h$HOST -u$USER -p$PASSWORD -D$DATABASE -e "ANALYZE TABLE $TABLE;"
    
    # 检查表大小，如果碎片率高则优化
    FRAGMENTATION=$(mysql -h$HOST -u$USER -p$PASSWORD -D$DATABASE -e "
        SELECT ROUND(((data_length + index_length) - data_free) * 100 / (data_length + index_length)) AS fragmentation
        FROM information_schema.tables 
        WHERE table_schema='$DATABASE' AND table_name='$TABLE';
    " | tail -1)
    
    if [ $FRAGMENTATION -lt 85 ]; then
        echo "优化表 $TABLE (碎片率: $FRAGMENTATION%)"
        mysql -h$HOST -u$USER -p$PASSWORD -D$DATABASE -e "OPTIMIZE TABLE $TABLE;"
    fi
done
```

### 6.3 容量规划

#### 存储容量监控
```sql
-- 数据库大小统计
SELECT 
    table_schema AS 'Database',
    ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) AS 'Size (MB)'
FROM information_schema.tables 
GROUP BY table_schema
ORDER BY SUM(data_length + index_length) DESC;

-- 表大小统计
SELECT 
    table_name AS 'Table',
    ROUND(((data_length + index_length) / 1024 / 1024), 2) AS 'Size (MB)',
    ROUND((data_free / 1024 / 1024), 2) AS 'Free (MB)',
    ROUND(((data_length + index_length - data_free) / (data_length + index_length) * 100), 2) AS 'Used %'
FROM information_schema.tables 
WHERE table_schema = 'your_database'
ORDER BY (data_length + index_length) DESC;
```

#### 增长趋势分析
```bash
#!/bin/bash
# 数据增长趋势分析脚本

HOST="localhost"
USER="monitor"
PASSWORD="password"
DATABASE="your_database"
LOG_FILE="/var/log/mysql_growth.log"

# 获取当前数据库大小
CURRENT_SIZE=$(mysql -h$HOST -u$USER -p$PASSWORD -e "
    SELECT ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) 
    FROM information_schema.tables 
    WHERE table_schema = '$DATABASE';
" | tail -1)

# 记录到日志
echo "$(date '+%Y-%m-%d %H:%M:%S'),$CURRENT_SIZE" >> $LOG_FILE

# 分析增长趋势（最近7天）
echo "最近7天数据增长趋势："
tail -168 $LOG_FILE | awk -F',' '{
    if (NR == 1) {
        start_size = $2
    }
    end_size = $2
}
END {
    growth = end_size - start_size
    growth_rate = (growth / start_size) * 100
    printf "起始大小: %.2f MB\n", start_size
    printf "当前大小: %.2f MB\n", end_size
    printf "增长量: %.2f MB\n", growth
    printf "增长率: %.2f%%\n", growth_rate
}'
```

### 6.4 应急响应预案

#### 性能问题应急处理
```bash
#!/bin/bash
# MySQL性能问题应急处理脚本

HOST="localhost"
USER="emergency"
PASSWORD="password"

echo "=== MySQL应急诊断开始 ==="

# 1. 检查系统资源
echo "1. 系统资源检查："
top -b -n1 | head -20
free -h
df -h

# 2. 检查MySQL状态
echo "2. MySQL连接状态："
mysql -h$HOST -u$USER -p$PASSWORD -e "SHOW STATUS LIKE 'Threads_connected';"
mysql -h$HOST -u$USER -p$PASSWORD -e "SHOW STATUS LIKE 'Max_used_connections';"

# 3. 检查当前查询
echo "3. 当前运行查询："
mysql -h$HOST -u$USER -p$PASSWORD -e "SHOW FULL PROCESSLIST;"

# 4. 检查锁等待
echo "4. 锁等待情况："
mysql -h$HOST -u$USER -p$PASSWORD -e "
    SELECT 
        r.trx_id waiting_trx_id,
        r.trx_mysql_thread_id waiting_thread,
        SUBSTRING(r.trx_query, 1, 50) waiting_query,
        b.trx_id blocking_trx_id,
        b.trx_mysql_thread_id blocking_thread,
        SUBSTRING(b.trx_query, 1, 50) blocking_query
    FROM information_schema.innodb_lock_waits w
    INNER JOIN information_schema.innodb_trx b ON b.trx_id = w.blocking_trx_id
    INNER JOIN information_schema.innodb_trx r ON r.trx_id = w.requesting_trx_id;
"

# 5. 检查慢查询
echo "5. 最近慢查询："
tail -50 /var/log/mysql/slow.log

echo "=== 应急诊断完成 ==="
```

### 6.5 最佳实践总结

#### 性能优化最佳实践
1. **索引优化**
   - 为WHERE、ORDER BY、GROUP BY子句中的列创建索引
   - 避免过多索引，影响写入性能
   - 定期分析索引使用情况，删除无用索引

2. **查询优化**
   - 避免SELECT *，只查询需要的列
   - 使用LIMIT限制结果集大小
   - 优化JOIN查询，确保连接条件有索引
   - 避免在WHERE子句中使用函数

3. **配置优化**
   - 合理设置innodb_buffer_pool_size
   - 调整连接数和超时参数
   - 优化日志配置
   - 启用查询缓存（适用于读多写少场景）

4. **监控告警**
   - 建立完善的监控体系
   - 设置合理的告警阈值
   - 定期review性能指标
   - 建立应急响应流程

5. **容量规划**
   - 定期分析数据增长趋势
   - 提前规划硬件升级
   - 考虑分库分表策略
   - 建立数据归档机制

通过系统性的监控、优化和维护，可以有效预防和解决MySQL在生产环境中遇到的各种问题，确保数据库的稳定性和高性能运行。