# Redis生产实战 - 高级/资深专家视角

## 一、性能调优案例：大促期间QPS从5万提升到50万

### 1.1 背景与挑战
某电商平台在双11大促期间，Redis集群面临巨大压力：
- **初始状态**：QPS 5万，响应时间P99 50ms
- **目标要求**：QPS 50万，响应时间P99 < 10ms
- **核心挑战**：热点商品缓存、库存扣减、用户会话管理

### 1.2 性能瓶颈分析

#### 1.2.1 热点Key问题
```bash
# 通过redis-cli --hotkeys分析热点key
redis-cli --hotkeys -i 0.1
# 发现商品ID为12345的key占用30%流量
```

**问题表现**：
- 单个商品缓存key被高频访问（QPS 1.5万）
- 导致单个Redis节点CPU 100%，其他节点闲置
- 网络带宽打满，响应时间激增

**解决方案**：
```python
# 热点key分片策略
def get_product_cache(product_id, shard_count=10):
    shard_key = f"product:{product_id}:shard:{hash(product_id) % shard_count}"
    return redis_client.get(shard_key)

# 本地缓存 + Redis多级缓存
from functools import lru_cache

@lru_cache(maxsize=1000)
def get_hot_product(product_id):
    # 本地缓存热点商品，TTL 30秒
    return redis_client.get(f"product:{product_id}")
```

#### 1.2.2 大Key问题
```bash
# 使用redis-cli --bigkeys扫描大key
redis-cli --bigkeys -i 0.1
# 发现购物车hash key达到10MB
```

**优化策略**：
```python
# 购物车分桶存储
def set_cart_item(user_id, item_id, quantity):
    bucket = hash(item_id) % 100
    cart_key = f"cart:{user_id}:bucket:{bucket}"
    redis_client.hset(cart_key, item_id, quantity)
    redis_client.expire(cart_key, 3600)

# 商品详情分字段存储
def cache_product_detail(product_id, product_data):
    pipe = redis_client.pipeline()
    for field, value in product_data.items():
        pipe.set(f"product:{product_id}:{field}", value, ex=1800)
    pipe.execute()
```

#### 1.2.3 网络优化
```python
# Pipeline批量操作
def batch_get_products(product_ids):
    pipe = redis_client.pipeline()
    for pid in product_ids:
        pipe.get(f"product:{pid}")
    return pipe.execute()

# 连接池优化
import redis
pool = redis.ConnectionPool(
    host='redis-cluster',
    port=6379,
    max_connections=200,  # 增加连接池大小
    socket_keepalive=True,
    socket_keepalive_options={},
    health_check_interval=30
)
redis_client = redis.Redis(connection_pool=pool)
```

### 1.3 架构优化

#### 1.3.1 读写分离架构
```yaml
# docker-compose.yml
version: '3.8'
services:
  redis-master:
    image: redis:7.0
    command: redis-server --appendonly yes --replica-read-only no
    ports:
      - "6379:6379"
    
  redis-slave-1:
    image: redis:7.0
    command: redis-server --replicaof redis-master 6379 --replica-read-only yes
    depends_on:
      - redis-master
      
  redis-slave-2:
    image: redis:7.0
    command: redis-server --replicaof redis-master 6379 --replica-read-only yes
    depends_on:
      - redis-master
```

```python
# 读写分离客户端
class RedisReadWriteClient:
    def __init__(self):
        self.master = redis.Redis(host='redis-master', port=6379)
        self.slaves = [
            redis.Redis(host='redis-slave-1', port=6379),
            redis.Redis(host='redis-slave-2', port=6379)
        ]
        self.slave_index = 0
    
    def get_slave(self):
        # 轮询选择从节点
        slave = self.slaves[self.slave_index]
        self.slave_index = (self.slave_index + 1) % len(self.slaves)
        return slave
    
    def get(self, key):
        return self.get_slave().get(key)
    
    def set(self, key, value, **kwargs):
        return self.master.set(key, value, **kwargs)
```

#### 1.3.2 集群分片策略
```bash
# Redis Cluster配置
# 6个节点：3主3从
redis-cli --cluster create \
  192.168.1.10:7000 192.168.1.11:7000 192.168.1.12:7000 \
  192.168.1.10:7001 192.168.1.11:7001 192.168.1.12:7001 \
  --cluster-replicas 1
```

```python
# 一致性哈希客户端
from rediscluster import RedisCluster

startup_nodes = [
    {"host": "192.168.1.10", "port": "7000"},
    {"host": "192.168.1.11", "port": "7000"},
    {"host": "192.168.1.12", "port": "7000"}
]

rc = RedisCluster(
    startup_nodes=startup_nodes,
    decode_responses=True,
    max_connections=32,
    health_check_interval=30
)
```

### 1.4 内存优化

#### 1.4.1 数据结构优化
```python
# 使用压缩列表优化小hash
# redis.conf配置
# hash-max-ziplist-entries 512
# hash-max-ziplist-value 64

# 商品属性压缩存储
def cache_product_attrs(product_id, attrs):
    # 小于64字节的属性使用hash压缩存储
    if len(str(attrs)) < 64:
        redis_client.hmset(f"product:{product_id}:attrs", attrs)
    else:
        # 大属性使用string + json
        redis_client.set(f"product:{product_id}:attrs", json.dumps(attrs))
```

#### 1.4.2 过期策略优化
```python
# 分层过期策略
class CacheManager:
    def __init__(self):
        self.redis = redis_client
    
    def set_with_smart_ttl(self, key, value, base_ttl=3600):
        # 根据key类型设置不同TTL
        if key.startswith('hot:'):
            ttl = base_ttl * 2  # 热点数据延长TTL
        elif key.startswith('temp:'):
            ttl = base_ttl // 6  # 临时数据缩短TTL
        else:
            ttl = base_ttl
        
        # 添加随机抖动，避免缓存雪崩
        import random
        ttl += random.randint(-ttl//10, ttl//10)
        
        return self.redis.setex(key, ttl, value)
```

### 1.5 最终效果
- **QPS提升**：5万 → 50万（10倍提升）
- **响应时间**：P99 50ms → 8ms（6倍优化）
- **内存使用**：优化30%，碎片率从45%降至15%
- **CPU使用**：单节点100% → 集群平均60%

