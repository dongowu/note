# MySQL表锁与死锁问题排查指南

## 1. 表锁问题排查与解决

### 1.1 表锁类型与识别

#### 锁类型概述
```sql
-- 查看当前锁等待情况
SHOW PROCESSLIST;

-- 查看InnoDB锁状态
SHOW ENGINE INNODB STATUS\G

-- 查看锁等待详情（MySQL 5.7+）
SELECT * FROM performance_schema.data_locks;
SELECT * FROM performance_schema.data_lock_waits;

-- 查看元数据锁（MySQL 5.7+）
SELECT * FROM performance_schema.metadata_locks;
```

#### 锁监控脚本
```python
#!/usr/bin/env python3
# mysql_lock_monitor.py

import pymysql
import time
import json
from datetime import datetime

class MySQLLockMonitor:
    def __init__(self, host='localhost', user='root', password='password'):
        self.connection = pymysql.connect(
            host=host, user=user, password=password,
            charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor
        )
    
    def get_current_locks(self):
        """获取当前锁信息"""
        with self.connection.cursor() as cursor:
            # 获取进程列表
            cursor.execute("SHOW PROCESSLIST")
            processes = cursor.fetchall()
            
            # 获取InnoDB状态
            cursor.execute("SHOW ENGINE INNODB STATUS")
            innodb_status = cursor.fetchone()['Status']
            
            # 解析锁等待信息
            lock_waits = []
            for process in processes:
                if process['State'] and 'lock' in process['State'].lower():
                    lock_waits.append({
                        'id': process['Id'],
                        'user': process['User'],
                        'host': process['Host'],
                        'db': process['db'],
                        'command': process['Command'],
                        'time': process['Time'],
                        'state': process['State'],
                        'info': process['Info']
                    })
            
            return {
                'timestamp': datetime.now().isoformat(),
                'lock_waits': lock_waits,
                'innodb_status': innodb_status
            }
    
    def detect_long_running_transactions(self, threshold_seconds=30):
        """检测长时间运行的事务"""
        with self.connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    trx_id,
                    trx_state,
                    trx_started,
                    trx_requested_lock_id,
                    trx_wait_started,
                    trx_weight,
                    trx_mysql_thread_id,
                    trx_query,
                    TIMESTAMPDIFF(SECOND, trx_started, NOW()) as duration_seconds
                FROM information_schema.innodb_trx 
                WHERE TIMESTAMPDIFF(SECOND, trx_started, NOW()) > %s
                ORDER BY trx_started
            """, (threshold_seconds,))
            
            return cursor.fetchall()
    
    def get_blocking_transactions(self):
        """获取阻塞事务信息"""
        with self.connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    r.trx_id AS waiting_trx_id,
                    r.trx_mysql_thread_id AS waiting_thread,
                    r.trx_query AS waiting_query,
                    b.trx_id AS blocking_trx_id,
                    b.trx_mysql_thread_id AS blocking_thread,
                    b.trx_query AS blocking_query,
                    l.lock_table,
                    l.lock_index,
                    l.lock_mode
                FROM information_schema.innodb_lock_waits w
                INNER JOIN information_schema.innodb_trx b ON b.trx_id = w.blocking_trx_id
                INNER JOIN information_schema.innodb_trx r ON r.trx_id = w.requesting_trx_id
                INNER JOIN information_schema.innodb_locks l ON l.lock_id = w.requested_lock_id
            """)
            
            return cursor.fetchall()
    
    def kill_blocking_transaction(self, thread_id):
        """终止阻塞事务"""
        with self.connection.cursor() as cursor:
            cursor.execute(f"KILL {thread_id}")
            return f"已终止线程 {thread_id}"

if __name__ == "__main__":
    monitor = MySQLLockMonitor()
    
    while True:
        try:
            print(f"\n=== 锁监控 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
            
            # 检查长时间运行的事务
            long_trx = monitor.detect_long_running_transactions(30)
            if long_trx:
                print(f"\n⚠️  发现 {len(long_trx)} 个长时间运行的事务:")
                for trx in long_trx:
                    print(f"  事务ID: {trx['trx_id']}, 持续时间: {trx['duration_seconds']}秒")
                    print(f"  查询: {trx['trx_query'][:100]}...")
            
            # 检查阻塞事务
            blocking = monitor.get_blocking_transactions()
            if blocking:
                print(f"\n🚫 发现 {len(blocking)} 个阻塞情况:")
                for block in blocking:
                    print(f"  阻塞线程: {block['blocking_thread']} -> 等待线程: {block['waiting_thread']}")
                    print(f"  表: {block['lock_table']}, 锁模式: {block['lock_mode']}")
            
            time.sleep(10)  # 每10秒检查一次
            
        except Exception as e:
            print(f"监控异常: {e}")
            time.sleep(10)
```

