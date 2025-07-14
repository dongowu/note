# MySQL磁盘空间与内存问题排查指南

## 1. 磁盘空间不足问题

### 1.1 症状识别

#### 错误信息
```bash
# 常见错误日志
ERROR 1114 (HY000): The table 'table_name' is full
ERROR 28 (HY000): No space left on device
ERROR 1030 (HY000): Got error 28 from storage engine
```

#### 系统监控指标
```bash
# 磁盘使用率检查
df -h
du -sh /var/lib/mysql/*

# inode使用情况
df -i

# 实时磁盘IO监控
iostat -x 1
iotop
```

### 1.2 排查步骤

#### 步骤1：快速定位空间占用
```bash
#!/bin/bash
# mysql_disk_check.sh - MySQL磁盘空间检查脚本

echo "=== MySQL磁盘空间分析 ==="
echo "数据目录总大小："
du -sh /var/lib/mysql/

echo "\n各数据库大小排序："
du -sh /var/lib/mysql/*/ | sort -hr

echo "\n大表文件排序（前20）："
find /var/lib/mysql -name "*.ibd" -exec du -sh {} \; | sort -hr | head -20

echo "\n日志文件大小："
ls -lh /var/lib/mysql/ib_logfile*
ls -lh /var/lib/mysql/mysql-bin.*

echo "\n临时文件检查："
find /tmp -name "*mysql*" -exec ls -lh {} \;
```

#### 步骤2：数据库级别分析
```sql
-- 查看各数据库大小
SELECT 
    table_schema AS '数据库',
    ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) AS '大小(MB)'
FROM information_schema.tables 
GROUP BY table_schema 
ORDER BY SUM(data_length + index_length) DESC;

-- 查看大表排序
SELECT 
    table_schema AS '数据库',
    table_name AS '表名',
    ROUND(((data_length + index_length) / 1024 / 1024), 2) AS '大小(MB)',
    table_rows AS '行数'
FROM information_schema.tables 
WHERE table_schema NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
ORDER BY (data_length + index_length) DESC 
LIMIT 20;

-- 查看碎片化严重的表
SELECT 
    table_schema,
    table_name,
    ROUND(data_length/1024/1024, 2) AS data_mb,
    ROUND(data_free/1024/1024, 2) AS free_mb,
    ROUND(data_free/(data_length+data_free)*100, 2) AS fragmentation_pct
FROM information_schema.tables 
WHERE data_free > 0 AND table_schema NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
ORDER BY fragmentation_pct DESC;
```

### 1.3 解决方案

#### 方案1：清理历史数据
```sql
-- 安全的数据清理流程
-- 1. 创建备份
CREATE TABLE user_logs_backup_20241201 AS 
SELECT * FROM user_logs WHERE created_at < '2024-01-01';

-- 2. 分批删除（避免长时间锁表）
DELIMITER //
CREATE PROCEDURE CleanOldLogs()
BEGIN
    DECLARE done INT DEFAULT FALSE;
    DECLARE batch_size INT DEFAULT 10000;
    
    REPEAT
        DELETE FROM user_logs 
        WHERE created_at < '2024-01-01' 
        LIMIT batch_size;
        
        SELECT ROW_COUNT() INTO @affected_rows;
        
        -- 短暂休眠，减少系统压力
        SELECT SLEEP(0.1);
        
    UNTIL @affected_rows < batch_size END REPEAT;
END//
DELIMITER ;

CALL CleanOldLogs();
DROP PROCEDURE CleanOldLogs;
```

#### 方案2：表碎片整理
```sql
-- 重建表以回收空间
ALTER TABLE large_table ENGINE=InnoDB;

-- 或使用OPTIMIZE（MyISAM表）
OPTIMIZE TABLE myisam_table;

-- 批量优化脚本
SELECT CONCAT('OPTIMIZE TABLE ', table_schema, '.', table_name, ';') AS optimize_sql
FROM information_schema.tables 
WHERE data_free > 100*1024*1024  -- 碎片超过100MB
AND engine = 'MyISAM';
```

#### 方案3：日志文件管理
```sql
-- 清理二进制日志
SHOW BINARY LOGS;
PURGE BINARY LOGS BEFORE '2024-11-01 00:00:00';

-- 设置自动清理策略
SET GLOBAL expire_logs_days = 7;
SET GLOBAL binlog_expire_logs_seconds = 604800; -- 7天

-- 清理慢查询日志
-- 在my.cnf中设置
# slow_query_log_file = /var/log/mysql/slow.log
# 定期轮转日志文件
```