## 二、故障诊断工具：redis-cli与redis-benchmark实战

### 2.1 redis-cli诊断工具集

#### 2.1.1 实时监控命令
```bash
# 实时监控所有命令
redis-cli monitor
# 输出示例：
# 1635724800.123456 [0 127.0.0.1:54321] "GET" "user:12345"
# 1635724800.234567 [0 127.0.0.1:54322] "HSET" "cart:67890" "item1" "5"

# 实时统计信息
redis-cli --stat
# 输出：
# ------- data ------ --------------------- load -------------------- - child -
# keys       mem      clients blocked requests            connections
# 1000000    2.50G    150     0       1000000 (+1000)     1500

# 延迟监控
redis-cli --latency -i 1
# 输出：
# min: 0, max: 15, avg: 2.50 (1000 samples)

# 延迟历史
redis-cli --latency-history -i 1
```

#### 2.1.2 内存分析工具
```bash
# 大key扫描
redis-cli --bigkeys -i 0.1
# 输出示例：
# Biggest string found 'product:12345' has 1048576 bytes
# Biggest hash found 'user:session:67890' has 5000 fields

# 热点key分析
redis-cli --hotkeys -i 0.1
# 需要开启maxmemory-policy allkeys-lfu

# 内存使用分析
redis-cli --memkeys -a password
# 按key模式分析内存使用

# 扫描特定模式的key
redis-cli --scan --pattern "user:*" | head -100
```

#### 2.1.3 集群诊断
```bash
# 集群节点信息
redis-cli -c cluster nodes
# 输出：
# 07c37dfeb235213a872192d90877d0cd55635b91 127.0.0.1:30004@31004 slave e7d1eecce10fd6bb5eb35b9f99a514335d9ba9ca 0 1426238317239 4 connected

# 集群状态检查
redis-cli -c cluster info
# cluster_state:ok
# cluster_slots_assigned:16384
# cluster_slots_ok:16384
# cluster_slots_pfail:0
# cluster_slots_fail:0

# 集群slot分布
redis-cli cluster slots

# 集群修复
redis-cli --cluster fix 127.0.0.1:7000
```

### 2.2 故障诊断实战案例

#### 2.2.1 案例1：突发延迟飙升
**现象**：应用响应时间从5ms突增至500ms

**诊断过程**：
```bash
# 1. 检查延迟
redis-cli --latency-history -i 1
# 发现延迟波动很大：min: 1, max: 2000, avg: 200

# 2. 检查慢查询
redis-cli slowlog get 10
# 发现大量HGETALL命令耗时超过100ms

# 3. 检查大key
redis-cli --bigkeys
# 发现hash key 'user:session:12345' 有50000个字段

# 4. 分析具体key
redis-cli hlen user:session:12345
# (integer) 50000
redis-cli memory usage user:session:12345
# (integer) 5242880  # 5MB
```

**解决方案**：
```python
# 拆分大hash为多个小hash
def migrate_large_session(user_id):
    old_key = f"user:session:{user_id}"
    session_data = redis_client.hgetall(old_key)
    
    # 按100个字段一组拆分
    batch_size = 100
    for i in range(0, len(session_data), batch_size):
        batch_key = f"user:session:{user_id}:batch:{i//batch_size}"
        batch_data = dict(list(session_data.items())[i:i+batch_size])
        redis_client.hmset(batch_key, batch_data)
        redis_client.expire(batch_key, 3600)
    
    # 删除原key
    redis_client.delete(old_key)
```

#### 2.2.2 案例2：内存使用异常
**现象**：Redis内存使用率90%，但业务数据量没有明显增长

**诊断过程**：
```bash
# 1. 检查内存信息
redis-cli info memory
# used_memory:8589934592  # 8GB
# used_memory_rss:12884901888  # 12GB
# mem_fragmentation_ratio:1.50  # 碎片率50%

# 2. 检查key分布
redis-cli --bigkeys
# 发现大量临时key没有设置过期时间

# 3. 扫描无TTL的key
redis-cli --scan | xargs -I {} redis-cli ttl {} | grep -c "^-1$"
# 发现100万个key没有过期时间

# 4. 分析key模式
redis-cli --scan --pattern "temp:*" | wc -l
# 500000个临时key
```

**解决方案**：
```bash
# 批量设置过期时间
redis-cli --scan --pattern "temp:*" | xargs -I {} redis-cli expire {} 3600

# 内存碎片整理（Redis 4.0+）
redis-cli memory purge

# 或者重启Redis（生产环境需谨慎）
```

### 2.3 redis-benchmark性能测试

#### 2.3.1 基础性能测试
```bash
# 基础读写测试
redis-benchmark -h 127.0.0.1 -p 6379 -c 100 -n 100000
# -c: 并发连接数
# -n: 总请求数

# 输出示例：
# SET: 85470.09 requests per second
# GET: 89285.71 requests per second
# INCR: 86956.52 requests per second

# 指定测试命令
redis-benchmark -t set,get -n 100000 -q
# SET: 85470.09 requests per second
# GET: 89285.71 requests per second

# 测试特定数据大小
redis-benchmark -t set -n 100000 -d 1024
# 测试1KB数据的SET性能
```

#### 2.3.2 高级性能测试
```bash
# Pipeline测试
redis-benchmark -t set -n 100000 -P 16
# 使用16个命令的pipeline

# 随机key测试
redis-benchmark -t set -r 100000 -n 1000000
# -r: 随机key范围

# 集群测试
redis-benchmark -h 127.0.0.1 -p 7000 -c 100 -n 100000 --cluster

# 自定义Lua脚本测试
cat > test_script.lua << EOF
local key = KEYS[1]
local value = ARGV[1]
redis.call('set', key, value)
return redis.call('get', key)
EOF

redis-benchmark -n 100000 script load "$(cat test_script.lua)"
```

#### 2.3.3 压力测试与容量规划
```bash
# 极限QPS测试
redis-benchmark -h 127.0.0.1 -p 6379 -c 1000 -n 10000000 -t get,set -q
# 测试1000并发下的极限QPS

# 内存压力测试
redis-benchmark -h 127.0.0.1 -p 6379 -c 100 -n 1000000 -d 10240 -t set
# 测试10KB数据的内存压力

# 网络带宽测试
redis-benchmark -h 127.0.0.1 -p 6379 -c 100 -n 100000 -d 102400 -t set
# 测试100KB数据的网络带宽
```

