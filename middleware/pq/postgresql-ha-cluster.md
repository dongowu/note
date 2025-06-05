# PostgreSQL 高可用与集群技术

## 目录
- [高可用架构设计](#高可用架构设计)
- [流复制技术](#流复制技术)
- [逻辑复制](#逻辑复制)
- [故障转移与切换](#故障转移与切换)
- [负载均衡](#负载均衡)
- [分布式集群](#分布式集群)
- [监控与运维](#监控与运维)
- [Go语言集成](#go语言集成)
- [高频面试题](#高频面试题)

## 高可用架构设计

### 1. 高可用架构模式

#### 主从复制架构
```
┌─────────────────┐    WAL Stream    ┌─────────────────┐
│   Primary DB    │ ───────────────► │   Standby DB    │
│  (Read/Write)   │                  │   (Read Only)   │
└─────────────────┘                  └─────────────────┘
         │                                    │
         ▼                                    ▼
┌─────────────────┐                  ┌─────────────────┐
│  Application    │                  │   Read Queries  │
│   (Write)       │                  │                 │
└─────────────────┘                  └─────────────────┘
```

#### 主主复制架构
```
┌─────────────────┐    Logical       ┌─────────────────┐
│   Primary DB1   │ ◄──────────────► │   Primary DB2   │
│  (Read/Write)   │   Replication    │  (Read/Write)   │
└─────────────────┘                  └─────────────────┘
         │                                    │
         ▼                                    ▼
┌─────────────────┐                  ┌─────────────────┐
│  Application    │                  │  Application    │
│   Region A      │                  │   Region B      │
└─────────────────┘                  └─────────────────┘
```

#### 集群架构
```
                    ┌─────────────────┐
                    │   Load Balancer │
                    │    (HAProxy)    │
                    └─────────┬───────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
              ▼               ▼               ▼
    ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
    │   Primary DB    │ │   Standby DB1   │ │   Standby DB2   │
    │  (Read/Write)   │ │   (Read Only)   │ │   (Read Only)   │
    └─────────────────┘ └─────────────────┘ └─────────────────┘
              │               │               │
              └───────────────┼───────────────┘
                              │
                    ┌─────────▼───────┐
                    │   Shared Storage│
                    │     (Optional)  │
                    └─────────────────┘
```

### 2. RTO/RPO指标

#### 关键指标定义
- **RTO (Recovery Time Objective)**：系统恢复时间目标
- **RPO (Recovery Point Objective)**：数据恢复点目标
- **MTBF (Mean Time Between Failures)**：平均故障间隔时间
- **MTTR (Mean Time To Recovery)**：平均恢复时间

#### 不同架构的RTO/RPO
```sql
-- 同步复制：RPO = 0，RTO = 30秒-2分钟
-- 异步复制：RPO = 几秒-几分钟，RTO = 1-5分钟
-- 逻辑复制：RPO = 几秒，RTO = 5-15分钟
-- 共享存储：RPO = 0，RTO = 1-3分钟
```

## 流复制技术

### 1. 流复制原理

#### WAL流复制机制
```sql
-- 主库配置
-- postgresql.conf
wal_level = replica
max_wal_senders = 10
wal_keep_segments = 32
synchronous_standby_names = 'standby1,standby2'

-- pg_hba.conf
host replication replicator 192.168.1.0/24 md5
```

#### 复制用户创建
```sql
-- 创建复制用户
CREATE USER replicator REPLICATION LOGIN CONNECTION LIMIT 5 ENCRYPTED PASSWORD 'password';

-- 授权
GRANT CONNECT ON DATABASE postgres TO replicator;
```

### 2. 同步复制配置

#### 主库配置
```ini
# postgresql.conf

# WAL配置
wal_level = replica
max_wal_senders = 10
wal_keep_segments = 64
wal_sender_timeout = 60s

# 同步复制
synchronous_standby_names = 'FIRST 1 (standby1, standby2)'
synchronous_commit = on

# 归档配置
archive_mode = on
archive_command = 'cp %p /var/lib/postgresql/archive/%f'
```

#### 从库配置
```ini
# postgresql.conf

# 热备配置
hot_standby = on
max_standby_streaming_delay = 30s
max_standby_archive_delay = 30s
hot_standby_feedback = on

# 恢复配置
restore_command = 'cp /var/lib/postgresql/archive/%f %p'
standby_mode = on
primary_conninfo = 'host=192.168.1.10 port=5432 user=replicator password=password application_name=standby1'
```

#### recovery.conf配置
```ini
# recovery.conf (PostgreSQL < 12)
standby_mode = 'on'
primary_conninfo = 'host=192.168.1.10 port=5432 user=replicator password=password application_name=standby1'
restore_command = 'cp /var/lib/postgresql/archive/%f %p'
archive_cleanup_command = 'pg_archivecleanup /var/lib/postgresql/archive %r'
```

### 3. 异步复制配置

#### 配置差异
```ini
# 主库配置
synchronous_standby_names = ''  # 空字符串表示异步
synchronous_commit = off

# 从库配置保持不变
```

#### 复制延迟监控
```sql
-- 查看复制状态
SELECT client_addr, application_name, state, sync_state,
       pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn) AS send_lag,
       pg_wal_lsn_diff(sent_lsn, write_lsn) AS write_lag,
       pg_wal_lsn_diff(write_lsn, flush_lsn) AS flush_lag,
       pg_wal_lsn_diff(flush_lsn, replay_lsn) AS replay_lag
FROM pg_stat_replication;

-- 从库查看复制延迟
SELECT now() - pg_last_xact_replay_timestamp() AS replication_delay;
```

## 逻辑复制

### 1. 逻辑复制原理

#### 发布订阅模型
```sql
-- 发布端（Publisher）
CREATE PUBLICATION my_publication FOR TABLE users, orders;

-- 订阅端（Subscriber）
CREATE SUBSCRIPTION my_subscription 
CONNECTION 'host=publisher_host port=5432 user=replicator dbname=mydb' 
PUBLICATION my_publication;
```

#### 逻辑复制架构
```
┌─────────────────┐                  ┌─────────────────┐
│  Publisher DB   │                  │ Subscriber DB   │
│                 │                  │                 │
│ ┌─────────────┐ │    Logical       │ ┌─────────────┐ │
│ │ Publication │ │ ──────────────► │ │Subscription │ │
│ │   (users)   │ │   Replication    │ │   (users)   │ │
│ └─────────────┘ │                  │ └─────────────┘ │
│                 │                  │                 │
│ ┌─────────────┐ │                  │ ┌─────────────┐ │
│ │ Publication │ │                  │ │Subscription │ │
│ │  (orders)   │ │                  │ │  (orders)   │ │
│ └─────────────┘ │                  │ └─────────────┘ │
└─────────────────┘                  └─────────────────┘
```

### 2. 逻辑复制配置

#### 发布端配置
```sql
-- 启用逻辑复制
-- postgresql.conf
wal_level = logical
max_replication_slots = 10
max_wal_senders = 10

-- 创建发布
CREATE PUBLICATION all_tables FOR ALL TABLES;
CREATE PUBLICATION user_data FOR TABLE users, user_profiles;
CREATE PUBLICATION filtered_orders FOR TABLE orders WHERE status = 'completed';

-- 查看发布
SELECT * FROM pg_publication;
SELECT * FROM pg_publication_tables;
```

#### 订阅端配置
```sql
-- 创建订阅
CREATE SUBSCRIPTION my_sub 
CONNECTION 'host=192.168.1.10 port=5432 user=replicator dbname=sourcedb sslmode=require' 
PUBLICATION all_tables;

-- 禁用订阅
ALTER SUBSCRIPTION my_sub DISABLE;

-- 启用订阅
ALTER SUBSCRIPTION my_sub ENABLE;

-- 刷新发布
ALTER SUBSCRIPTION my_sub REFRESH PUBLICATION;

-- 删除订阅
DROP SUBSCRIPTION my_sub;

-- 查看订阅状态
SELECT * FROM pg_subscription;
SELECT * FROM pg_stat_subscription;
```

### 3. 冲突处理

#### 冲突类型
```sql
-- 主键冲突
-- 发布端：INSERT INTO users (id, name) VALUES (1, 'Alice');
-- 订阅端：INSERT INTO users (id, name) VALUES (1, 'Bob');
-- 结果：复制停止，需要手动解决

-- 更新冲突
-- 发布端：UPDATE users SET name = 'Alice Updated' WHERE id = 1;
-- 订阅端：该行不存在
-- 结果：更新被忽略

-- 删除冲突
-- 发布端：DELETE FROM users WHERE id = 1;
-- 订阅端：该行不存在
-- 结果：删除被忽略
```

#### 冲突解决
```sql
-- 查看复制错误
SELECT * FROM pg_stat_subscription;

-- 跳过冲突事务
SELECT pg_replication_origin_advance('pg_16385', '0/3000000');

-- 手动解决冲突后重启订阅
ALTER SUBSCRIPTION my_sub ENABLE;
```

## 故障转移与切换

### 1. 自动故障转移

#### Patroni集群管理
```yaml
# patroni.yml
scope: postgres-cluster
namespace: /db/
name: postgresql0

restapi:
  listen: 0.0.0.0:8008
  connect_address: 192.168.1.10:8008

etcd:
  hosts: 192.168.1.11:2379,192.168.1.12:2379,192.168.1.13:2379

bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 30
    maximum_lag_on_failover: 1048576
    postgresql:
      use_pg_rewind: true
      parameters:
        wal_level: replica
        hot_standby: "on"
        max_connections: 200
        max_wal_senders: 10
        wal_keep_segments: 8
        archive_mode: "on"
        archive_timeout: 1800s
        archive_command: mkdir -p ../wal_archive && test ! -f ../wal_archive/%f && cp %p ../wal_archive/%f
      recovery_conf:
        restore_command: cp ../wal_archive/%f %p

postgresql:
  listen: 0.0.0.0:5432
  connect_address: 192.168.1.10:5432
  data_dir: /data/postgresql0
  bin_dir: /usr/lib/postgresql/13/bin
  pgpass: /tmp/pgpass0
  authentication:
    replication:
      username: replicator
      password: rep-pass
    superuser:
      username: postgres
      password: zalando
  parameters:
    unix_socket_directories: '.'

tags:
    nofailover: false
    noloadbalance: false
    clonefrom: false
    nosync: false
```

#### 故障转移脚本
```bash
#!/bin/bash
# failover.sh

# 检查主库状态
check_primary() {
    pg_isready -h $PRIMARY_HOST -p 5432 -U postgres
    return $?
}

# 提升从库为主库
promote_standby() {
    echo "Promoting standby to primary..."
    pg_ctl promote -D $PGDATA
    
    # 等待提升完成
    sleep 5
    
    # 验证新主库状态
    if pg_isready -h localhost -p 5432 -U postgres; then
        echo "Failover completed successfully"
        # 更新应用配置
        update_application_config
    else
        echo "Failover failed"
        exit 1
    fi
}

# 更新应用配置
update_application_config() {
    # 更新DNS记录或负载均衡器配置
    # 通知应用程序新的数据库地址
    echo "Updating application configuration..."
}

# 主逻辑
if ! check_primary; then
    echo "Primary database is down, initiating failover..."
    promote_standby
else
    echo "Primary database is healthy"
fi
```

### 2. 手动切换

#### 计划内切换
```bash
# 1. 停止主库写入
psql -h primary -c "SELECT pg_switch_wal();"

# 2. 等待从库同步
psql -h standby -c "SELECT pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn();"

# 3. 停止主库
pg_ctl stop -D $PGDATA -m fast

# 4. 提升从库
pg_ctl promote -D $STANDBY_PGDATA

# 5. 重新配置原主库为从库
echo "standby_mode = 'on'" >> $PGDATA/recovery.conf
echo "primary_conninfo = 'host=new_primary port=5432 user=replicator'" >> $PGDATA/recovery.conf
pg_ctl start -D $PGDATA
```

#### 紧急切换
```bash
# 1. 立即提升从库
pg_ctl promote -D $STANDBY_PGDATA

# 2. 更新应用连接
# 修改应用配置文件或DNS记录

# 3. 检查数据一致性
psql -h new_primary -c "SELECT pg_current_wal_lsn();"
```

## 负载均衡

### 1. HAProxy配置

#### 配置文件
```ini
# haproxy.cfg
global
    maxconn 4096
    log stdout local0
    chroot /var/lib/haproxy
    stats socket /run/haproxy/admin.sock mode 660 level admin
    stats timeout 30s
    user haproxy
    group haproxy
    daemon

defaults
    mode tcp
    timeout connect 5000ms
    timeout client 50000ms
    timeout server 50000ms
    option tcplog

# PostgreSQL主库（写操作）
listen postgres_write
    bind *:5000
    option httpchk
    http-check expect status 200
    default-server inter 3s fall 3 rise 2 on-marked-down shutdown-sessions
    server postgresql_primary 192.168.1.10:5432 maxconn 100 check port 8008
    server postgresql_standby1 192.168.1.11:5432 maxconn 100 check port 8008 backup
    server postgresql_standby2 192.168.1.12:5432 maxconn 100 check port 8008 backup

# PostgreSQL从库（读操作）
listen postgres_read
    bind *:5001
    balance roundrobin
    option httpchk
    http-check expect status 200
    default-server inter 3s fall 3 rise 2
    server postgresql_standby1 192.168.1.11:5432 maxconn 100 check port 8008
    server postgresql_standby2 192.168.1.12:5432 maxconn 100 check port 8008
    server postgresql_primary 192.168.1.10:5432 maxconn 100 check port 8008 backup

# 统计页面
listen stats
    bind *:8404
    stats enable
    stats uri /stats
    stats refresh 30s
    stats admin if TRUE
```

#### 健康检查脚本
```bash
#!/bin/bash
# pg_health_check.sh

PG_HOST="$1"
PG_PORT="$2"

# 检查PostgreSQL是否可连接
if pg_isready -h "$PG_HOST" -p "$PG_PORT" -U postgres >/dev/null 2>&1; then
    # 检查是否为主库
    ROLE=$(psql -h "$PG_HOST" -p "$PG_PORT" -U postgres -t -c "SELECT CASE WHEN pg_is_in_recovery() THEN 'standby' ELSE 'primary' END;" 2>/dev/null | tr -d ' ')
    
    if [ "$ROLE" = "primary" ]; then
        echo "HTTP/1.1 200 OK"
        echo "Content-Type: text/plain"
        echo ""
        echo "Primary"
    elif [ "$ROLE" = "standby" ]; then
        echo "HTTP/1.1 206 Partial Content"
        echo "Content-Type: text/plain"
        echo ""
        echo "Standby"
    else
        echo "HTTP/1.1 503 Service Unavailable"
        echo "Content-Type: text/plain"
        echo ""
        echo "Unknown"
    fi
else
    echo "HTTP/1.1 503 Service Unavailable"
    echo "Content-Type: text/plain"
    echo ""
    echo "Down"
fi
```

### 2. PgBouncer配置

#### 连接池配置
```ini
# pgbouncer.ini
[databases]
postgres_write = host=192.168.1.10 port=5432 dbname=postgres
postgres_read = host=192.168.1.11 port=5432 dbname=postgres

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = md5
auth_file = /etc/pgbouncer/userlist.txt
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 25
min_pool_size = 5
reserve_pool_size = 5
server_reset_query = DISCARD ALL
server_check_query = SELECT 1
server_check_delay = 30
max_db_connections = 100
max_user_connections = 100
server_round_robin = 1
ignore_startup_parameters = extra_float_digits

# 日志配置
log_connections = 1
log_disconnections = 1
log_pooler_errors = 1
stats_period = 60

# 管理接口
admin_users = pgbouncer_admin
stats_users = pgbouncer_stats
```

## 分布式集群

### 1. Citus分布式扩展

#### 集群架构
```
┌─────────────────┐
│  Coordinator    │
│    Node         │
└─────────┬───────┘
          │
    ┌─────┼─────┐
    │     │     │
    ▼     ▼     ▼
┌─────┐ ┌─────┐ ┌─────┐
│Work │ │Work │ │Work │
│Node1│ │Node2│ │Node3│
└─────┘ └─────┘ └─────┘
```

#### 安装配置
```sql
-- 在协调节点安装Citus
CREATE EXTENSION citus;

-- 添加工作节点
SELECT master_add_node('worker-node-1', 5432);
SELECT master_add_node('worker-node-2', 5432);
SELECT master_add_node('worker-node-3', 5432);

-- 查看节点状态
SELECT * FROM master_get_active_worker_nodes();
```

#### 分布式表创建
```sql
-- 创建分布式表
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 分布表
SELECT create_distributed_table('users', 'id');

-- 创建引用表（小表，在所有节点复制）
CREATE TABLE countries (
    code CHAR(2) PRIMARY KEY,
    name TEXT NOT NULL
);

SELECT create_reference_table('countries');

-- 查看分布信息
SELECT * FROM pg_dist_partition;
SELECT * FROM pg_dist_shard;
```

### 2. 分片策略

#### 哈希分片
```sql
-- 基于用户ID哈希分片
SELECT create_distributed_table('users', 'user_id', 'hash');

-- 查看分片分布
SELECT 
    schemaname,
    tablename,
    shardid,
    nodename,
    nodeport
FROM pg_dist_shard_placement 
JOIN pg_dist_shard USING (shardid)
JOIN pg_dist_partition USING (logicalrelid)
WHERE logicalrelid = 'users'::regclass;
```

#### 范围分片
```sql
-- 基于时间范围分片
SELECT create_distributed_table('events', 'created_at', 'range');

-- 手动创建分片
SELECT master_create_empty_shard('events');
```

#### 分片重平衡
```sql
-- 重平衡分片
SELECT rebalance_table_shards('users');

-- 移动分片
SELECT master_move_shard_placement(
    12345,  -- shard_id
    'worker-node-1', 5432,  -- source
    'worker-node-2', 5432   -- destination
);
```

## 监控与运维

### 1. 复制监控

#### 监控脚本
```bash
#!/bin/bash
# replication_monitor.sh

PRIMARY_HOST="192.168.1.10"
STANDBY_HOSTS=("192.168.1.11" "192.168.1.12")

# 检查主库状态
check_primary() {
    echo "=== Primary Database Status ==="
    psql -h $PRIMARY_HOST -U postgres -c "
        SELECT 
            client_addr,
            application_name,
            state,
            sync_state,
            pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn) AS send_lag,
            pg_wal_lsn_diff(sent_lsn, write_lsn) AS write_lag,
            pg_wal_lsn_diff(write_lsn, flush_lsn) AS flush_lag,
            pg_wal_lsn_diff(flush_lsn, replay_lsn) AS replay_lag
        FROM pg_stat_replication;
    "
}

# 检查从库状态
check_standby() {
    local host=$1
    echo "=== Standby Database Status ($host) ==="
    
    # 检查复制延迟
    psql -h $host -U postgres -c "
        SELECT 
            CASE 
                WHEN pg_is_in_recovery() THEN 'Standby'
                ELSE 'Primary'
            END AS role,
            pg_last_wal_receive_lsn() AS receive_lsn,
            pg_last_wal_replay_lsn() AS replay_lsn,
            EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp())) AS lag_seconds;
    "
}

# 主监控逻辑
check_primary

for standby in "${STANDBY_HOSTS[@]}"; do
    check_standby $standby
done

# 检查归档状态
echo "=== Archive Status ==="
psql -h $PRIMARY_HOST -U postgres -c "
    SELECT 
        archived_count,
        last_archived_wal,
        last_archived_time,
        failed_count,
        last_failed_wal,
        last_failed_time,
        stats_reset
    FROM pg_stat_archiver;
"
```

### 2. 性能监控

#### Prometheus监控配置
```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'postgresql'
    static_configs:
      - targets: ['192.168.1.10:9187', '192.168.1.11:9187', '192.168.1.12:9187']
    scrape_interval: 5s
    metrics_path: /metrics
```

#### Grafana仪表板
```json
{
  "dashboard": {
    "title": "PostgreSQL Cluster Monitoring",
    "panels": [
      {
        "title": "Replication Lag",
        "type": "graph",
        "targets": [
          {
            "expr": "pg_stat_replication_replay_lag_seconds",
            "legendFormat": "{{application_name}}"
          }
        ]
      },
      {
        "title": "Connection Count",
        "type": "graph",
        "targets": [
          {
            "expr": "pg_stat_database_numbackends",
            "legendFormat": "{{datname}}"
          }
        ]
      },
      {
        "title": "Transaction Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(pg_stat_database_xact_commit[5m])",
            "legendFormat": "Commits/sec"
          },
          {
            "expr": "rate(pg_stat_database_xact_rollback[5m])",
            "legendFormat": "Rollbacks/sec"
          }
        ]
      }
    ]
  }
}
```

## Go语言集成

### 1. 高可用连接管理

```go
package main

import (
    "context"
    "database/sql"
    "fmt"
    "log"
    "sync"
    "time"
    
    _ "github.com/lib/pq"
)

// HAConfig 高可用配置
type HAConfig struct {
    PrimaryDSN   string
    StandbyDSNs  []string
    MaxRetries   int
    RetryDelay   time.Duration
    HealthCheck  time.Duration
}

// HAManager 高可用管理器
type HAManager struct {
    config      HAConfig
    primaryDB   *sql.DB
    standbyDBs  []*sql.DB
    currentRead int
    mu          sync.RWMutex
    healthy     map[string]bool
}

// NewHAManager 创建高可用管理器
func NewHAManager(config HAConfig) (*HAManager, error) {
    ha := &HAManager{
        config:  config,
        healthy: make(map[string]bool),
    }
    
    // 连接主库
    primaryDB, err := sql.Open("postgres", config.PrimaryDSN)
    if err != nil {
        return nil, fmt.Errorf("failed to connect to primary: %w", err)
    }
    ha.primaryDB = primaryDB
    ha.healthy[config.PrimaryDSN] = true
    
    // 连接从库
    for _, dsn := range config.StandbyDSNs {
        standbyDB, err := sql.Open("postgres", dsn)
        if err != nil {
            log.Printf("Failed to connect to standby %s: %v", dsn, err)
            ha.healthy[dsn] = false
            continue
        }
        ha.standbyDBs = append(ha.standbyDBs, standbyDB)
        ha.healthy[dsn] = true
    }
    
    // 启动健康检查
    go ha.healthChecker()
    
    return ha, nil
}

// GetWriteDB 获取写数据库连接
func (ha *HAManager) GetWriteDB() *sql.DB {
    ha.mu.RLock()
    defer ha.mu.RUnlock()
    
    if ha.healthy[ha.config.PrimaryDSN] {
        return ha.primaryDB
    }
    
    // 主库不可用，尝试故障转移
    return ha.failover()
}

// GetReadDB 获取读数据库连接
func (ha *HAManager) GetReadDB() *sql.DB {
    ha.mu.RLock()
    defer ha.mu.RUnlock()
    
    // 轮询选择健康的从库
    for i := 0; i < len(ha.standbyDBs); i++ {
        idx := (ha.currentRead + i) % len(ha.standbyDBs)
        dsn := ha.config.StandbyDSNs[idx]
        
        if ha.healthy[dsn] {
            ha.currentRead = (idx + 1) % len(ha.standbyDBs)
            return ha.standbyDBs[idx]
        }
    }
    
    // 所有从库不可用，使用主库
    if ha.healthy[ha.config.PrimaryDSN] {
        return ha.primaryDB
    }
    
    return nil
}

// ExecuteWrite 执行写操作
func (ha *HAManager) ExecuteWrite(ctx context.Context, query string, args ...interface{}) error {
    db := ha.GetWriteDB()
    if db == nil {
        return fmt.Errorf("no available write database")
    }
    
    for attempt := 0; attempt < ha.config.MaxRetries; attempt++ {
        _, err := db.ExecContext(ctx, query, args...)
        if err == nil {
            return nil
        }
        
        log.Printf("Write attempt %d failed: %v", attempt+1, err)
        
        if attempt < ha.config.MaxRetries-1 {
            time.Sleep(ha.config.RetryDelay)
            db = ha.GetWriteDB() // 重新获取连接
        }
    }
    
    return fmt.Errorf("write operation failed after %d attempts", ha.config.MaxRetries)
}

// ExecuteRead 执行读操作
func (ha *HAManager) ExecuteRead(ctx context.Context, query string, args ...interface{}) (*sql.Rows, error) {
    db := ha.GetReadDB()
    if db == nil {
        return nil, fmt.Errorf("no available read database")
    }
    
    for attempt := 0; attempt < ha.config.MaxRetries; attempt++ {
        rows, err := db.QueryContext(ctx, query, args...)
        if err == nil {
            return rows, nil
        }
        
        log.Printf("Read attempt %d failed: %v", attempt+1, err)
        
        if attempt < ha.config.MaxRetries-1 {
            time.Sleep(ha.config.RetryDelay)
            db = ha.GetReadDB() // 重新获取连接
        }
    }
    
    return nil, fmt.Errorf("read operation failed after %d attempts", ha.config.MaxRetries)
}

// healthChecker 健康检查
func (ha *HAManager) healthChecker() {
    ticker := time.NewTicker(ha.config.HealthCheck)
    defer ticker.Stop()
    
    for range ticker.C {
        ha.checkHealth()
    }
}

// checkHealth 检查数据库健康状态
func (ha *HAManager) checkHealth() {
    ha.mu.Lock()
    defer ha.mu.Unlock()
    
    // 检查主库
    ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
    defer cancel()
    
    err := ha.primaryDB.PingContext(ctx)
    ha.healthy[ha.config.PrimaryDSN] = (err == nil)
    
    // 检查从库
    for i, db := range ha.standbyDBs {
        ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
        err := db.PingContext(ctx)
        ha.healthy[ha.config.StandbyDSNs[i]] = (err == nil)
        cancel()
    }
}

// failover 故障转移
func (ha *HAManager) failover() *sql.DB {
    log.Println("Primary database is down, attempting failover...")
    
    // 在实际环境中，这里应该触发自动故障转移逻辑
    // 例如：提升从库为主库，更新DNS记录等
    
    return nil
}

// Close 关闭所有连接
func (ha *HAManager) Close() error {
    var errs []error
    
    if ha.primaryDB != nil {
        if err := ha.primaryDB.Close(); err != nil {
            errs = append(errs, err)
        }
    }
    
    for _, db := range ha.standbyDBs {
        if err := db.Close(); err != nil {
            errs = append(errs, err)
        }
    }
    
    if len(errs) > 0 {
        return fmt.Errorf("errors closing databases: %v", errs)
    }
    
    return nil
}

// 使用示例
func main() {
    config := HAConfig{
        PrimaryDSN:  "postgres://user:pass@primary:5432/db?sslmode=disable",
        StandbyDSNs: []string{
            "postgres://user:pass@standby1:5432/db?sslmode=disable",
            "postgres://user:pass@standby2:5432/db?sslmode=disable",
        },
        MaxRetries:  3,
        RetryDelay:  time.Second,
        HealthCheck: 30 * time.Second,
    }
    
    ha, err := NewHAManager(config)
    if err != nil {
        log.Fatal(err)
    }
    defer ha.Close()
    
    ctx := context.Background()
    
    // 写操作
    err = ha.ExecuteWrite(ctx, "INSERT INTO users (name, email) VALUES ($1, $2)", "Alice", "alice@example.com")
    if err != nil {
        log.Printf("Write failed: %v", err)
    }
    
    // 读操作
    rows, err := ha.ExecuteRead(ctx, "SELECT id, name, email FROM users WHERE name = $1", "Alice")
    if err != nil {
        log.Printf("Read failed: %v", err)
    } else {
        defer rows.Close()
        for rows.Next() {
            var id int
            var name, email string
            rows.Scan(&id, &name, &email)
            fmt.Printf("User: %d, %s, %s\n", id, name, email)
        }
    }
}
```

### 2. 连接池监控

```go
package main

import (
    "context"
    "database/sql"
    "encoding/json"
    "log"
    "net/http"
    "time"
    
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
    "github.com/prometheus/client_golang/prometheus/promhttp"
)

// 监控指标
var (
    dbConnections = promauto.NewGaugeVec(
        prometheus.GaugeOpts{
            Name: "postgresql_connections_total",
            Help: "Total number of database connections",
        },
        []string{"database", "state"},
    )
    
    dbQueryDuration = promauto.NewHistogramVec(
        prometheus.HistogramOpts{
            Name: "postgresql_query_duration_seconds",
            Help: "Database query duration",
            Buckets: prometheus.DefBuckets,
        },
        []string{"database", "operation"},
    )
    
    dbErrors = promauto.NewCounterVec(
        prometheus.CounterOpts{
            Name: "postgresql_errors_total",
            Help: "Total number of database errors",
        },
        []string{"database", "error_type"},
    )
)

// MonitoredDB 带监控的数据库连接
type MonitoredDB struct {
    db   *sql.DB
    name string
}

// NewMonitoredDB 创建监控数据库连接
func NewMonitoredDB(dsn, name string) (*MonitoredDB, error) {
    db, err := sql.Open("postgres", dsn)
    if err != nil {
        return nil, err
    }
    
    mdb := &MonitoredDB{
        db:   db,
        name: name,
    }
    
    // 启动监控
    go mdb.startMonitoring()
    
    return mdb, nil
}

// Query 执行查询并记录指标
func (mdb *MonitoredDB) Query(ctx context.Context, query string, args ...interface{}) (*sql.Rows, error) {
    start := time.Now()
    
    rows, err := mdb.db.QueryContext(ctx, query, args...)
    
    duration := time.Since(start)
    dbQueryDuration.WithLabelValues(mdb.name, "select").Observe(duration.Seconds())
    
    if err != nil {
        dbErrors.WithLabelValues(mdb.name, "query_error").Inc()
    }
    
    return rows, err
}

// Exec 执行命令并记录指标
func (mdb *MonitoredDB) Exec(ctx context.Context, query string, args ...interface{}) (sql.Result, error) {
    start := time.Now()
    
    result, err := mdb.db.ExecContext(ctx, query, args...)
    
    duration := time.Since(start)
    dbQueryDuration.WithLabelValues(mdb.name, "exec").Observe(duration.Seconds())
    
    if err != nil {
        dbErrors.WithLabelValues(mdb.name, "exec_error").Inc()
    }
    
    return result, err
}

// startMonitoring 启动连接池监控
func (mdb *MonitoredDB) startMonitoring() {
    ticker := time.NewTicker(30 * time.Second)
    defer ticker.Stop()
    
    for range ticker.C {
        stats := mdb.db.Stats()
        
        dbConnections.WithLabelValues(mdb.name, "open").Set(float64(stats.OpenConnections))
        dbConnections.WithLabelValues(mdb.name, "in_use").Set(float64(stats.InUse))
        dbConnections.WithLabelValues(mdb.name, "idle").Set(float64(stats.Idle))
    }
}

// HealthStatus 健康状态
type HealthStatus struct {
    Database  string    `json:"database"`
    Status    string    `json:"status"`
    Timestamp time.Time `json:"timestamp"`
    Stats     sql.DBStats `json:"stats"`
}

// HealthCheck 健康检查端点
func (mdb *MonitoredDB) HealthCheck(w http.ResponseWriter, r *http.Request) {
    ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
    defer cancel()
    
    status := HealthStatus{
        Database:  mdb.name,
        Timestamp: time.Now(),
        Stats:     mdb.db.Stats(),
    }
    
    err := mdb.db.PingContext(ctx)
    if err != nil {
        status.Status = "unhealthy"
        w.WriteHeader(http.StatusServiceUnavailable)
    } else {
        status.Status = "healthy"
        w.WriteHeader(http.StatusOK)
    }
    
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(status)
}

// 启动监控服务
func startMonitoringServer() {
    http.Handle("/metrics", promhttp.Handler())
    
    log.Println("Starting monitoring server on :8080")
    log.Fatal(http.ListenAndServe(":8080", nil))
}
```

## 高频面试题

### 1. 架构设计类

**Q: 如何设计一个支持99.99%可用性的PostgreSQL架构？**

A: 高可用架构设计要点：

1. **多层冗余**：
   - 主从复制：1主2从配置
   - 同步复制确保数据一致性
   - 异地备份防止区域性故障

2. **自动故障转移**：
   - 使用Patroni或类似工具
   - 健康检查间隔≤30秒
   - 故障转移时间≤2分钟

3. **负载均衡**：
   - HAProxy进行读写分离
   - 连接池管理（PgBouncer）
   - 应用层连接重试机制

4. **监控告警**：
   - 实时监控复制延迟
   - 连接数、性能指标监控
   - 自动化运维脚本

**Q: PostgreSQL流复制和逻辑复制的区别？**

A: 主要区别对比：

| 特性 | 流复制 | 逻辑复制 |
|------|--------|----------|
| 复制级别 | 物理（WAL） | 逻辑（SQL） |
| 版本要求 | 相同版本 | 可跨版本 |
| 表结构 | 完全相同 | 可不同 |
| 复制粒度 | 整个集群 | 表级别 |
| 冲突处理 | 无冲突 | 需处理冲突 |
| 性能开销 | 较低 | 较高 |
| 双向复制 | 不支持 | 支持 |

### 2. 故障处理类

**Q: 主库宕机时如何进行故障转移？**

A: 故障转移步骤：

1. **检测故障**：
   - 健康检查失败
   - 连接超时
   - 复制中断

2. **选择新主库**：
   - 选择延迟最小的从库
   - 确保数据完整性
   - 避免脑裂问题

3. **提升从库**：
```bash
# 停止从库复制
pg_ctl promote -D $PGDATA

# 等待提升完成
while pg_is_in_recovery(); do sleep 1; done
```

4. **更新配置**：
   - 修改应用连接字符串
   - 更新DNS记录
   - 重新配置其他从库

5. **验证切换**：
   - 测试读写操作
   - 检查复制状态
   - 监控性能指标

**Q: 如何处理复制延迟过大的问题？**

A: 复制延迟优化方案：

1. **网络优化**：
   - 增加网络带宽
   - 减少网络延迟
   - 使用专用网络连接

2. **配置调优**：
```ini
# 增加WAL发送缓冲区
wal_sender_timeout = 0
wal_receiver_timeout = 0

# 调整复制相关参数
max_wal_senders = 10
wal_keep_segments = 128
```

3. **硬件升级**：
   - 使用SSD存储
   - 增加内存容量
   - 提升CPU性能

4. **应用优化**：
   - 减少大事务
   - 批量操作优化
   - 避免长时间锁定

### 3. 性能优化类

**Q: 如何优化PostgreSQL集群的读性能？**

A: 读性能优化策略：

1. **读写分离**：
   - 读操作路由到从库
   - 负载均衡分发请求
   - 连接池管理

2. **索引优化**：
   - 为查询字段创建索引
   - 使用复合索引
   - 定期维护索引

3. **缓存策略**：
   - 应用层缓存
   - Redis缓存热点数据
   - 查询结果缓存

4. **分片策略**：
   - 水平分片
   - 垂直分片
   - 使用Citus扩展

**Q: 如何监控PostgreSQL集群的健康状态？**

A: 监控体系建设：

1. **基础监控**：
```sql
-- 复制状态监控
SELECT * FROM pg_stat_replication;

-- 连接数监控
SELECT count(*), state FROM pg_stat_activity GROUP BY state;

-- 锁等待监控
SELECT * FROM pg_locks WHERE NOT granted;
```

2. **性能监控**：
   - 查询性能（pg_stat_statements）
   - 缓存命中率
   - I/O统计信息

3. **告警机制**：
   - 复制延迟告警
   - 连接数告警
   - 磁盘空间告警

4. **可视化监控**：
   - Grafana仪表板
   - Prometheus指标收集
   - 自定义监控脚本

### 4. 运维管理类

**Q: 如何进行PostgreSQL集群的在线扩容？**

A: 在线扩容方案：

1. **垂直扩容**：
   - 增加CPU、内存
   - 升级存储性能
   - 调整配置参数

2. **水平扩容**：
   - 添加新的从库节点
   - 配置流复制
   - 更新负载均衡配置

3. **分片扩容**：
```sql
-- 添加新的工作节点
SELECT master_add_node('new-worker', 5432);

-- 重平衡分片
SELECT rebalance_table_shards('large_table');
```

4. **扩容验证**：
   - 测试新节点功能
   - 验证数据一致性
   - 监控性能指标

**Q: 如何保证PostgreSQL集群的数据一致性？**

A: 数据一致性保证措施：

1. **同步复制**：
```ini
synchronous_standby_names = 'FIRST 1 (standby1, standby2)'
synchronous_commit = on
```

2. **事务管理**：
   - 使用适当的隔离级别
   - 避免长事务
   - 合理使用锁机制

3. **一致性检查**：
```sql
-- 检查数据一致性
SELECT pg_current_wal_lsn() AS primary_lsn;
SELECT pg_last_wal_replay_lsn() AS standby_lsn;
```

4. **备份验证**：
   - 定期备份测试
   - 数据校验脚本
   - 恢复演练

## 总结

PostgreSQL高可用与集群技术是构建企业级数据库系统的核心。通过合理的架构设计、完善的监控体系、自动化的故障转移机制，可以实现高可用性和高性能的数据库服务。在Go语言环境下，结合连接池管理、健康检查、监控集成等技术，能够构建稳定可靠的数据库访问层。