### 1.2 表锁问题解决方案

#### 方案1：优化查询和事务
```sql
-- 1. 避免长时间事务
-- 错误示例
START TRANSACTION;
SELECT * FROM large_table WHERE condition; -- 大量数据查询
-- ... 其他业务逻辑处理 ...
UPDATE another_table SET status = 1;
COMMIT;

-- 正确示例
-- 先完成查询，缓存结果
SELECT * FROM large_table WHERE condition;
-- 业务逻辑处理
-- 快速事务更新
START TRANSACTION;
UPDATE another_table SET status = 1 WHERE id = ?;
COMMIT;

-- 2. 使用合适的隔离级别
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;

-- 3. 添加合适的索引减少锁范围
CREATE INDEX idx_status_created ON orders(status, created_at);

-- 4. 使用SELECT ... FOR UPDATE时指定具体行
SELECT * FROM accounts WHERE id = 123 FOR UPDATE;
```

#### 方案2：锁超时和重试机制
```python
# 应用层重试机制
import pymysql
import time
import random

class MySQLRetryHandler:
    def __init__(self, max_retries=3, base_delay=0.1):
        self.max_retries = max_retries
        self.base_delay = base_delay
    
    def execute_with_retry(self, connection, sql, params=None):
        """带重试的SQL执行"""
        for attempt in range(self.max_retries + 1):
            try:
                with connection.cursor() as cursor:
                    cursor.execute(sql, params)
                    connection.commit()
                    return cursor.fetchall()
            
            except pymysql.err.OperationalError as e:
                if e.args[0] == 1205:  # Lock wait timeout
                    if attempt < self.max_retries:
                        # 指数退避 + 随机抖动
                        delay = self.base_delay * (2 ** attempt) + random.uniform(0, 0.1)
                        print(f"锁等待超时，{delay:.2f}秒后重试 (尝试 {attempt + 1}/{self.max_retries})")
                        time.sleep(delay)
                        continue
                    else:
                        raise Exception(f"重试 {self.max_retries} 次后仍然失败")
                else:
                    raise
            
            except Exception as e:
                raise

# 使用示例
retry_handler = MySQLRetryHandler(max_retries=3)
connection = pymysql.connect(host='localhost', user='user', password='pass', database='db')

try:
    result = retry_handler.execute_with_retry(
        connection,
        "UPDATE accounts SET balance = balance - %s WHERE id = %s",
        (100, 123)
    )
except Exception as e:
    print(f"操作失败: {e}")
```

## 2. 死锁问题排查与解决

### 2.1 死锁检测与分析

#### 死锁日志分析
```bash
#!/bin/bash
# deadlock_analyzer.sh - 死锁日志分析脚本

echo "=== MySQL死锁分析 ==="

# 从错误日志中提取死锁信息
echo "最近的死锁记录:"
grep -A 50 "LATEST DETECTED DEADLOCK" /var/log/mysql/error.log | tail -100

# 从InnoDB状态中获取死锁信息
mysql -u root -p -e "SHOW ENGINE INNODB STATUS\G" | grep -A 30 "LATEST DETECTED DEADLOCK"

echo "\n死锁统计:"
grep "LATEST DETECTED DEADLOCK" /var/log/mysql/error.log | wc -l
```

