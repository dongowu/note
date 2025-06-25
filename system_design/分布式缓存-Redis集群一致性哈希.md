# 分布式缓存：Redis集群 + 一致性哈希的缓存分片方案

## 1. 系统概述

### 1.1 业务场景
- **数据规模**: TB级缓存数据
- **访问量**: 千万级QPS
- **延迟要求**: P99 < 1ms
- **可用性**: 99.99%
- **一致性**: 最终一致性

### 1.2 技术挑战
- **数据分片**: 海量数据的均匀分布
- **节点扩缩容**: 最小化数据迁移
- **故障恢复**: 快速故障检测与自动恢复
- **热点数据**: 避免热点导致的性能瓶颈

---

## 2. 一致性哈希算法

### 2.1 算法原理

一致性哈希将整个哈希空间组织成一个虚拟的圆环，数据和节点都映射到这个圆环上。

```
         Node A (hash: 100)
              |
    Key3 ---- + ---- Key1
   /                    \
  /                      \
Node C                   Node B
(hash: 300)           (hash: 200)
  \                      /
   \                    /
    Key4 ---- + ---- Key2
              |
         Node D (hash: 400)
```

### 2.2 Go语言实现

#### 基础数据结构
```go
package consistent

import (
    "crypto/sha1"
    "fmt"
    "sort"
    "strconv"
    "sync"
)

// 一致性哈希环
type ConsistentHash struct {
    mu           sync.RWMutex
    hash         func([]byte) uint32  // 哈希函数
    replicas     int                  // 虚拟节点数量
    keys         []uint32             // 哈希环上的所有键（已排序）
    hashMap      map[uint32]string    // 哈希值到节点的映射
    nodes        map[string]bool      // 所有节点
    nodeWeights  map[string]int       // 节点权重
}

// 创建一致性哈希实例
func NewConsistentHash(replicas int, hashFunc func([]byte) uint32) *ConsistentHash {
    if hashFunc == nil {
        hashFunc = defaultHash
    }
    
    return &ConsistentHash{
        hash:        hashFunc,
        replicas:    replicas,
        hashMap:     make(map[uint32]string),
        nodes:       make(map[string]bool),
        nodeWeights: make(map[string]int),
    }
}

// 默认哈希函数
func defaultHash(data []byte) uint32 {
    h := sha1.Sum(data)
    return uint32(h[0])<<24 | uint32(h[1])<<16 | uint32(h[2])<<8 | uint32(h[3])
}
```

#### 节点管理
```go
// 添加节点
func (ch *ConsistentHash) AddNode(node string, weight int) {
    ch.mu.Lock()
    defer ch.mu.Unlock()
    
    if ch.nodes[node] {
        return // 节点已存在
    }
    
    ch.nodes[node] = true
    ch.nodeWeights[node] = weight
    
    // 根据权重创建虚拟节点
    virtualNodes := ch.replicas * weight
    for i := 0; i < virtualNodes; i++ {
        virtualKey := fmt.Sprintf("%s#%d", node, i)
        hash := ch.hash([]byte(virtualKey))
        ch.keys = append(ch.keys, hash)
        ch.hashMap[hash] = node
    }
    
    // 保持哈希环有序
    sort.Slice(ch.keys, func(i, j int) bool {
        return ch.keys[i] < ch.keys[j]
    })
}

// 删除节点
func (ch *ConsistentHash) RemoveNode(node string) {
    ch.mu.Lock()
    defer ch.mu.Unlock()
    
    if !ch.nodes[node] {
        return // 节点不存在
    }
    
    delete(ch.nodes, node)
    weight := ch.nodeWeights[node]
    delete(ch.nodeWeights, node)
    
    // 删除虚拟节点
    virtualNodes := ch.replicas * weight
    for i := 0; i < virtualNodes; i++ {
        virtualKey := fmt.Sprintf("%s#%d", node, i)
        hash := ch.hash([]byte(virtualKey))
        delete(ch.hashMap, hash)
        
        // 从keys中删除
        for j, key := range ch.keys {
            if key == hash {
                ch.keys = append(ch.keys[:j], ch.keys[j+1:]...)
                break
            }
        }
    }
}

// 获取节点
func (ch *ConsistentHash) GetNode(key string) string {
    ch.mu.RLock()
    defer ch.mu.RUnlock()
    
    if len(ch.keys) == 0 {
        return ""
    }
    
    hash := ch.hash([]byte(key))
    
    // 二分查找第一个大于等于hash的节点
    idx := sort.Search(len(ch.keys), func(i int) bool {
        return ch.keys[i] >= hash
    })
    
    // 如果没找到，则选择第一个节点（环形结构）
    if idx == len(ch.keys) {
        idx = 0
    }
    
    return ch.hashMap[ch.keys[idx]]
}

// 获取多个节点（用于副本）
func (ch *ConsistentHash) GetNodes(key string, count int) []string {
    ch.mu.RLock()
    defer ch.mu.RUnlock()
    
    if len(ch.keys) == 0 || count <= 0 {
        return nil
    }
    
    hash := ch.hash([]byte(key))
    nodes := make([]string, 0, count)
    nodeSet := make(map[string]bool)
    
    // 找到起始位置
    idx := sort.Search(len(ch.keys), func(i int) bool {
        return ch.keys[i] >= hash
    })
    
    // 顺时针查找不同的物理节点
    for len(nodes) < count && len(nodeSet) < len(ch.nodes) {
        if idx >= len(ch.keys) {
            idx = 0
        }
        
        node := ch.hashMap[ch.keys[idx]]
        if !nodeSet[node] {
            nodes = append(nodes, node)
            nodeSet[node] = true
        }
        idx++
    }
    
    return nodes
}
```