#### 方案4：临时解决方案
```bash
# 创建软链接到其他磁盘
sudo service mysql stop
sudo mv /var/lib/mysql/large_database /mnt/extra_disk/
sudo ln -s /mnt/extra_disk/large_database /var/lib/mysql/
sudo chown -R mysql:mysql /mnt/extra_disk/large_database
sudo service mysql start
```

## 2. 内存不足与OOM问题

### 2.1 症状识别

#### 系统层面
```bash
# 内存使用监控
free -h
cat /proc/meminfo

# OOM日志检查
dmesg | grep -i "killed process"
grep -i "out of memory" /var/log/messages
grep -i "oom" /var/log/syslog

# MySQL进程内存使用
ps aux | grep mysql
pmap -d $(pidof mysqld)
```

#### MySQL层面
```sql
-- 查看内存相关配置
SHOW VARIABLES LIKE '%buffer%';
SHOW VARIABLES LIKE '%cache%';
SHOW VARIABLES LIKE '%memory%';

-- 查看当前内存使用
SHOW STATUS LIKE 'Innodb_buffer_pool_%';
SHOW STATUS LIKE 'Key_%';
SHOW STATUS LIKE 'Query_cache_%';

-- 查看连接数
SHOW STATUS LIKE 'Threads_%';
SHOW STATUS LIKE 'Max_used_connections';
SHOW PROCESSLIST;
```

### 2.2 内存配置优化

#### 核心参数调优
```ini
# my.cnf 内存优化配置
[mysqld]
# InnoDB缓冲池（最重要）
innodb_buffer_pool_size = 2G  # 物理内存的70-80%
innodb_buffer_pool_instances = 8  # 大内存时分多个实例

# 连接相关
max_connections = 200
max_connect_errors = 100000
thread_cache_size = 50

# 查询缓存（MySQL 5.7及以下）
query_cache_size = 128M
query_cache_type = 1

# MyISAM键缓存
key_buffer_size = 256M

# 排序和临时表
sort_buffer_size = 2M
read_buffer_size = 1M
read_rnd_buffer_size = 2M
join_buffer_size = 2M
tmp_table_size = 64M
max_heap_table_size = 64M

# 二进制日志
binlog_cache_size = 1M
```

#### 动态内存监控脚本
```python
#!/usr/bin/env python3
# mysql_memory_monitor.py

import pymysql
import psutil
import time
import logging

class MySQLMemoryMonitor:
    def __init__(self, host='localhost', user='monitor', password='password'):
        self.connection = pymysql.connect(
            host=host, user=user, password=password,
            charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor
        )
        
    def get_mysql_memory_usage(self):
        """获取MySQL内存使用情况"""
        with self.connection.cursor() as cursor:
            # InnoDB缓冲池使用率
            cursor.execute("""
                SELECT 
                    ROUND((
                        SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_STATUS 
                        WHERE VARIABLE_NAME = 'Innodb_buffer_pool_pages_data'
                    ) * 16384 / 1024 / 1024, 2) AS buffer_pool_used_mb,
                    ROUND((
                        SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_VARIABLES 
                        WHERE VARIABLE_NAME = 'innodb_buffer_pool_size'
                    ) / 1024 / 1024, 2) AS buffer_pool_size_mb
            """)
            buffer_pool = cursor.fetchone()
            
            # 连接数统计
            cursor.execute("""
                SELECT 
                    VARIABLE_VALUE as current_connections
                FROM information_schema.GLOBAL_STATUS 
                WHERE VARIABLE_NAME = 'Threads_connected'
            """)
            connections = cursor.fetchone()
            
            return {
                'buffer_pool_used_mb': buffer_pool['buffer_pool_used_mb'],
                'buffer_pool_size_mb': buffer_pool['buffer_pool_size_mb'],
                'buffer_pool_usage_pct': round(
                    buffer_pool['buffer_pool_used_mb'] / buffer_pool['buffer_pool_size_mb'] * 100, 2
                ),
                'current_connections': connections['current_connections']
            }
    
    def get_system_memory(self):
        """获取系统内存使用情况"""
        memory = psutil.virtual_memory()
        return {
            'total_gb': round(memory.total / 1024**3, 2),
            'available_gb': round(memory.available / 1024**3, 2),
            'used_pct': memory.percent
        }
    
    def check_memory_pressure(self):
        """检查内存压力"""
        mysql_mem = self.get_mysql_memory_usage()
        sys_mem = self.get_system_memory()
        
        alerts = []
        
        # 系统内存告警
        if sys_mem['used_pct'] > 90:
            alerts.append(f"系统内存使用率过高: {sys_mem['used_pct']}%")
        
        # InnoDB缓冲池告警
        if mysql_mem['buffer_pool_usage_pct'] > 95:
            alerts.append(f"InnoDB缓冲池使用率过高: {mysql_mem['buffer_pool_usage_pct']}%")
        
        # 连接数告警
        if int(mysql_mem['current_connections']) > 150:
            alerts.append(f"MySQL连接数过多: {mysql_mem['current_connections']}")
        
        return {
            'mysql_memory': mysql_mem,
            'system_memory': sys_mem,
            'alerts': alerts
        }

if __name__ == "__main__":
    monitor = MySQLMemoryMonitor()
    
    while True:
        try:
            result = monitor.check_memory_pressure()
            
            print(f"\n=== MySQL内存监控 {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
            print(f"系统内存: {result['system_memory']['used_pct']}% 使用")
            print(f"InnoDB缓冲池: {result['mysql_memory']['buffer_pool_usage_pct']}% 使用")
            print(f"当前连接数: {result['mysql_memory']['current_connections']}")
            
            if result['alerts']:
                print("\n⚠️  告警信息:")
                for alert in result['alerts']:
                    print(f"  - {alert}")
            
            time.sleep(60)  # 每分钟检查一次
            
        except Exception as e:
            logging.error(f"监控异常: {e}")
            time.sleep(60)
```