#### 死锁监控脚本
```python
#!/usr/bin/env python3
# deadlock_monitor.py

import pymysql
import re
import json
from datetime import datetime

class DeadlockMonitor:
    def __init__(self, host='localhost', user='root', password='password'):
        self.connection = pymysql.connect(
            host=host, user=user, password=password,
            charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor
        )
    
    def get_deadlock_info(self):
        """获取最新死锁信息"""
        with self.connection.cursor() as cursor:
            cursor.execute("SHOW ENGINE INNODB STATUS")
            status = cursor.fetchone()['Status']
            
            # 解析死锁信息
            deadlock_section = self._extract_deadlock_section(status)
            if deadlock_section:
                return self._parse_deadlock_info(deadlock_section)
            
            return None
    
    def _extract_deadlock_section(self, status):
        """提取死锁部分"""
        lines = status.split('\n')
        deadlock_start = -1
        deadlock_end = -1
        
        for i, line in enumerate(lines):
            if 'LATEST DETECTED DEADLOCK' in line:
                deadlock_start = i
            elif deadlock_start != -1 and line.startswith('---'):
                deadlock_end = i
                break
        
        if deadlock_start != -1 and deadlock_end != -1:
            return '\n'.join(lines[deadlock_start:deadlock_end])
        
        return None
    
    def _parse_deadlock_info(self, deadlock_text):
        """解析死锁信息"""
        info = {
            'timestamp': None,
            'transactions': [],
            'victim_transaction': None
        }
        
        # 提取时间戳
        timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', deadlock_text)
        if timestamp_match:
            info['timestamp'] = timestamp_match.group(1)
        
        # 提取事务信息
        transaction_sections = re.split(r'\*\*\* \(\d+\) TRANSACTION:', deadlock_text)[1:]
        
        for section in transaction_sections:
            transaction = self._parse_transaction_section(section)
            if transaction:
                info['transactions'].append(transaction)
        
        # 提取被回滚的事务
        victim_match = re.search(r'WE ROLL BACK TRANSACTION \((\d+)\)', deadlock_text)
        if victim_match:
            info['victim_transaction'] = victim_match.group(1)
        
        return info
    
    def _parse_transaction_section(self, section):
        """解析单个事务信息"""
        lines = section.strip().split('\n')
        if not lines:
            return None
        
        transaction = {
            'id': None,
            'thread_id': None,
            'query': None,
            'locks_held': [],
            'locks_waiting': []
        }
        
        # 解析事务ID和线程ID
        first_line = lines[0]
        id_match = re.search(r'ACTIVE (\d+) sec.*thread id (\d+)', first_line)
        if id_match:
            transaction['thread_id'] = id_match.group(2)
        
        # 解析查询语句
        for line in lines:
            if line.strip().startswith('MySQL thread id'):
                query_start = lines.index(line) + 1
                if query_start < len(lines):
                    transaction['query'] = lines[query_start].strip()
                break
        
        return transaction
    
    def analyze_deadlock_pattern(self, hours=24):
        """分析死锁模式"""
        # 这里可以连接到日志文件或监控系统
        # 分析死锁发生的模式、频率、涉及的表等
        pass

if __name__ == "__main__":
    monitor = DeadlockMonitor()
    
    deadlock_info = monitor.get_deadlock_info()
    if deadlock_info:
        print("发现死锁:")
        print(json.dumps(deadlock_info, indent=2, ensure_ascii=False))
    else:
        print("未发现最近的死锁")
```

### 2.2 死锁预防策略

#### 策略1：统一锁顺序
```sql
-- 错误示例：不同的锁顺序可能导致死锁
-- 事务A
START TRANSACTION;
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
UPDATE accounts SET balance = balance + 100 WHERE id = 2;
COMMIT;

-- 事务B
START TRANSACTION;
UPDATE accounts SET balance = balance - 50 WHERE id = 2;
UPDATE accounts SET balance = balance + 50 WHERE id = 1;
COMMIT;

-- 正确示例：统一按ID顺序加锁
-- 转账函数
DELIMITER //
CREATE PROCEDURE SafeTransfer(IN from_id INT, IN to_id INT, IN amount DECIMAL(10,2))
BEGIN
    DECLARE min_id INT;
    DECLARE max_id INT;
    
    -- 确保按ID顺序加锁
    IF from_id < to_id THEN
        SET min_id = from_id;
        SET max_id = to_id;
    ELSE
        SET min_id = to_id;
        SET max_id = from_id;
    END IF;
    
    START TRANSACTION;
    
    -- 按顺序锁定账户
    SELECT balance INTO @balance1 FROM accounts WHERE id = min_id FOR UPDATE;
    SELECT balance INTO @balance2 FROM accounts WHERE id = max_id FOR UPDATE;
    
    -- 执行转账
    UPDATE accounts SET balance = balance - amount WHERE id = from_id;
    UPDATE accounts SET balance = balance + amount WHERE id = to_id;
    
    COMMIT;
END//
DELIMITER ;
```