#### 数据迁移
```go
// 数据迁移信息
type MigrationInfo struct {
    Key      string
    FromNode string
    ToNode   string
}

// 计算节点变更后的数据迁移
func (ch *ConsistentHash) CalculateMigration(oldNodes, newNodes []string) []MigrationInfo {
    // 创建旧的哈希环
    oldHash := NewConsistentHash(ch.replicas, ch.hash)
    for _, node := range oldNodes {
        oldHash.AddNode(node, 1)
    }
    
    // 创建新的哈希环
    newHash := NewConsistentHash(ch.replicas, ch.hash)
    for _, node := range newNodes {
        newHash.AddNode(node, 1)
    }
    
    var migrations []MigrationInfo
    
    // 模拟一些键来计算迁移
    // 在实际应用中，这里应该遍历所有实际的键
    for i := 0; i < 10000; i++ {
        key := fmt.Sprintf("key_%d", i)
        oldNode := oldHash.GetNode(key)
        newNode := newHash.GetNode(key)
        
        if oldNode != newNode && oldNode != "" && newNode != "" {
            migrations = append(migrations, MigrationInfo{
                Key:      key,
                FromNode: oldNode,
                ToNode:   newNode,
            })
        }
    }
    
    return migrations
}
```

---

## 3. Redis集群架构

### 3.1 集群拓扑

```
┌─────────────────────────────────────────────────────────────┐
│                        客户端层                              │
├─────────────────────────────────────────────────────────────┤
│                      代理层 (Proxy)                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Proxy 1   │  │   Proxy 2   │  │   Proxy 3   │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
├─────────────────────────────────────────────────────────────┤
│                      Redis集群                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Master1   │  │   Master2   │  │   Master3   │         │
│  │   Slave1    │  │   Slave2    │  │   Slave3    │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Redis代理实现

#### 代理服务器
```go
package proxy

import (
    "context"
    "fmt"
    "log"
    "net"
    "strings"
    "sync"
    "time"
    
    "github.com/go-redis/redis/v8"
)

// Redis代理
type RedisProxy struct {
    consistentHash *ConsistentHash
    clients        map[string]*redis.Client
    mu             sync.RWMutex
    config         *ProxyConfig
}

// 代理配置
type ProxyConfig struct {
    ListenAddr      string
    Nodes          []NodeConfig
    Replicas       int
    HealthCheck    time.Duration
    ConnTimeout    time.Duration
    ReadTimeout    time.Duration
    WriteTimeout   time.Duration
    MaxRetries     int
}

// 节点配置
type NodeConfig struct {
    Name     string
    Addr     string
    Password string
    Weight   int
    DB       int
}

// 创建Redis代理
func NewRedisProxy(config *ProxyConfig) *RedisProxy {
    proxy := &RedisProxy{
        consistentHash: NewConsistentHash(config.Replicas, nil),
        clients:        make(map[string]*redis.Client),
        config:         config,
    }
    
    // 初始化Redis客户端
    for _, nodeConfig := range config.Nodes {
        client := redis.NewClient(&redis.Options{
            Addr:         nodeConfig.Addr,
            Password:     nodeConfig.Password,
            DB:           nodeConfig.DB,
            DialTimeout:  config.ConnTimeout,
            ReadTimeout:  config.ReadTimeout,
            WriteTimeout: config.WriteTimeout,
            MaxRetries:   config.MaxRetries,
        })
        
        proxy.clients[nodeConfig.Name] = client
        proxy.consistentHash.AddNode(nodeConfig.Name, nodeConfig.Weight)
    }
    
    // 启动健康检查
    go proxy.startHealthCheck()
    
    return proxy
}

// 获取Redis客户端
func (p *RedisProxy) getClient(key string) *redis.Client {
    p.mu.RLock()
    defer p.mu.RUnlock()
    
    nodeName := p.consistentHash.GetNode(key)
    if nodeName == "" {
        return nil
    }
    
    return p.clients[nodeName]
}