## 三、监控告警：Prometheus + Grafana完整方案

### 3.1 Redis Exporter部署

#### 3.1.1 Docker部署方式
```yaml
# docker-compose.yml
version: '3.8'
services:
  redis-exporter:
    image: oliver006/redis_exporter:latest
    ports:
      - "9121:9121"
    environment:
      REDIS_ADDR: "redis://redis-server:6379"
      REDIS_PASSWORD: "your_password"
    command:
      - '--redis.addr=redis://redis-server:6379'
      - '--redis.password=your_password'
      - '--include-system-metrics'
      - '--check-keys=hot:*,user:*,product:*'
    depends_on:
      - redis-server
      
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/etc/prometheus/console_libraries'
      - '--web.console.templates=/etc/prometheus/consoles'
      - '--storage.tsdb.retention.time=200h'
      - '--web.enable-lifecycle'
      
  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana-storage:/var/lib/grafana
      - ./grafana/dashboards:/etc/grafana/provisioning/dashboards
      - ./grafana/datasources:/etc/grafana/provisioning/datasources

volumes:
  grafana-storage:
```

#### 3.1.2 Prometheus配置
```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - "redis_rules.yml"

scrape_configs:
  - job_name: 'redis'
    static_configs:
      - targets: ['redis-exporter:9121']
    scrape_interval: 5s
    metrics_path: /metrics
    
  - job_name: 'redis-cluster'
    static_configs:
      - targets: 
        - 'redis-exporter-1:9121'
        - 'redis-exporter-2:9121'
        - 'redis-exporter-3:9121'
    scrape_interval: 5s

alerting:
  alertmanagers:
    - static_configs:
        - targets:
          - alertmanager:9093
```

### 3.2 核心监控指标

#### 3.2.1 性能指标
```yaml
# redis_rules.yml
groups:
- name: redis_performance
  rules:
  # QPS监控
  - alert: RedisHighQPS
    expr: rate(redis_commands_processed_total[5m]) > 50000
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "Redis QPS过高"
      description: "Redis实例 {{ $labels.instance }} QPS达到 {{ $value }}/s"
      
  # 响应时间监控
  - alert: RedisHighLatency
    expr: redis_slowlog_length > 100
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Redis响应时间过高"
      description: "Redis实例 {{ $labels.instance }} 慢查询数量: {{ $value }}"
      
  # 连接数监控
  - alert: RedisHighConnections
    expr: redis_connected_clients / redis_config_maxclients > 0.8
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "Redis连接数过高"
      description: "Redis连接使用率: {{ $value | humanizePercentage }}"
```

#### 3.2.2 内存指标
```yaml
- name: redis_memory
  rules:
  # 内存使用率
  - alert: RedisHighMemoryUsage
    expr: redis_memory_used_bytes / redis_memory_max_bytes > 0.85
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "Redis内存使用率过高"
      description: "内存使用率: {{ $value | humanizePercentage }}"
      
  # 内存碎片率
  - alert: RedisHighMemoryFragmentation
    expr: redis_memory_fragmentation_ratio > 1.5
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Redis内存碎片率过高"
      description: "内存碎片率: {{ $value }}"
      
  # 大key监控
  - alert: RedisBigKeys
    expr: redis_key_size_bytes > 10485760  # 10MB
    for: 1m
    labels:
      severity: warning
    annotations:
      summary: "发现Redis大key"
      description: "Key {{ $labels.key }} 大小: {{ $value | humanizeBytes }}"
```

#### 3.2.3 可用性指标
```yaml
- name: redis_availability
  rules:
  # 主从同步延迟
  - alert: RedisReplicationLag
    expr: redis_master_repl_offset - redis_slave_repl_offset > 1000000
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Redis主从同步延迟"
      description: "同步延迟: {{ $value }} bytes"
      
  # 实例下线
  - alert: RedisInstanceDown
    expr: up{job="redis"} == 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Redis实例下线"
      description: "Redis实例 {{ $labels.instance }} 无法访问"
      
  # 集群节点故障
  - alert: RedisClusterNodeFail
    expr: redis_cluster_nodes{state!="ok"} > 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Redis集群节点故障"
      description: "集群节点 {{ $labels.node }} 状态异常: {{ $labels.state }}"
```

### 3.3 Grafana仪表板配置

#### 3.3.1 数据源配置
```yaml
# grafana/datasources/prometheus.yml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: true
```

#### 3.3.2 核心仪表板JSON
```json
{
  "dashboard": {
    "id": null,
    "title": "Redis监控仪表板",
    "tags": ["redis"],
    "timezone": "browser",
    "panels": [
      {
        "id": 1,
        "title": "QPS",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(redis_commands_processed_total[5m])",
            "legendFormat": "{{instance}} QPS"
          }
        ],
        "yAxes": [
          {
            "label": "requests/sec",
            "min": 0
          }
        ],
        "alert": {
          "conditions": [
            {
              "query": {
                "queryType": "",
                "refId": "A"
              },
              "reducer": {
                "type": "last",
                "params": []
              },
              "evaluator": {
                "params": [50000],
                "type": "gt"
              }
            }
          ],
          "executionErrorState": "alerting",
          "for": "2m",
          "frequency": "10s",
          "handler": 1,
          "name": "QPS过高告警",
          "noDataState": "no_data",
          "notifications": []
        }
      },
      {
        "id": 2,
        "title": "内存使用",
        "type": "singlestat",
        "targets": [
          {
            "expr": "redis_memory_used_bytes / redis_memory_max_bytes * 100",
            "legendFormat": "内存使用率"
          }
        ],
        "valueName": "current",
        "format": "percent",
        "thresholds": "70,85",
        "colorBackground": true
      },
      {
        "id": 3,
        "title": "连接数",
        "type": "graph",
        "targets": [
          {
            "expr": "redis_connected_clients",
            "legendFormat": "{{instance}} 连接数"
          }
        ]
      },
      {
        "id": 4,
        "title": "慢查询",
        "type": "graph",
        "targets": [
          {
            "expr": "redis_slowlog_length",
            "legendFormat": "{{instance}} 慢查询数量"
          }
        ]
      },
      {
        "id": 5,
        "title": "主从延迟",
        "type": "graph",
        "targets": [
          {
            "expr": "redis_master_repl_offset - redis_slave_repl_offset",
            "legendFormat": "{{instance}} 同步延迟"
          }
        ]
      },
      {
        "id": 6,
        "title": "热点Key Top 10",
        "type": "table",
        "targets": [
          {
            "expr": "topk(10, redis_key_hits_total)",
            "format": "table",
            "instant": true
          }
        ],
        "columns": [
          {
            "text": "Key",
            "value": "key"
          },
          {
            "text": "访问次数",
            "value": "Value"
          }
        ]
      }
    ],
    "time": {
      "from": "now-1h",
      "to": "now"
    },
    "refresh": "5s"
  }
}
```