### 2.3 OOM预防与处理

#### 预防措施
```bash
# 1. 设置MySQL内存限制（systemd）
sudo mkdir -p /etc/systemd/system/mysql.service.d/
sudo tee /etc/systemd/system/mysql.service.d/memory.conf << EOF
[Service]
MemoryLimit=4G
MemoryAccounting=yes
EOF

sudo systemctl daemon-reload
sudo systemctl restart mysql

# 2. 配置swap（谨慎使用）
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 3. 设置vm参数
echo 'vm.swappiness=1' | sudo tee -a /etc/sysctl.conf
echo 'vm.overcommit_memory=2' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

#### 应急处理脚本
```bash
#!/bin/bash
# mysql_oom_recovery.sh - MySQL OOM恢复脚本

echo "检查MySQL进程状态..."
if ! pgrep mysqld > /dev/null; then
    echo "MySQL进程不存在，尝试启动..."
    sudo systemctl start mysql
    sleep 10
fi

echo "检查内存使用情况..."
free -h

echo "清理系统缓存..."
sudo sync
sudo echo 3 > /proc/sys/vm/drop_caches

echo "检查MySQL错误日志..."
tail -50 /var/log/mysql/error.log | grep -i "out of memory\|oom"

echo "重启MySQL服务（如果需要）..."
read -p "是否重启MySQL服务？(y/N): " restart
if [[ $restart =~ ^[Yy]$ ]]; then
    sudo systemctl restart mysql
    echo "MySQL服务已重启"
fi

echo "内存恢复完成"
```

## 3. 综合监控与预警

### 3.1 Prometheus + Grafana监控

```yaml
# docker-compose.yml
version: '3.8'
services:
  mysql-exporter:
    image: prom/mysqld-exporter
    environment:
      - DATA_SOURCE_NAME=monitor:password@(mysql:3306)/
    ports:
      - "9104:9104"
    depends_on:
      - mysql
  
  prometheus:
    image: prom/prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
  
  grafana:
    image: grafana/grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
```

### 3.2 告警规则配置

```yaml
# prometheus_rules.yml
groups:
- name: mysql_disk_memory
  rules:
  - alert: MySQLDiskSpaceHigh
    expr: (mysql_global_status_innodb_data_written + mysql_global_status_innodb_data_read) > 0.9
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "MySQL磁盘空间使用率过高"
      description: "MySQL磁盘使用率超过90%"
  
  - alert: MySQLMemoryHigh
    expr: mysql_global_status_innodb_buffer_pool_pages_data / mysql_global_variables_innodb_buffer_pool_size > 0.95
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "MySQL内存使用率过高"
      description: "InnoDB缓冲池使用率超过95%"
```

## 4. 最佳实践总结

### 4.1 预防性维护

1. **定期清理**：建立数据归档和清理策略
2. **容量规划**：根据业务增长预测资源需求
3. **监控告警**：设置合理的阈值和告警机制
4. **备份策略**：确保数据安全的前提下进行优化

### 4.2 应急响应流程

1. **快速评估**：确定问题严重程度
2. **临时缓解**：采取紧急措施恢复服务
3. **根本解决**：分析根因并制定长期方案
4. **复盘改进**：总结经验并优化预防措施

### 4.3 性能优化建议

1. **硬件配置**：SSD存储、充足内存、多核CPU
2. **参数调优**：根据业务特点调整MySQL配置
3. **架构优化**：读写分离、分库分表、缓存策略
4. **代码优化**：SQL优化、索引设计、连接池管理

通过系统性的监控、预防和应急处理机制，可以有效避免和解决MySQL的磁盘空间与内存问题，确保数据库服务的稳定运行。