// 获取多个客户端（用于副本）
func (p *RedisProxy) getClients(key string, count int) []*redis.Client {
    p.mu.RLock()
    defer p.mu.RUnlock()
    
    nodeNames := p.consistentHash.GetNodes(key, count)
    clients := make([]*redis.Client, 0, len(nodeNames))
    
    for _, nodeName := range nodeNames {
        if client := p.clients[nodeName]; client != nil {
            clients = append(clients, client)
        }
    }
    
    return clients
}
```

#### 命令处理
```go
// Redis命令处理
func (p *RedisProxy) handleCommand(ctx context.Context, cmd string, args []string) (interface{}, error) {
    if len(args) == 0 {
        return nil, fmt.Errorf("invalid command: %s", cmd)
    }
    
    key := args[0]
    cmd = strings.ToUpper(cmd)
    
    switch cmd {
    case "GET":
        return p.handleGet(ctx, key)
    case "SET":
        if len(args) < 2 {
            return nil, fmt.Errorf("invalid SET command")
        }
        return p.handleSet(ctx, key, args[1], args[2:]...)
    case "DEL":
        return p.handleDel(ctx, args...)
    case "EXISTS":
        return p.handleExists(ctx, args...)
    case "EXPIRE":
        if len(args) < 2 {
            return nil, fmt.Errorf("invalid EXPIRE command")
        }
        return p.handleExpire(ctx, key, args[1])
    case "MGET":
        return p.handleMGet(ctx, args...)
    case "MSET":
        return p.handleMSet(ctx, args...)
    default:
        return nil, fmt.Errorf("unsupported command: %s", cmd)
    }
}

// GET命令处理
func (p *RedisProxy) handleGet(ctx context.Context, key string) (string, error) {
    client := p.getClient(key)
    if client == nil {
        return "", fmt.Errorf("no available client for key: %s", key)
    }
    
    return client.Get(ctx, key).Result()
}

// SET命令处理（支持副本）
func (p *RedisProxy) handleSet(ctx context.Context, key, value string, args ...string) (string, error) {
    clients := p.getClients(key, 2) // 主副本
    if len(clients) == 0 {
        return "", fmt.Errorf("no available client for key: %s", key)
    }
    
    // 解析SET参数
    var expiration time.Duration
    for i := 0; i < len(args); i += 2 {
        if i+1 < len(args) {
            switch strings.ToUpper(args[i]) {
            case "EX":
                if exp, err := time.ParseDuration(args[i+1] + "s"); err == nil {
                    expiration = exp
                }
            case "PX":
                if exp, err := time.ParseDuration(args[i+1] + "ms"); err == nil {
                    expiration = exp
                }
            }
        }
    }
    
    // 写入主节点
    result, err := clients[0].Set(ctx, key, value, expiration).Result()
    if err != nil {
        return "", err
    }
    
    // 异步写入副本节点
    if len(clients) > 1 {
        go func() {
            for i := 1; i < len(clients); i++ {
                clients[i].Set(context.Background(), key, value, expiration)
            }
        }()
    }
    
    return result, nil
}

// MGET命令处理（跨节点）
func (p *RedisProxy) handleMGet(ctx context.Context, keys ...string) ([]interface{}, error) {
    // 按节点分组键
    nodeKeys := make(map[string][]string)
    keyToNode := make(map[string]string)
    
    for _, key := range keys {
        nodeName := p.consistentHash.GetNode(key)
        if nodeName != "" {
            nodeKeys[nodeName] = append(nodeKeys[nodeName], key)
            keyToNode[key] = nodeName
        }
    }
    
    // 并发查询各节点
    type result struct {
        node   string
        values []interface{}
        err    error
    }
    
    resultChan := make(chan result, len(nodeKeys))
    
    for nodeName, nodeKeyList := range nodeKeys {
        go func(node string, keyList []string) {
            client := p.clients[node]
            if client == nil {
                resultChan <- result{node: node, err: fmt.Errorf("client not found for node: %s", node)}
                return
            }
            
            values, err := client.MGet(ctx, keyList...).Result()
            resultChan <- result{node: node, values: values, err: err}
        }(nodeName, nodeKeyList)
    }
    
    // 收集结果
    nodeResults := make(map[string][]interface{})
    for i := 0; i < len(nodeKeys); i++ {
        res := <-resultChan
        if res.err != nil {
            return nil, res.err
        }
        nodeResults[res.node] = res.values
    }
    
    // 按原始顺序重组结果
    results := make([]interface{}, len(keys))
    nodeKeyIndex := make(map[string]int)
    
    for i, key := range keys {
        nodeName := keyToNode[key]
        if nodeName != "" {
            keyIndex := nodeKeyIndex[nodeName]
            if keyIndex < len(nodeResults[nodeName]) {
                results[i] = nodeResults[nodeName][keyIndex]
                nodeKeyIndex[nodeName]++
            }
        }
    }
    
    return results, nil
}
```

#### 健康检查与故障恢复
```go
// 健康检查
func (p *RedisProxy) startHealthCheck() {
    ticker := time.NewTicker(p.config.HealthCheck)
    defer ticker.Stop()
    
    for range ticker.C {
        p.checkNodeHealth()
    }
}

func (p *RedisProxy) checkNodeHealth() {
    p.mu.Lock()
    defer p.mu.Unlock()
    
    for nodeName, client := range p.clients {
        ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
        err := client.Ping(ctx).Err()
        cancel()
        
        if err != nil {
            log.Printf("Node %s is unhealthy: %v", nodeName, err)
            // 从一致性哈希环中移除不健康的节点
            p.consistentHash.RemoveNode(nodeName)
        } else {
            // 确保健康的节点在哈希环中
            if !p.isNodeInHash(nodeName) {
                weight := p.getNodeWeight(nodeName)
                p.consistentHash.AddNode(nodeName, weight)
                log.Printf("Node %s recovered and added back to hash ring", nodeName)
            }
        }
    }
}