### 3.4 告警通知配置

#### 3.4.1 AlertManager配置
```yaml
# alertmanager.yml
global:
  smtp_smarthost: 'smtp.company.com:587'
  smtp_from: 'alerts@company.com'
  smtp_auth_username: 'alerts@company.com'
  smtp_auth_password: 'password'

route:
  group_by: ['alertname']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h
  receiver: 'web.hook'
  routes:
  - match:
      severity: critical
    receiver: 'critical-alerts'
  - match:
      severity: warning
    receiver: 'warning-alerts'

receivers:
- name: 'web.hook'
  webhook_configs:
  - url: 'http://webhook-server:5000/alerts'
    
- name: 'critical-alerts'
  email_configs:
  - to: 'oncall@company.com'
    subject: '[CRITICAL] Redis告警'
    body: |
      {{ range .Alerts }}
      告警: {{ .Annotations.summary }}
      描述: {{ .Annotations.description }}
      时间: {{ .StartsAt }}
      {{ end }}
  webhook_configs:
  - url: 'http://webhook-server:5000/critical'
    
- name: 'warning-alerts'
  email_configs:
  - to: 'team@company.com'
    subject: '[WARNING] Redis告警'
    body: |
      {{ range .Alerts }}
      告警: {{ .Annotations.summary }}
      描述: {{ .Annotations.description }}
      {{ end }}
```

#### 3.4.2 钉钉/企业微信集成
```python
# webhook_server.py
from flask import Flask, request
import requests
import json

app = Flask(__name__)

# 钉钉机器人webhook
DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN"

@app.route('/alerts', methods=['POST'])
def handle_alerts():
    alerts = request.json.get('alerts', [])
    
    for alert in alerts:
        if alert['status'] == 'firing':
            send_dingtalk_alert(alert)
    
    return 'OK'

def send_dingtalk_alert(alert):
    message = {
        "msgtype": "markdown",
        "markdown": {
            "title": "Redis告警",
            "text": f"""
### {alert['labels']['severity'].upper()} - Redis告警

**告警名称**: {alert['labels']['alertname']}

**实例**: {alert['labels']['instance']}

**描述**: {alert['annotations']['description']}

**时间**: {alert['startsAt']}

**详情**: [查看Grafana](http://grafana.company.com)
            """
        }
    }
    
    requests.post(DINGTALK_WEBHOOK, json=message)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
```

## 四、生产配置：主从复制、哨兵模式、集群模式

### 4.1 主从复制配置

#### 4.1.1 主节点配置
```bash
# redis-master.conf
# 基础配置
port 6379
bind 0.0.0.0
protected-mode yes
requirepass "StrongPassword123!"
masterauth "StrongPassword123!"

# 内存配置
maxmemory 8gb
maxmemory-policy allkeys-lru

# 持久化配置
save 900 1
save 300 10
save 60 10000
rdbcompression yes
rdbchecksum yes
dbfilename dump.rdb
dir /data/redis

# AOF配置
appendonly yes
appendfilename "appendonly.aof"
appendfsync everysec
no-appendfsync-on-rewrite no
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb
aof-use-rdb-preamble yes

# 复制配置
repl-diskless-sync no
repl-diskless-sync-delay 5
repl-ping-slave-period 10
repl-timeout 60
repl-disable-tcp-nodelay no
repl-backlog-size 1mb
repl-backlog-ttl 3600

# 客户端配置
maxclients 10000
tcp-keepalive 300
tcp-backlog 511
timeout 0

# 慢查询配置
slowlog-log-slower-than 10000
slowlog-max-len 128

# 安全配置
rename-command FLUSHDB ""
rename-command FLUSHALL ""
rename-command KEYS ""
rename-command CONFIG "CONFIG_9a8b7c6d5e4f"
```

#### 4.1.2 从节点配置
```bash
# redis-slave.conf
# 继承主节点配置
include /etc/redis/redis-master.conf

# 从节点特定配置
port 6380
replicaof 192.168.1.10 6379
replica-read-only yes
replica-serve-stale-data yes
replica-priority 100

# 从节点不需要持久化（可选）
save ""
appendonly no

# 日志配置
logfile /var/log/redis/redis-slave.log
loglevel notice
```

#### 4.1.3 Docker Compose部署
```yaml
# docker-compose-replication.yml
version: '3.8'
services:
  redis-master:
    image: redis:7.0-alpine
    container_name: redis-master
    ports:
      - "6379:6379"
    volumes:
      - ./redis-master.conf:/usr/local/etc/redis/redis.conf
      - redis-master-data:/data
    command: redis-server /usr/local/etc/redis/redis.conf
    networks:
      - redis-network
    restart: unless-stopped
    
  redis-slave-1:
    image: redis:7.0-alpine
    container_name: redis-slave-1
    ports:
      - "6380:6379"
    volumes:
      - ./redis-slave.conf:/usr/local/etc/redis/redis.conf
      - redis-slave-1-data:/data
    command: redis-server /usr/local/etc/redis/redis.conf
    depends_on:
      - redis-master
    networks:
      - redis-network
    restart: unless-stopped
    
  redis-slave-2:
    image: redis:7.0-alpine
    container_name: redis-slave-2
    ports:
      - "6381:6379"
    volumes:
      - ./redis-slave.conf:/usr/local/etc/redis/redis.conf
      - redis-slave-2-data:/data
    command: redis-server /usr/local/etc/redis/redis.conf
    depends_on:
      - redis-master
    networks:
      - redis-network
    restart: unless-stopped

volumes:
  redis-master-data:
  redis-slave-1-data:
  redis-slave-2-data:

networks:
  redis-network:
    driver: bridge
```