#### 策略2：减少事务大小和持有时间
```python
# 应用层事务优化
class OptimizedTransactionManager:
    def __init__(self, connection):
        self.connection = connection
    
    def batch_update_with_small_transactions(self, updates, batch_size=100):
        """分批处理大量更新，减少锁持有时间"""
        total_updated = 0
        
        for i in range(0, len(updates), batch_size):
            batch = updates[i:i + batch_size]
            
            try:
                with self.connection.cursor() as cursor:
                    self.connection.begin()
                    
                    for update in batch:
                        cursor.execute(
                            "UPDATE products SET stock = stock - %s WHERE id = %s AND stock >= %s",
                            (update['quantity'], update['product_id'], update['quantity'])
                        )
                    
                    self.connection.commit()
                    total_updated += len(batch)
                    
                    # 短暂休眠，让其他事务有机会执行
                    time.sleep(0.01)
                    
            except Exception as e:
                self.connection.rollback()
                print(f"批次更新失败: {e}")
                raise
        
        return total_updated
    
    def optimistic_locking_update(self, table, id_value, updates, version_field='version'):
        """乐观锁更新"""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                with self.connection.cursor() as cursor:
                    # 读取当前版本
                    cursor.execute(f"SELECT {version_field} FROM {table} WHERE id = %s", (id_value,))
                    result = cursor.fetchone()
                    if not result:
                        raise Exception("记录不存在")
                    
                    current_version = result[version_field]
                    
                    # 构建更新SQL
                    set_clause = ', '.join([f"{k} = %s" for k in updates.keys()])
                    sql = f"""
                        UPDATE {table} 
                        SET {set_clause}, {version_field} = {version_field} + 1 
                        WHERE id = %s AND {version_field} = %s
                    """
                    
                    # 执行更新
                    params = list(updates.values()) + [id_value, current_version]
                    cursor.execute(sql, params)
                    
                    if cursor.rowcount == 0:
                        if attempt < max_retries - 1:
                            time.sleep(0.1 * (attempt + 1))  # 递增延迟
                            continue
                        else:
                            raise Exception("乐观锁冲突，更新失败")
                    
                    self.connection.commit()
                    return True
                    
            except Exception as e:
                self.connection.rollback()
                if attempt == max_retries - 1:
                    raise
        
        return False
```

#### 策略3：使用适当的索引
```sql
-- 确保WHERE条件有合适的索引，减少锁范围
-- 错误：全表扫描导致大范围锁
UPDATE orders SET status = 'shipped' WHERE customer_id = 123;

-- 正确：添加索引
CREATE INDEX idx_customer_id ON orders(customer_id);
UPDATE orders SET status = 'shipped' WHERE customer_id = 123;

-- 复合索引优化范围查询
CREATE INDEX idx_status_created ON orders(status, created_at);
UPDATE orders SET status = 'processed' 
WHERE status = 'pending' AND created_at < '2024-01-01';
```

### 2.3 死锁自动处理机制

#### 自动死锁检测配置
```sql
-- 查看死锁检测配置
SHOW VARIABLES LIKE 'innodb_deadlock_detect';
SHOW VARIABLES LIKE 'innodb_lock_wait_timeout';

-- 调整死锁检测参数
SET GLOBAL innodb_deadlock_detect = ON;  -- 启用自动死锁检测
SET GLOBAL innodb_lock_wait_timeout = 50;  -- 锁等待超时时间（秒）

-- 在my.cnf中永久设置
# [mysqld]
# innodb_deadlock_detect = ON
# innodb_lock_wait_timeout = 50
```