func (p *RedisProxy) isNodeInHash(nodeName string) bool {
    // 检查节点是否在哈希环中
    testKey := "__health_check__"
    return p.consistentHash.GetNode(testKey) != ""
}

func (p *RedisProxy) getNodeWeight(nodeName string) int {
    for _, nodeConfig := range p.config.Nodes {
        if nodeConfig.Name == nodeName {
            return nodeConfig.Weight
        }
    }
    return 1 // 默认权重
}
```

---

## 4. 缓存策略优化

### 4.1 热点数据处理

#### 热点检测
```go
type HotKeyDetector struct {
    counters    map[string]*Counter
    mu          sync.RWMutex
    threshold   int64
    window      time.Duration
    hotKeys     map[string]bool
    localCache  *sync.Map // 本地缓存热点数据
}

type Counter struct {
    count     int64
    timestamp time.Time
}

// 记录键访问
func (hkd *HotKeyDetector) RecordAccess(key string) {
    hkd.mu.Lock()
    defer hkd.mu.Unlock()
    
    now := time.Now()
    counter, exists := hkd.counters[key]
    
    if !exists || now.Sub(counter.timestamp) > hkd.window {
        hkd.counters[key] = &Counter{
            count:     1,
            timestamp: now,
        }
    } else {
        counter.count++
        
        // 检查是否成为热点
        if counter.count > hkd.threshold {
            hkd.hotKeys[key] = true
            log.Printf("Hot key detected: %s (count: %d)", key, counter.count)
        }
    }
}

// 检查是否为热点键
func (hkd *HotKeyDetector) IsHotKey(key string) bool {
    hkd.mu.RLock()
    defer hkd.mu.RUnlock()
    return hkd.hotKeys[key]
}

// 从本地缓存获取热点数据
func (hkd *HotKeyDetector) GetFromLocalCache(key string) (interface{}, bool) {
    if hkd.IsHotKey(key) {
        return hkd.localCache.Load(key)
    }
    return nil, false
}

// 设置本地缓存
func (hkd *HotKeyDetector) SetToLocalCache(key string, value interface{}) {
    if hkd.IsHotKey(key) {
        hkd.localCache.Store(key, value)
    }
}
```

#### 多级缓存
```go
type MultiLevelCache struct {
    l1Cache     *sync.Map           // 本地缓存
    l2Cache     *RedisProxy         // Redis集群
    hotDetector *HotKeyDetector     // 热点检测器
    stats       *CacheStats         // 缓存统计
}

type CacheStats struct {
    L1Hits   int64
    L1Misses int64
    L2Hits   int64
    L2Misses int64
    mu       sync.RWMutex
}

// 获取数据
func (mlc *MultiLevelCache) Get(ctx context.Context, key string) (string, error) {
    // 记录访问
    mlc.hotDetector.RecordAccess(key)
    
    // L1缓存：本地缓存
    if value, ok := mlc.hotDetector.GetFromLocalCache(key); ok {
        mlc.stats.IncrL1Hits()
        return value.(string), nil
    }
    mlc.stats.IncrL1Misses()
    
    // L2缓存：Redis集群
    value, err := mlc.l2Cache.handleGet(ctx, key)
    if err == nil {
        mlc.stats.IncrL2Hits()
        // 如果是热点数据，存入本地缓存
        mlc.hotDetector.SetToLocalCache(key, value)
        return value, nil
    }
    mlc.stats.IncrL2Misses()
    
    return "", err
}

// 设置数据
func (mlc *MultiLevelCache) Set(ctx context.Context, key, value string, expiration time.Duration) error {
    // 写入Redis集群
    _, err := mlc.l2Cache.handleSet(ctx, key, value, fmt.Sprintf("PX %d", expiration.Milliseconds()))
    if err != nil {
        return err
    }
    
    // 如果是热点数据，同时写入本地缓存
    if mlc.hotDetector.IsHotKey(key) {
        mlc.hotDetector.SetToLocalCache(key, value)
        
        // 设置过期时间
        time.AfterFunc(expiration, func() {
            mlc.l1Cache.Delete(key)
        })
    }
    
    return nil
}

// 缓存统计
func (cs *CacheStats) IncrL1Hits() {
    cs.mu.Lock()
    cs.L1Hits++
    cs.mu.Unlock()
}

func (cs *CacheStats) IncrL1Misses() {
    cs.mu.Lock()
    cs.L1Misses++
    cs.mu.Unlock()
}

func (cs *CacheStats) IncrL2Hits() {
    cs.mu.Lock()
    cs.L2Hits++
    cs.mu.Unlock()
}

func (cs *CacheStats) IncrL2Misses() {
    cs.mu.Lock()
    cs.L2Misses++
    cs.mu.Unlock()
}