### 4.2 哨兵模式配置

#### 4.2.1 哨兵配置文件
```bash
# sentinel.conf
port 26379
bind 0.0.0.0
protected-mode no

# 监控主节点
sentinel monitor mymaster 192.168.1.10 6379 2
sentinel auth-pass mymaster StrongPassword123!

# 故障检测配置
sentinel down-after-milliseconds mymaster 5000
sentinel parallel-syncs mymaster 1
sentinel failover-timeout mymaster 10000

# 通知脚本
sentinel notification-script mymaster /scripts/notify.sh
sentinel client-reconfig-script mymaster /scripts/reconfig.sh

# 日志配置
logfile /var/log/redis/sentinel.log
loglevel notice

# 工作目录
dir /tmp
```

#### 4.2.2 哨兵集群部署
```yaml
# docker-compose-sentinel.yml
version: '3.8'
services:
  # Redis主从节点（复用上面的配置）
  redis-master:
    # ... 同上
    
  redis-slave-1:
    # ... 同上
    
  redis-slave-2:
    # ... 同上
    
  # 哨兵节点
  sentinel-1:
    image: redis:7.0-alpine
    container_name: sentinel-1
    ports:
      - "26379:26379"
    volumes:
      - ./sentinel.conf:/usr/local/etc/redis/sentinel.conf
      - ./scripts:/scripts
    command: redis-sentinel /usr/local/etc/redis/sentinel.conf
    depends_on:
      - redis-master
      - redis-slave-1
      - redis-slave-2
    networks:
      - redis-network
    restart: unless-stopped
    
  sentinel-2:
    image: redis:7.0-alpine
    container_name: sentinel-2
    ports:
      - "26380:26379"
    volumes:
      - ./sentinel.conf:/usr/local/etc/redis/sentinel.conf
      - ./scripts:/scripts
    command: redis-sentinel /usr/local/etc/redis/sentinel.conf
    depends_on:
      - redis-master
      - redis-slave-1
      - redis-slave-2
    networks:
      - redis-network
    restart: unless-stopped
    
  sentinel-3:
    image: redis:7.0-alpine
    container_name: sentinel-3
    ports:
      - "26381:26379"
    volumes:
      - ./sentinel.conf:/usr/local/etc/redis/sentinel.conf
      - ./scripts:/scripts
    command: redis-sentinel /usr/local/etc/redis/sentinel.conf
    depends_on:
      - redis-master
      - redis-slave-1
      - redis-slave-2
    networks:
      - redis-network
    restart: unless-stopped

networks:
  redis-network:
    driver: bridge
```

#### 4.2.3 故障转移脚本
```bash
#!/bin/bash
# notify.sh - 哨兵通知脚本

EVENT_TYPE=$1
EVENT_NAME=$2
MASTER_NAME=$3
MASTER_IP=$4
MASTER_PORT=$5

case $EVENT_TYPE in
    "+sdown")
        echo "$(date): Master $MASTER_NAME ($MASTER_IP:$MASTER_PORT) is subjectively down" >> /var/log/redis/sentinel-events.log
        # 发送告警
        curl -X POST "http://alertmanager:9093/api/v1/alerts" \
             -H "Content-Type: application/json" \
             -d '[{
                "labels": {
                    "alertname": "RedisMasterDown",
                    "instance": "'$MASTER_IP:$MASTER_PORT'",
                    "severity": "critical"
                },
                "annotations": {
                    "summary": "Redis主节点疑似下线",
                    "description": "哨兵检测到主节点 '$MASTER_IP:$MASTER_PORT' 疑似下线"
                }
             }]'
        ;;
    "+odown")
        echo "$(date): Master $MASTER_NAME ($MASTER_IP:$MASTER_PORT) is objectively down" >> /var/log/redis/sentinel-events.log
        ;;
    "+failover-end")
        echo "$(date): Failover for master $MASTER_NAME completed" >> /var/log/redis/sentinel-events.log
        # 故障转移完成通知
        curl -X POST "http://webhook:5000/redis-failover" \
             -H "Content-Type: application/json" \
             -d '{
                "event": "failover-completed",
                "master": "'$MASTER_NAME'",
                "new_master": "'$MASTER_IP:$MASTER_PORT'",
                "timestamp": "'$(date -Iseconds)'"
             }'
        ;;
esac
```

```bash
#!/bin/bash
# reconfig.sh - 客户端重配置脚本

MASTER_NAME=$1
ROLE=$2
STATE=$3
FROM_IP=$4
FROM_PORT=$5
TO_IP=$6
TO_PORT=$7

echo "$(date): Master $MASTER_NAME role changed from $FROM_IP:$FROM_PORT to $TO_IP:$TO_PORT" >> /var/log/redis/reconfig.log

# 更新应用配置
# 这里可以调用API通知应用程序更新Redis连接配置
curl -X POST "http://app-config-service:8080/redis/master-changed" \
     -H "Content-Type: application/json" \
     -d '{
        "master_name": "'$MASTER_NAME'",
        "old_master": "'$FROM_IP:$FROM_PORT'",
        "new_master": "'$TO_IP:$TO_PORT'",
        "timestamp": "'$(date -Iseconds)'"
     }'
```

### 4.3 集群模式配置

#### 4.3.1 集群节点配置
```bash
# redis-cluster.conf
# 基础配置
port 7000
bind 0.0.0.0
protected-mode yes
requirepass "ClusterPassword123!"
masterauth "ClusterPassword123!"

# 集群配置
cluster-enabled yes
cluster-config-file nodes-7000.conf
cluster-node-timeout 15000
cluster-announce-ip 192.168.1.10
cluster-announce-port 7000
cluster-announce-bus-port 17000

# 故障转移配置
cluster-require-full-coverage no
cluster-replica-validity-factor 10
cluster-migration-barrier 1

# 内存和持久化
maxmemory 4gb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
save 60 10000
appendonly yes
appendfsync everysec

# 性能优化
tcp-keepalive 300
tcp-backlog 511
maxclients 10000

# 慢查询
slowlog-log-slower-than 10000
slowlog-max-len 128

# 安全配置
rename-command FLUSHDB ""
rename-command FLUSHALL ""
rename-command KEYS ""
```