#### 死锁告警脚本
```bash
#!/bin/bash
# deadlock_alert.sh - 死锁告警脚本

DEADLOCK_LOG="/var/log/mysql/deadlock.log"
ALERT_THRESHOLD=5  # 5分钟内超过此数量触发告警
TIME_WINDOW=300    # 5分钟

# 检查最近5分钟的死锁数量
deadlock_count=$(mysql -u monitor -p'password' -e "SHOW ENGINE INNODB STATUS\G" | 
    grep "LATEST DETECTED DEADLOCK" | wc -l)

if [ $deadlock_count -gt $ALERT_THRESHOLD ]; then
    echo "$(date): 检测到频繁死锁，数量: $deadlock_count" >> $DEADLOCK_LOG
    
    # 发送告警（可以集成钉钉、邮件等）
    curl -X POST "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK" \
        -H 'Content-type: application/json' \
        --data '{"text":"MySQL死锁告警: 检测到频繁死锁，数量: '$deadlock_count'"}'
fi
```

## 3. 锁优化最佳实践

### 3.1 应用层优化

```python
# 连接池配置优化
import pymysql.cursors
from dbutils.pooled_db import PooledDB

class OptimizedConnectionPool:
    def __init__(self):
        self.pool = PooledDB(
            creator=pymysql,
            maxconnections=20,  # 最大连接数
            mincached=5,        # 最小缓存连接数
            maxcached=10,       # 最大缓存连接数
            maxshared=0,        # 最大共享连接数
            blocking=True,      # 连接池满时是否阻塞
            maxusage=1000,      # 连接最大使用次数
            setsession=[        # 连接初始化SQL
                'SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED',
                'SET SESSION innodb_lock_wait_timeout = 10'
            ],
            host='localhost',
            user='app_user',
            password='password',
            database='app_db',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
    
    def get_connection(self):
        return self.pool.connection()
    
    def execute_transaction(self, operations):
        """执行事务操作"""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                conn.begin()
                
                for operation in operations:
                    cursor.execute(operation['sql'], operation.get('params', []))
                
                conn.commit()
                return True
                
        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.close()
```

### 3.2 数据库层优化

```sql
-- 1. 合理设置隔离级别
-- 全局设置
SET GLOBAL transaction_isolation = 'READ-COMMITTED';

-- 会话级设置
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;

-- 2. 优化表结构
-- 添加合适的索引
CREATE INDEX idx_user_status ON users(status) USING BTREE;
CREATE INDEX idx_order_date_status ON orders(order_date, status) USING BTREE;

-- 3. 分区表减少锁竞争
CREATE TABLE orders_partitioned (
    id INT AUTO_INCREMENT,
    user_id INT,
    order_date DATE,
    status VARCHAR(20),
    amount DECIMAL(10,2),
    PRIMARY KEY (id, order_date)
) PARTITION BY RANGE (YEAR(order_date)) (
    PARTITION p2023 VALUES LESS THAN (2024),
    PARTITION p2024 VALUES LESS THAN (2025),
    PARTITION p_future VALUES LESS THAN MAXVALUE
);

-- 4. 使用合适的存储引擎
-- InnoDB行级锁
ALTER TABLE high_concurrency_table ENGINE=InnoDB;

-- 5. 优化查询语句
-- 使用覆盖索引减少回表
CREATE INDEX idx_covering ON products(category_id, status, price, name);
SELECT name, price FROM products 
WHERE category_id = 1 AND status = 'active';
```

### 3.3 监控和告警

```yaml
# prometheus监控规则
groups:
- name: mysql_locks
  rules:
  - alert: MySQLHighLockWaits
    expr: mysql_global_status_innodb_row_lock_waits > 100
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "MySQL锁等待过多"
      description: "InnoDB行锁等待数量: {{ $value }}"
  
  - alert: MySQLDeadlockDetected
    expr: increase(mysql_global_status_innodb_deadlocks[5m]) > 5
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "MySQL死锁频发"
      description: "5分钟内检测到 {{ $value }} 次死锁"
  
  - alert: MySQLLongRunningTransaction
    expr: mysql_info_schema_innodb_trx_time_seconds > 300
    for: 1m
    labels:
      severity: warning
    annotations:
      summary: "MySQL长时间运行事务"
      description: "事务运行时间超过5分钟"
```

## 4. 应急处理流程

### 4.1 锁等待处理