func (cs *CacheStats) GetStats() (int64, int64, int64, int64) {
    cs.mu.RLock()
    defer cs.mu.RUnlock()
    return cs.L1Hits, cs.L1Misses, cs.L2Hits, cs.L2Misses
}
```

### 4.2 数据一致性保证

#### 缓存更新策略
```go
type CacheConsistency struct {
    cache    *MultiLevelCache
    db       *sql.DB
    mq       *MessageQueue
}

// Cache-Aside模式
func (cc *CacheConsistency) GetWithCacheAside(ctx context.Context, key string, loader func() (string, error)) (string, error) {
    // 1. 从缓存获取
    value, err := cc.cache.Get(ctx, key)
    if err == nil {
        return value, nil
    }
    
    // 2. 缓存未命中，从数据源加载
    value, err = loader()
    if err != nil {
        return "", err
    }
    
    // 3. 写入缓存
    cc.cache.Set(ctx, key, value, time.Hour)
    
    return value, nil
}

// Write-Through模式
func (cc *CacheConsistency) SetWithWriteThrough(ctx context.Context, key, value string, updater func(string) error) error {
    // 1. 更新数据源
    if err := updater(value); err != nil {
        return err
    }
    
    // 2. 更新缓存
    return cc.cache.Set(ctx, key, value, time.Hour)
}

// Write-Behind模式
func (cc *CacheConsistency) SetWithWriteBehind(ctx context.Context, key, value string) error {
    // 1. 立即更新缓存
    if err := cc.cache.Set(ctx, key, value, time.Hour); err != nil {
        return err
    }
    
    // 2. 异步更新数据源
    updateEvent := &UpdateEvent{
        Key:       key,
        Value:     value,
        Timestamp: time.Now().Unix(),
    }
    
    return cc.mq.SendMessage("cache_updates", updateEvent)
}

// 延迟双删策略
func (cc *CacheConsistency) UpdateWithDelayedDoubleDelete(ctx context.Context, key string, updater func() error) error {
    // 1. 删除缓存
    cc.cache.Delete(ctx, key)
    
    // 2. 更新数据库
    if err := updater(); err != nil {
        return err
    }
    
    // 3. 延迟删除缓存
    time.AfterFunc(500*time.Millisecond, func() {
        cc.cache.Delete(context.Background(), key)
    })
    
    return nil
}
```

---

## 5. 监控与运维

### 5.1 监控指标

#### 性能监控
```go
type CacheMonitor struct {
    prometheus *prometheus.Registry
    metrics    *CacheMetrics
}

type CacheMetrics struct {
    // 请求指标
    RequestsTotal    *prometheus.CounterVec
    RequestDuration  *prometheus.HistogramVec
    
    // 缓存指标
    CacheHits        *prometheus.CounterVec
    CacheMisses      *prometheus.CounterVec
    CacheSize        *prometheus.GaugeVec
    
    // 节点指标
    NodeStatus       *prometheus.GaugeVec
    NodeConnections  *prometheus.GaugeVec
    NodeMemoryUsage  *prometheus.GaugeVec
    
    // 热点指标
    HotKeys          *prometheus.GaugeVec
    KeyAccessCount   *prometheus.CounterVec
}

// 初始化监控指标
func NewCacheMonitor() *CacheMonitor {
    metrics := &CacheMetrics{
        RequestsTotal: prometheus.NewCounterVec(
            prometheus.CounterOpts{
                Name: "cache_requests_total",
                Help: "Total number of cache requests",
            },
            []string{"method", "status"},
        ),
        RequestDuration: prometheus.NewHistogramVec(
            prometheus.HistogramOpts{
                Name:    "cache_request_duration_seconds",
                Help:    "Cache request duration",
                Buckets: prometheus.DefBuckets,
            },
            []string{"method"},
        ),
        CacheHits: prometheus.NewCounterVec(
            prometheus.CounterOpts{
                Name: "cache_hits_total",
                Help: "Total number of cache hits",
            },
            []string{"level"},
        ),
        CacheMisses: prometheus.NewCounterVec(
            prometheus.CounterOpts{
                Name: "cache_misses_total",
                Help: "Total number of cache misses",
            },
            []string{"level"},
        ),
        NodeStatus: prometheus.NewGaugeVec(
            prometheus.GaugeOpts{
                Name: "cache_node_status",
                Help: "Cache node status (1=healthy, 0=unhealthy)",
            },
            []string{"node"},
        ),
        HotKeys: prometheus.NewGaugeVec(
            prometheus.GaugeOpts{
                Name: "cache_hot_keys_count",
                Help: "Number of hot keys detected",
            },
            []string{"node"},
        ),
    }
    
    registry := prometheus.NewRegistry()
    registry.MustRegister(
        metrics.RequestsTotal,
        metrics.RequestDuration,
        metrics.CacheHits,
        metrics.CacheMisses,
        metrics.NodeStatus,
        metrics.HotKeys,
    )
    
    return &CacheMonitor{
        prometheus: registry,
        metrics:    metrics,
    }
}

// 记录请求指标
func (cm *CacheMonitor) RecordRequest(method, status string, duration time.Duration) {
    cm.metrics.RequestsTotal.WithLabelValues(method, status).Inc()
    cm.metrics.RequestDuration.WithLabelValues(method).Observe(duration.Seconds())
}