#### 4.3.2 集群部署脚本
```bash
#!/bin/bash
# deploy-cluster.sh

# 创建6个节点的配置文件
for port in 7000 7001 7002 7003 7004 7005; do
    mkdir -p /opt/redis-cluster/${port}
    cp redis-cluster.conf /opt/redis-cluster/${port}/redis.conf
    sed -i "s/port 7000/port ${port}/g" /opt/redis-cluster/${port}/redis.conf
    sed -i "s/nodes-7000.conf/nodes-${port}.conf/g" /opt/redis-cluster/${port}/redis.conf
    sed -i "s/cluster-announce-port 7000/cluster-announce-port ${port}/g" /opt/redis-cluster/${port}/redis.conf
    sed -i "s/cluster-announce-bus-port 17000/cluster-announce-bus-port 1${port}/g" /opt/redis-cluster/${port}/redis.conf
done

# 启动所有节点
for port in 7000 7001 7002 7003 7004 7005; do
    redis-server /opt/redis-cluster/${port}/redis.conf --daemonize yes
done

# 等待节点启动
sleep 5

# 创建集群
redis-cli --cluster create \
    127.0.0.1:7000 127.0.0.1:7001 127.0.0.1:7002 \
    127.0.0.1:7003 127.0.0.1:7004 127.0.0.1:7005 \
    --cluster-replicas 1 \
    --cluster-yes

echo "Redis集群部署完成！"
redis-cli --cluster info 127.0.0.1:7000
```

#### 4.3.3 Docker Compose集群部署
```yaml
# docker-compose-cluster.yml
version: '3.8'
services:
  redis-node-1:
    image: redis:7.0-alpine
    container_name: redis-node-1
    ports:
      - "7000:7000"
      - "17000:17000"
    volumes:
      - ./cluster-configs/redis-7000.conf:/usr/local/etc/redis/redis.conf
      - redis-node-1-data:/data
    command: redis-server /usr/local/etc/redis/redis.conf
    networks:
      redis-cluster:
        ipv4_address: 172.20.0.10
    restart: unless-stopped
    
  redis-node-2:
    image: redis:7.0-alpine
    container_name: redis-node-2
    ports:
      - "7001:7001"
      - "17001:17001"
    volumes:
      - ./cluster-configs/redis-7001.conf:/usr/local/etc/redis/redis.conf
      - redis-node-2-data:/data
    command: redis-server /usr/local/etc/redis/redis.conf
    networks:
      redis-cluster:
        ipv4_address: 172.20.0.11
    restart: unless-stopped
    
  redis-node-3:
    image: redis:7.0-alpine
    container_name: redis-node-3
    ports:
      - "7002:7002"
      - "17002:17002"
    volumes:
      - ./cluster-configs/redis-7002.conf:/usr/local/etc/redis/redis.conf
      - redis-node-3-data:/data
    command: redis-server /usr/local/etc/redis/redis.conf
    networks:
      redis-cluster:
        ipv4_address: 172.20.0.12
    restart: unless-stopped
    
  redis-node-4:
    image: redis:7.0-alpine
    container_name: redis-node-4
    ports:
      - "7003:7003"
      - "17003:17003"
    volumes:
      - ./cluster-configs/redis-7003.conf:/usr/local/etc/redis/redis.conf
      - redis-node-4-data:/data
    command: redis-server /usr/local/etc/redis/redis.conf
    networks:
      redis-cluster:
        ipv4_address: 172.20.0.13
    restart: unless-stopped
    
  redis-node-5:
    image: redis:7.0-alpine
    container_name: redis-node-5
    ports:
      - "7004:7004"
      - "17004:17004"
    volumes:
      - ./cluster-configs/redis-7004.conf:/usr/local/etc/redis/redis.conf
      - redis-node-5-data:/data
    command: redis-server /usr/local/etc/redis/redis.conf
    networks:
      redis-cluster:
        ipv4_address: 172.20.0.14
    restart: unless-stopped
    
  redis-node-6:
    image: redis:7.0-alpine
    container_name: redis-node-6
    ports:
      - "7005:7005"
      - "17005:17005"
    volumes:
      - ./cluster-configs/redis-7005.conf:/usr/local/etc/redis/redis.conf
      - redis-node-6-data:/data
    command: redis-server /usr/local/etc/redis/redis.conf
    networks:
      redis-cluster:
        ipv4_address: 172.20.0.15
    restart: unless-stopped
    
  # 集群初始化容器
  redis-cluster-init:
    image: redis:7.0-alpine
    container_name: redis-cluster-init
    depends_on:
      - redis-node-1
      - redis-node-2
      - redis-node-3
      - redis-node-4
      - redis-node-5
      - redis-node-6
    networks:
      - redis-cluster
    command: >
      sh -c '
        sleep 10 &&
        redis-cli --cluster create \
          172.20.0.10:7000 172.20.0.11:7001 172.20.0.12:7002 \
          172.20.0.13:7003 172.20.0.14:7004 172.20.0.15:7005 \
          --cluster-replicas 1 \
          --cluster-yes &&
        echo "Redis集群初始化完成" &&
        redis-cli --cluster info 172.20.0.10:7000
      '
    restart: "no"

volumes:
  redis-node-1-data:
  redis-node-2-data:
  redis-node-3-data:
  redis-node-4-data:
  redis-node-5-data:
  redis-node-6-data:

networks:
  redis-cluster:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

#### 4.3.4 集群运维脚本
```bash
#!/bin/bash
# cluster-ops.sh - 集群运维脚本

CLUSTER_HOST="127.0.0.1:7000"