```bash
#!/bin/bash
# emergency_lock_handler.sh

echo "=== MySQL锁等待应急处理 ==="

# 1. 查看当前锁等待情况
echo "当前进程列表:"
mysql -u root -p -e "SHOW PROCESSLIST" | grep -E "(Waiting|Locked)"

# 2. 查看长时间运行的事务
echo "\n长时间运行的事务:"
mysql -u root -p -e "
SELECT 
    trx_id,
    trx_mysql_thread_id,
    TIMESTAMPDIFF(SECOND, trx_started, NOW()) as duration_seconds,
    trx_query
FROM information_schema.innodb_trx 
WHERE TIMESTAMPDIFF(SECOND, trx_started, NOW()) > 60
ORDER BY duration_seconds DESC;"

# 3. 提供终止选项
read -p "是否需要终止长时间运行的事务？(y/N): " kill_long_trx
if [[ $kill_long_trx =~ ^[Yy]$ ]]; then
    echo "请手动执行: KILL <thread_id>"
fi

# 4. 重启MySQL（最后手段）
read -p "是否需要重启MySQL服务？(y/N): " restart_mysql
if [[ $restart_mysql =~ ^[Yy]$ ]]; then
    echo "重启MySQL服务..."
    sudo systemctl restart mysql
    echo "MySQL服务已重启"
fi
```

### 4.2 死锁恢复

```python
#!/usr/bin/env python3
# deadlock_recovery.py

import pymysql
import time
import logging

class DeadlockRecovery:
    def __init__(self, connection_config):
        self.config = connection_config
        self.logger = logging.getLogger(__name__)
    
    def auto_recovery(self, failed_operations):
        """自动恢复死锁失败的操作"""
        recovery_results = []
        
        for operation in failed_operations:
            try:
                result = self._retry_operation(operation)
                recovery_results.append({
                    'operation_id': operation['id'],
                    'status': 'success',
                    'result': result
                })
            except Exception as e:
                recovery_results.append({
                    'operation_id': operation['id'],
                    'status': 'failed',
                    'error': str(e)
                })
                self.logger.error(f"操作 {operation['id']} 恢复失败: {e}")
        
        return recovery_results
    
    def _retry_operation(self, operation, max_retries=3):
        """重试单个操作"""
        for attempt in range(max_retries):
            try:
                connection = pymysql.connect(**self.config)
                
                with connection.cursor() as cursor:
                    connection.begin()
                    
                    # 执行操作
                    for sql_op in operation['sql_operations']:
                        cursor.execute(sql_op['sql'], sql_op.get('params', []))
                    
                    connection.commit()
                    return cursor.fetchall()
                    
            except pymysql.err.OperationalError as e:
                if e.args[0] == 1213:  # Deadlock
                    if attempt < max_retries - 1:
                        # 指数退避
                        delay = (2 ** attempt) * 0.1
                        time.sleep(delay)
                        continue
                    else:
                        raise
                else:
                    raise
            finally:
                if 'connection' in locals():
                    connection.close()
        
        raise Exception(f"重试 {max_retries} 次后仍然失败")

# 使用示例
if __name__ == "__main__":
    config = {
        'host': 'localhost',
        'user': 'app_user',
        'password': 'password',
        'database': 'app_db',
        'charset': 'utf8mb4'
    }
    
    recovery = DeadlockRecovery(config)
    
    # 模拟失败的操作
    failed_ops = [
        {
            'id': 'transfer_001',
            'sql_operations': [
                {
                    'sql': 'UPDATE accounts SET balance = balance - %s WHERE id = %s',
                    'params': [100, 1]
                },
                {
                    'sql': 'UPDATE accounts SET balance = balance + %s WHERE id = %s',
                    'params': [100, 2]
                }
            ]
        }
    ]
    
    results = recovery.auto_recovery(failed_ops)
    print(f"恢复结果: {results}")
```

## 5. 总结

### 5.1 预防措施
1. **设计阶段**：合理的表结构设计、索引设计
2. **开发阶段**：统一锁顺序、减少事务大小、使用合适的隔离级别
3. **部署阶段**：合理的参数配置、监控告警设置
4. **运维阶段**：定期检查、性能调优、应急预案

### 5.2 最佳实践
1. **避免长事务**：尽快提交或回滚事务
2. **统一锁顺序**：按照固定顺序获取锁资源
3. **使用合适的索引**：减少锁的范围和持有时间
4. **监控和告警**：及时发现和处理锁问题
5. **应急预案**：制定完善的故障处理流程

通过系统性的预防、监控和处理机制，可以有效减少MySQL表锁和死锁问题，确保数据库系统的稳定运行。