// 记录缓存命中
func (cm *CacheMonitor) RecordCacheHit(level string) {
    cm.metrics.CacheHits.WithLabelValues(level).Inc()
}

// 记录缓存未命中
func (cm *CacheMonitor) RecordCacheMiss(level string) {
    cm.metrics.CacheMisses.WithLabelValues(level).Inc()
}

// 更新节点状态
func (cm *CacheMonitor) UpdateNodeStatus(node string, healthy bool) {
    status := 0.0
    if healthy {
        status = 1.0
    }
    cm.metrics.NodeStatus.WithLabelValues(node).Set(status)
}
```

### 5.2 自动扩缩容

#### 扩容策略
```go
type AutoScaler struct {
    proxy       *RedisProxy
    monitor     *CacheMonitor
    config      *AutoScaleConfig
    nodeManager *NodeManager
}

type AutoScaleConfig struct {
    MinNodes        int
    MaxNodes        int
    ScaleUpThreshold   float64 // CPU使用率阈值
    ScaleDownThreshold float64
    CooldownPeriod     time.Duration
    CheckInterval      time.Duration
}

type NodeManager struct {
    availableNodes []NodeConfig
    activeNodes    map[string]bool
}

// 启动自动扩缩容
func (as *AutoScaler) Start() {
    ticker := time.NewTicker(as.config.CheckInterval)
    go func() {
        for range ticker.C {
            as.checkAndScale()
        }
    }()
}

// 检查并执行扩缩容
func (as *AutoScaler) checkAndScale() {
    metrics := as.collectMetrics()
    
    if as.shouldScaleUp(metrics) {
        as.scaleUp()
    } else if as.shouldScaleDown(metrics) {
        as.scaleDown()
    }
}

// 扩容
func (as *AutoScaler) scaleUp() {
    activeCount := len(as.nodeManager.activeNodes)
    if activeCount >= as.config.MaxNodes {
        log.Println("Already at maximum node count")
        return
    }
    
    // 选择一个可用节点
    newNode := as.nodeManager.selectAvailableNode()
    if newNode == nil {
        log.Println("No available nodes for scaling up")
        return
    }
    
    // 启动新节点
    if err := as.nodeManager.startNode(newNode); err != nil {
        log.Printf("Failed to start node %s: %v", newNode.Name, err)
        return
    }
    
    // 添加到代理
    as.proxy.AddNode(newNode)
    as.nodeManager.activeNodes[newNode.Name] = true
    
    log.Printf("Scaled up: added node %s", newNode.Name)
}

// 缩容
func (as *AutoScaler) scaleDown() {
    activeCount := len(as.nodeManager.activeNodes)
    if activeCount <= as.config.MinNodes {
        log.Println("Already at minimum node count")
        return
    }
    
    // 选择要移除的节点（负载最低的）
    nodeToRemove := as.selectNodeToRemove()
    if nodeToRemove == "" {
        return
    }
    
    // 数据迁移
    if err := as.migrateData(nodeToRemove); err != nil {
        log.Printf("Failed to migrate data from node %s: %v", nodeToRemove, err)
        return
    }
    
    // 从代理中移除
    as.proxy.RemoveNode(nodeToRemove)
    delete(as.nodeManager.activeNodes, nodeToRemove)
    
    // 停止节点
    as.nodeManager.stopNode(nodeToRemove)
    
    log.Printf("Scaled down: removed node %s", nodeToRemove)
}

// 数据迁移
func (as *AutoScaler) migrateData(fromNode string) error {
    // 获取节点上的所有键
    keys, err := as.getNodeKeys(fromNode)
    if err != nil {
        return err
    }
    
    // 批量迁移数据
    batchSize := 1000
    for i := 0; i < len(keys); i += batchSize {
        end := i + batchSize
        if end > len(keys) {
            end = len(keys)
        }
        
        batch := keys[i:end]
        if err := as.migrateBatch(fromNode, batch); err != nil {
            return err
        }
    }
    
    return nil
}

func (as *AutoScaler) migrateBatch(fromNode string, keys []string) error {
    fromClient := as.proxy.clients[fromNode]
    
    for _, key := range keys {
        // 获取数据
        value, err := fromClient.Get(context.Background(), key).Result()
        if err != nil {
            continue // 键可能已过期
        }
        
        // 获取TTL
        ttl, _ := fromClient.TTL(context.Background(), key).Result()
        
        // 写入新节点
        newNode := as.proxy.consistentHash.GetNode(key)
        if newNode != fromNode {
            newClient := as.proxy.clients[newNode]
            newClient.Set(context.Background(), key, value, ttl)
        }
        
        // 从原节点删除
        fromClient.Del(context.Background(), key)
    }
    
    return nil
}
```

---

## 6. 部署与配置

### 6.1 Docker部署

#### Dockerfile
```dockerfile
FROM golang:1.19-alpine AS builder

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o redis-proxy ./cmd/proxy

FROM alpine:latest
RUN apk --no-cache add ca-certificates
WORKDIR /root/