case $1 in
    "status")
        echo "=== 集群状态 ==="
        redis-cli --cluster info $CLUSTER_HOST
        echo
        echo "=== 节点信息 ==="
        redis-cli --cluster nodes $CLUSTER_HOST
        ;;
    "check")
        echo "=== 集群健康检查 ==="
        redis-cli --cluster check $CLUSTER_HOST
        ;;
    "rebalance")
        echo "=== 集群重平衡 ==="
        redis-cli --cluster rebalance $CLUSTER_HOST --cluster-threshold 5
        ;;
    "add-node")
        if [ -z "$2" ] || [ -z "$3" ]; then
            echo "用法: $0 add-node <new_node_ip:port> <existing_node_ip:port>"
            exit 1
        fi
        echo "=== 添加节点 $2 ==="
        redis-cli --cluster add-node $2 $3
        ;;
    "remove-node")
        if [ -z "$2" ] || [ -z "$3" ]; then
            echo "用法: $0 remove-node <node_ip:port> <node_id>"
            exit 1
        fi
        echo "=== 移除节点 $2 ==="
        redis-cli --cluster del-node $2 $3
        ;;
    "reshard")
        echo "=== 重新分片 ==="
        redis-cli --cluster reshard $CLUSTER_HOST
        ;;
    "backup")
        echo "=== 集群备份 ==="
        timestamp=$(date +%Y%m%d_%H%M%S)
        mkdir -p /backup/redis-cluster/$timestamp
        
        for port in 7000 7001 7002 7003 7004 7005; do
            redis-cli -p $port --rdb /backup/redis-cluster/$timestamp/dump-$port.rdb
        done
        
        echo "备份完成: /backup/redis-cluster/$timestamp"
        ;;
    "monitor")
        echo "=== 集群监控 ==="
        while true; do
            clear
            echo "$(date) - Redis集群监控"
            echo "========================"
            redis-cli --cluster info $CLUSTER_HOST | grep -E "(slots|state|size)"
            echo
            redis-cli -p 7000 info replication | grep -E "(role|connected_slaves)"
            echo
            redis-cli -p 7000 info stats | grep -E "(total_commands_processed|instantaneous_ops_per_sec)"
            sleep 5
        done
        ;;
    *)
        echo "Redis集群运维脚本"
        echo "用法: $0 {status|check|rebalance|add-node|remove-node|reshard|backup|monitor}"
        echo
        echo "命令说明:"
        echo "  status      - 查看集群状态"
        echo "  check       - 健康检查"
        echo "  rebalance   - 重平衡"
        echo "  add-node    - 添加节点"
        echo "  remove-node - 移除节点"
        echo "  reshard     - 重新分片"
        echo "  backup      - 备份集群"
        echo "  monitor     - 实时监控"
        ;;
esac
```

### 4.4 生产环境最佳实践

#### 4.4.1 系统参数优化
```bash
# /etc/sysctl.conf
# 网络优化
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.core.netdev_max_backlog = 5000
net.ipv4.tcp_fin_timeout = 30
net.ipv4.tcp_keepalive_time = 1200
net.ipv4.tcp_keepalive_probes = 3
net.ipv4.tcp_keepalive_intvl = 15

# 内存优化
vm.overcommit_memory = 1
vm.swappiness = 1
vm.dirty_background_ratio = 5
vm.dirty_ratio = 10

# 文件描述符
fs.file-max = 1000000

# 应用配置
sysctl -p
```

```bash
# /etc/security/limits.conf
redis soft nofile 65535
redis hard nofile 65535
redis soft nproc 65535
redis hard nproc 65535
```

#### 4.4.2 监控脚本
```bash
#!/bin/bash
# redis-health-check.sh

REDIS_HOST="127.0.0.1"
REDIS_PORT="6379"
REDIS_PASSWORD="your_password"
LOG_FILE="/var/log/redis-health.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> $LOG_FILE
}