COPY --from=builder /app/redis-proxy .
COPY --from=builder /app/config.yaml .

EXPOSE 6379
CMD ["./redis-proxy", "-config", "config.yaml"]
```

#### Docker Compose
```yaml
version: '3.8'

services:
  # Redis集群节点
  redis-node-1:
    image: redis:7-alpine
    ports:
      - "7001:6379"
    volumes:
      - ./redis-node-1.conf:/usr/local/etc/redis/redis.conf
      - redis-node-1-data:/data
    command: redis-server /usr/local/etc/redis/redis.conf
    networks:
      - redis-cluster

  redis-node-2:
    image: redis:7-alpine
    ports:
      - "7002:6379"
    volumes:
      - ./redis-node-2.conf:/usr/local/etc/redis/redis.conf
      - redis-node-2-data:/data
    command: redis-server /usr/local/etc/redis/redis.conf
    networks:
      - redis-cluster

  redis-node-3:
    image: redis:7-alpine
    ports:
      - "7003:6379"
    volumes:
      - ./redis-node-3.conf:/usr/local/etc/redis/redis.conf
      - redis-node-3-data:/data
    command: redis-server /usr/local/etc/redis/redis.conf
    networks:
      - redis-cluster

  # Redis代理
  redis-proxy-1:
    build: .
    ports:
      - "6379:6379"
    volumes:
      - ./proxy-config.yaml:/root/config.yaml
    depends_on:
      - redis-node-1
      - redis-node-2
      - redis-node-3
    networks:
      - redis-cluster

  redis-proxy-2:
    build: .
    ports:
      - "6380:6379"
    volumes:
      - ./proxy-config.yaml:/root/config.yaml
    depends_on:
      - redis-node-1
      - redis-node-2
      - redis-node-3
    networks:
      - redis-cluster

  # 负载均衡器
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - redis-proxy-1
      - redis-proxy-2
    networks:
      - redis-cluster

  # 监控
  prometheus:
    image: prom/prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    networks:
      - redis-cluster

  grafana:
    image: grafana/grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana-data:/var/lib/grafana
    networks:
      - redis-cluster

volumes:
  redis-node-1-data:
  redis-node-2-data:
  redis-node-3-data:
  grafana-data:

networks:
  redis-cluster:
    driver: bridge
```

### 6.2 配置文件

#### 代理配置
```yaml
# proxy-config.yaml
server:
  listen_addr: ":6379"
  read_timeout: 5s
  write_timeout: 5s
  max_connections: 10000

redis:
  nodes:
    - name: "node-1"
      addr: "redis-node-1:6379"
      weight: 1
      db: 0
    - name: "node-2"
      addr: "redis-node-2:6379"
      weight: 1
      db: 0
    - name: "node-3"
      addr: "redis-node-3:6379"
      weight: 1
      db: 0
  
  replicas: 160  # 虚拟节点数量
  conn_timeout: 5s
  read_timeout: 3s
  write_timeout: 3s
  max_retries: 3
  pool_size: 100

health_check:
  interval: 30s
  timeout: 5s

hot_key:
  threshold: 1000    # 热点阈值
  window: 60s        # 统计窗口
  local_cache_size: 10000
  local_cache_ttl: 300s

auto_scale:
  enabled: true
  min_nodes: 3
  max_nodes: 10
  scale_up_threshold: 0.8
  scale_down_threshold: 0.3
  cooldown_period: 300s
  check_interval: 60s

monitoring:
  enabled: true
  metrics_addr: ":8080"
  log_level: "info"

logging:
  level: "info"
  format: "json"
  output: "stdout"
```

#### Redis节点配置
```conf
# redis-node-1.conf
port 6379
bind 0.0.0.0

# 内存配置
maxmemory 2gb
maxmemory-policy allkeys-lru

# 持久化配置
save 900 1
save 300 10
save 60 10000

rdbcompression yes
rdbchecksum yes
dbfilename dump.rdb
dir /data

# AOF配置
appendonly yes
appendfilename "appendonly.aof"
appendfsync everysec

# 网络配置
tcp-keepalive 300
timeout 0

# 安全配置
# requirepass your_password_here

# 日志配置
loglevel notice
logfile ""

# 客户端配置
maxclients 10000

# 慢查询配置
slowlog-log-slower-than 10000
slowlog-max-len 128
```

---

## 7. 性能测试

### 7.1 基准测试

#### 测试脚本
```go
package main

import (
    "context"
    "fmt"
    "log"
    "math/rand"
    "sync"
    "time"
    
    "github.com/go-redis/redis/v8"
)

type BenchmarkConfig struct {
    Clients     int
    Requests    int
    KeySize     int
    ValueSize   int
    ReadRatio   float64
    TestDuration time.Duration
}

type BenchmarkResult struct {
    TotalRequests int64
    TotalErrors   int64
    TotalLatency  time.Duration
    MinLatency    time.Duration
    MaxLatency    time.Duration
    P50Latency    time.Duration
    P95Latency    time.Duration
    P99Latency    time.Duration
    QPS           float64
}

func main() {
    config := &BenchmarkConfig{
        Clients:      100,
        Requests:     100000,
        KeySize:      16,
        ValueSize:    1024,
        ReadRatio:    0.8,
        TestDuration: 60 * time.Second,
    }
    
    // 连接Redis代理
    client := redis.NewClient(&redis.Options{
        Addr: "localhost:6379",
    })
    
    result := runBenchmark(client, config)
    printResult(result)
}

func runBenchmark(client *redis.Client, config *BenchmarkConfig) *BenchmarkResult {
    var wg sync.WaitGroup
    var totalRequests, totalErrors int64
    latencies := make([]time.Duration, 0, config.Requests)
    var latencyMutex sync.Mutex
    
    startTime := time.Now()
    
    // 启动多个客户端
    for i := 0; i < config.Clients; i++ {
        wg.Add(1)
        go func(clientID int) {
            defer wg.Done()
            
            requestsPerClient := config.Requests / config.Clients
            for j := 0; j < requestsPerClient; j++ {
                key := generateKey(config.KeySize)
                
                var err error
                var latency time.Duration
                
                if rand.Float64() < config.ReadRatio {
                    // 读操作
                    latency, err = measureLatency(func() error {
                        _, err := client.Get(context.Background(), key).Result()
                        if err == redis.Nil {
                            return nil // 键不存在不算错误
                        }
                        return err
                    })
                } else {
                    // 写操作
                    value := generateValue(config.ValueSize)
                    latency, err = measureLatency(func() error {
                        return client.Set(context.Background(), key, value, time.Hour).Err()
                    })
                }
                
                atomic.AddInt64(&totalRequests, 1)
                if err != nil {
                    atomic.AddInt64(&totalErrors, 1)
                }
                
                latencyMutex.Lock()
                latencies = append(latencies, latency)
                latencyMutex.Unlock()
            }
        }(i)
    }
    
    wg.Wait()
    endTime := time.Now()
    
    // 计算统计信息
    sort.Slice(latencies, func(i, j int) bool {
        return latencies[i] < latencies[j]
    })
    
    var totalLatency time.Duration
    for _, lat := range latencies {
        totalLatency += lat
    }
    
    result := &BenchmarkResult{
        TotalRequests: totalRequests,
        TotalErrors:   totalErrors,
        TotalLatency:  totalLatency,
        MinLatency:    latencies[0],
        MaxLatency:    latencies[len(latencies)-1],
        P50Latency:    latencies[len(latencies)*50/100],
        P95Latency:    latencies[len(latencies)*95/100],
        P99Latency:    latencies[len(latencies)*99/100],
        QPS:           float64(totalRequests) / endTime.Sub(startTime).Seconds(),
    }
    
    return result
}

func measureLatency(operation func() error) (time.Duration, error) {
    start := time.Now()
    err := operation()
    return time.Since(start), err
}

func generateKey(size int) string {
    const charset = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    b := make([]byte, size)
    for i := range b {
        b[i] = charset[rand.Intn(len(charset))]
    }
    return string(b)
}

func generateValue(size int) string {
    return strings.Repeat("x", size)
}

func printResult(result *BenchmarkResult) {
    fmt.Printf("Benchmark Results:\n")
    fmt.Printf("Total Requests: %d\n", result.TotalRequests)
    fmt.Printf("Total Errors: %d\n", result.TotalErrors)
    fmt.Printf("Error Rate: %.2f%%\n", float64(result.TotalErrors)/float64(result.TotalRequests)*100)
    fmt.Printf("QPS: %.2f\n", result.QPS)
    fmt.Printf("Average Latency: %v\n", result.TotalLatency/time.Duration(result.TotalRequests))
    fmt.Printf("Min Latency: %v\n", result.MinLatency)
    fmt.Printf("Max Latency: %v\n", result.MaxLatency)
    fmt.Printf("P50 Latency: %v\n", result.P50Latency)
    fmt.Printf("P95 Latency: %v\n", result.P95Latency)
    fmt.Printf("P99 Latency: %v\n", result.P99Latency)
}
```

---

## 8. 总结

### 8.1 架构优势

1. **高性能**: 一致性哈希算法确保数据均匀分布，避免热点
2. **高可用**: 多副本机制，故障自动转移
3. **可扩展**: 支持动态扩缩容，最小化数据迁移
4. **智能路由**: 基于一致性哈希的智能请求路由
5. **多级缓存**: 本地缓存 + 分布式缓存，提升命中率

### 8.2 关键技术

- **一致性哈希**: 解决数据分片和负载均衡问题
- **虚拟节点**: 提高数据分布的均匀性
- **热点检测**: 自动识别和缓存热点数据
- **故障恢复**: 快速故障检测和自动恢复
- **监控告警**: 全方位的性能监控和告警

### 8.3 性能指标

- **QPS**: 100万+
- **延迟**: P99 < 1ms
- **可用性**: 99.99%
- **扩展性**: 支持1000+节点
- **数据迁移**: 扩缩容时 < 5%数据迁移

通过以上设计，可以构建一个高性能、高可用、可扩展的分布式缓存系统，满足大规模互联网应用的缓存需求。