# 检查Redis连接
check_connection() {
    if redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD ping > /dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# 检查内存使用
check_memory() {
    local used_memory=$(redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD info memory | grep used_memory_human | cut -d: -f2 | tr -d '\r')
    local max_memory=$(redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD config get maxmemory | tail -1)
    
    if [ "$max_memory" != "0" ]; then
        local used_bytes=$(redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD info memory | grep used_memory: | cut -d: -f2 | tr -d '\r')
        local usage_percent=$((used_bytes * 100 / max_memory))
        
        if [ $usage_percent -gt 85 ]; then
            log "WARNING: 内存使用率过高 ${usage_percent}%"
            return 1
        fi
    fi
    return 0
}

# 检查慢查询
check_slowlog() {
    local slowlog_len=$(redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD slowlog len)
    if [ $slowlog_len -gt 100 ]; then
        log "WARNING: 慢查询数量过多 $slowlog_len"
        return 1
    fi
    return 0
}

# 检查主从同步
check_replication() {
    local role=$(redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD info replication | grep role | cut -d: -f2 | tr -d '\r')
    
    if [ "$role" = "master" ]; then
        local connected_slaves=$(redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD info replication | grep connected_slaves | cut -d: -f2 | tr -d '\r')
        if [ $connected_slaves -eq 0 ]; then
            log "WARNING: 主节点没有从节点连接"
            return 1
        fi
    elif [ "$role" = "slave" ]; then
        local master_link_status=$(redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD info replication | grep master_link_status | cut -d: -f2 | tr -d '\r')
        if [ "$master_link_status" != "up" ]; then
            log "CRITICAL: 从节点与主节点连接断开"
            return 1
        fi
    fi
    return 0
}

# 主检查函数
main() {
    log "开始Redis健康检查"
    
    if ! check_connection; then
        log "CRITICAL: Redis连接失败"
        exit 1
    fi
    
    check_memory
    check_slowlog
    check_replication
    
    log "Redis健康检查完成"
}

# 如果作为脚本直接运行
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main
fi
```

#### 4.4.3 自动化部署脚本
```bash
#!/bin/bash
# redis-deploy.sh - Redis自动化部署脚本

set -e

# 配置变量
REDIS_VERSION="7.0.15"
INSTALL_DIR="/opt/redis"
DATA_DIR="/data/redis"
LOG_DIR="/var/log/redis"
CONF_DIR="/etc/redis"
REDIS_USER="redis"
REDIS_GROUP="redis"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查系统
check_system() {
    log_info "检查系统环境..."
    
    # 检查操作系统
    if [ ! -f /etc/redhat-release ] && [ ! -f /etc/debian_version ]; then
        log_error "不支持的操作系统"
        exit 1
    fi
    
    # 检查内存
    local mem_total=$(free -m | awk 'NR==2{print $2}')
    if [ $mem_total -lt 2048 ]; then
        log_warn "内存不足2GB，建议增加内存"
    fi
    
    # 检查磁盘空间
    local disk_free=$(df -m / | awk 'NR==2{print $4}')
    if [ $disk_free -lt 10240 ]; then
        log_warn "磁盘空间不足10GB，建议增加存储"
    fi
}

# 创建用户和目录
setup_user_dirs() {
    log_info "创建Redis用户和目录..."
    
    # 创建用户
    if ! id "$REDIS_USER" &>/dev/null; then
        useradd -r -s /bin/false $REDIS_USER
    fi
    
    # 创建目录
    mkdir -p $INSTALL_DIR $DATA_DIR $LOG_DIR $CONF_DIR
    chown -R $REDIS_USER:$REDIS_GROUP $DATA_DIR $LOG_DIR
    chmod 755 $INSTALL_DIR $CONF_DIR
    chmod 750 $DATA_DIR $LOG_DIR
}

# 安装Redis
install_redis() {
    log_info "安装Redis $REDIS_VERSION..."
    
    cd /tmp
    wget http://download.redis.io/releases/redis-$REDIS_VERSION.tar.gz
    tar xzf redis-$REDIS_VERSION.tar.gz
    cd redis-$REDIS_VERSION
    
    make
    make install PREFIX=$INSTALL_DIR
    
    # 创建软链接
    ln -sf $INSTALL_DIR/bin/redis-server /usr/local/bin/
    ln -sf $INSTALL_DIR/bin/redis-cli /usr/local/bin/
    ln -sf $INSTALL_DIR/bin/redis-sentinel /usr/local/bin/
    
    # 清理
    cd /
    rm -rf /tmp/redis-$REDIS_VERSION*
}

# 配置系统参数
optimize_system() {
    log_info "优化系统参数..."
    
    # 内核参数
    cat >> /etc/sysctl.conf << EOF
# Redis优化参数
vm.overcommit_memory = 1
net.core.somaxconn = 65535
EOF
    
    # 禁用透明大页
    echo never > /sys/kernel/mm/transparent_hugepage/enabled
    echo never > /sys/kernel/mm/transparent_hugepage/defrag
    
    # 添加到启动脚本
    cat >> /etc/rc.local << EOF
echo never > /sys/kernel/mm/transparent_hugepage/enabled
echo never > /sys/kernel/mm/transparent_hugepage/defrag
EOF
    
    sysctl -p
}

# 创建systemd服务
create_service() {
    log_info "创建systemd服务..."
    
    cat > /etc/systemd/system/redis.service << EOF
[Unit]
Description=Redis In-Memory Data Store
After=network.target

[Service]
User=$REDIS_USER
Group=$REDIS_GROUP
ExecStart=$INSTALL_DIR/bin/redis-server $CONF_DIR/redis.conf
ExecStop=/bin/kill -s QUIT \$MAINPID
TimeoutStopSec=0
Restart=always

[Install]
WantedBy=multi-user.target
EOF
    
    systemctl daemon-reload
    systemctl enable redis
}

# 生成配置文件
generate_config() {
    log_info "生成Redis配置文件..."
    
    cat > $CONF_DIR/redis.conf << EOF
# Redis生产环境配置
# 基础配置
port 6379
bind 127.0.0.1
protected-mode yes
tcp-backlog 511
timeout 0
tcp-keepalive 300

# 日志配置
loglevel notice
logfile $LOG_DIR/redis.log
syslog-enabled yes
syslog-ident redis

# 数据库配置
databases 16

# 持久化配置
save 900 1
save 300 10
save 60 10000
stop-writes-on-bgsave-error yes
rdbcompression yes
rdbchecksum yes
dbfilename dump.rdb
dir $DATA_DIR

# AOF配置
appendonly yes
appendfilename "appendonly.aof"
appendfsync everysec
no-appendfsync-on-rewrite no
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb
aof-use-rdb-preamble yes

# 内存配置
maxmemory 2gb
maxmemory-policy allkeys-lru

# 客户端配置
maxclients 10000

# 慢查询配置
slowlog-log-slower-than 10000
slowlog-max-len 128

# 安全配置
# requirepass your_password_here
EOF
    
    chown $REDIS_USER:$REDIS_GROUP $CONF_DIR/redis.conf
    chmod 640 $CONF_DIR/redis.conf
}

# 主函数
main() {
    if [ "$EUID" -ne 0 ]; then
        log_error "请使用root权限运行此脚本"
        exit 1
    fi
    
    log_info "开始Redis自动化部署..."
    
    check_system
    setup_user_dirs
    install_redis
    optimize_system
    generate_config
    create_service
    
    log_info "Redis部署完成！"
    log_info "配置文件: $CONF_DIR/redis.conf"
    log_info "数据目录: $DATA_DIR"
    log_info "日志目录: $LOG_DIR"
    log_info "启动命令: systemctl start redis"
    log_warn "请记得修改配置文件中的密码设置"
}

# 执行主函数
main "$@"
```

## 五、总结与最佳实践

### 5.1 性能优化核心要点
1. **热点数据处理**：分片、本地缓存、读写分离
2. **大Key优化**：拆分存储、分批处理、合理TTL
3. **网络优化**：Pipeline、连接池、压缩传输
4. **内存管理**：合理配置、定期清理、碎片整理
5. **架构设计**：集群分片、主从复制、故障转移

### 5.2 监控告警体系
1. **核心指标**：QPS、延迟、内存、连接数、慢查询
2. **可用性监控**：主从状态、集群健康、节点故障
3. **业务指标**：热点Key、大Key、命中率
4. **告警策略**：分级告警、自动恢复、通知机制

### 5.3 生产环境配置原则
1. **安全第一**：密码认证、网络隔离、权限控制
2. **高可用**：主从复制、哨兵监控、集群部署
3. **性能优化**：系统参数、内存配置、持久化策略
4. **运维自动化**：监控告警、自动部署、故障恢复

### 5.4 故障处理流程
1. **快速定位**：监控告警、日志分析、性能指标
2. **应急处理**：流量切换、服务降级、资源扩容
3. **根因分析**：慢查询分析、内存分析、网络诊断
4. **预防措施**：配置优化、架构改进、监控完善

通过以上生产实战经验和配置方案，可以构建一个高性能、高可用、易运维的Redis集群系统，满足大规模互联网应用的需求。