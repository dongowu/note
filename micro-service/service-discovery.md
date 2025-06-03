# 服务注册与发现（Service Discovery）

## 1. 服务注册与发现概述

### 1.1 定义与核心概念

服务注册与发现是微服务架构中的核心组件，负责管理服务实例的生命周期，提供服务位置信息的动态查询能力。

**核心概念**：
- **服务注册（Service Registration）**：服务实例启动时向注册中心注册自己的网络位置信息
- **服务发现（Service Discovery）**：客户端通过注册中心查找目标服务的可用实例
- **健康检查（Health Check）**：定期检查服务实例的健康状态，自动剔除不健康实例
- **负载均衡（Load Balancing）**：在多个服务实例间分配请求负载

### 1.2 架构模式

**1. 客户端发现模式（Client-Side Discovery）**
- 客户端直接查询服务注册表
- 客户端负责选择可用实例和负载均衡
- 优点：简单直接，性能好
- 缺点：客户端逻辑复杂，与注册中心耦合

**2. 服务端发现模式（Server-Side Discovery）**
- 客户端通过负载均衡器访问服务
- 负载均衡器查询服务注册表
- 优点：客户端简单，语言无关
- 缺点：增加网络跳数，负载均衡器成为瓶颈

**3. 服务网格模式（Service Mesh）**
- 通过Sidecar代理处理服务发现
- 对应用透明，功能丰富
- 优点：功能强大，对应用无侵入
- 缺点：复杂度高，资源开销大

## 2. 核心功能实现

### 2.1 基于etcd的服务注册与发现

#### 服务注册实现

```go
package discovery

import (
    "context"
    "encoding/json"
    "fmt"
    "log"
    "sync"
    "time"
    
    "go.etcd.io/etcd/clientv3"
)

// ServiceInstance 服务实例信息
type ServiceInstance struct {
    ID       string            `json:"id"`
    Name     string            `json:"name"`
    Version  string            `json:"version"`
    Address  string            `json:"address"`
    Port     int               `json:"port"`
    Metadata map[string]string `json:"metadata"`
    Health   HealthStatus      `json:"health"`
    RegisterTime time.Time     `json:"register_time"`
}

// HealthStatus 健康状态
type HealthStatus struct {
    Status    string    `json:"status"`
    LastCheck time.Time `json:"last_check"`
    Message   string    `json:"message"`
}

// ServiceRegistry 服务注册器
type ServiceRegistry struct {
    client       *clientv3.Client
    leaseID      clientv3.LeaseID
    keepAliveCh  <-chan *clientv3.LeaseKeepAliveResponse
    key          string
    value        string
    ttl          int64
    mutex        sync.RWMutex
    registered   bool
}

// NewServiceRegistry 创建服务注册器
func NewServiceRegistry(endpoints []string, ttl int64) (*ServiceRegistry, error) {
    client, err := clientv3.New(clientv3.Config{
        Endpoints:   endpoints,
        DialTimeout: 5 * time.Second,
    })
    if err != nil {
        return nil, fmt.Errorf("failed to create etcd client: %v", err)
    }
    
    return &ServiceRegistry{
        client: client,
        ttl:    ttl,
    }, nil
}

// Register 注册服务
func (sr *ServiceRegistry) Register(ctx context.Context, instance *ServiceInstance) error {
    sr.mutex.Lock()
    defer sr.mutex.Unlock()
    
    // 序列化服务实例信息
    instanceData, err := json.Marshal(instance)
    if err != nil {
        return fmt.Errorf("failed to marshal instance: %v", err)
    }
    
    // 创建租约
    lease, err := sr.client.Grant(ctx, sr.ttl)
    if err != nil {
        return fmt.Errorf("failed to create lease: %v", err)
    }
    
    sr.leaseID = lease.ID
    sr.key = fmt.Sprintf("/services/%s/%s", instance.Name, instance.ID)
    sr.value = string(instanceData)
    
    // 注册服务实例
    _, err = sr.client.Put(ctx, sr.key, sr.value, clientv3.WithLease(sr.leaseID))
    if err != nil {
        return fmt.Errorf("failed to register service: %v", err)
    }
    
    // 启动租约续期
    sr.keepAliveCh, err = sr.client.KeepAlive(ctx, sr.leaseID)
    if err != nil {
        return fmt.Errorf("failed to keep alive lease: %v", err)
    }
    
    sr.registered = true
    
    // 启动续期监听
    go sr.listenKeepAlive()
    
    log.Printf("Service registered: %s at %s:%d", instance.Name, instance.Address, instance.Port)
    return nil
}

// listenKeepAlive 监听租约续期
func (sr *ServiceRegistry) listenKeepAlive() {
    for ka := range sr.keepAliveCh {
        if ka == nil {
            log.Println("Keep alive channel closed")
            break
        }
        // log.Printf("Lease renewed: %d", ka.ID)
    }
}

// Deregister 注销服务
func (sr *ServiceRegistry) Deregister(ctx context.Context) error {
    sr.mutex.Lock()
    defer sr.mutex.Unlock()
    
    if !sr.registered {
        return nil
    }
    
    // 撤销租约
    _, err := sr.client.Revoke(ctx, sr.leaseID)
    if err != nil {
        log.Printf("Failed to revoke lease: %v", err)
    }
    
    // 删除服务键
    _, err = sr.client.Delete(ctx, sr.key)
    if err != nil {
        log.Printf("Failed to delete service key: %v", err)
    }
    
    sr.registered = false
    log.Println("Service deregistered")
    return err
}

// UpdateHealth 更新健康状态
func (sr *ServiceRegistry) UpdateHealth(ctx context.Context, health HealthStatus) error {
    sr.mutex.Lock()
    defer sr.mutex.Unlock()
    
    if !sr.registered {
        return fmt.Errorf("service not registered")
    }
    
    // 获取当前服务实例信息
    resp, err := sr.client.Get(ctx, sr.key)
    if err != nil {
        return fmt.Errorf("failed to get current instance: %v", err)
    }
    
    if len(resp.Kvs) == 0 {
        return fmt.Errorf("service instance not found")
    }
    
    var instance ServiceInstance
    err = json.Unmarshal(resp.Kvs[0].Value, &instance)
    if err != nil {
        return fmt.Errorf("failed to unmarshal instance: %v", err)
    }
    
    // 更新健康状态
    instance.Health = health
    
    // 序列化并更新
    instanceData, err := json.Marshal(instance)
    if err != nil {
        return fmt.Errorf("failed to marshal instance: %v", err)
    }
    
    _, err = sr.client.Put(ctx, sr.key, string(instanceData), clientv3.WithLease(sr.leaseID))
    if err != nil {
        return fmt.Errorf("failed to update health: %v", err)
    }
    
    return nil
}

// Close 关闭注册器
func (sr *ServiceRegistry) Close() error {
    return sr.client.Close()
}
```

#### 服务发现实现

```go
// ServiceDiscovery 服务发现器
type ServiceDiscovery struct {
    client    *clientv3.Client
    cache     map[string][]*ServiceInstance
    watchers  map[string]clientv3.WatchChan
    mutex     sync.RWMutex
    callbacks map[string][]ServiceChangeCallback
}

// ServiceChangeCallback 服务变更回调
type ServiceChangeCallback func(serviceName string, instances []*ServiceInstance)

// NewServiceDiscovery 创建服务发现器
func NewServiceDiscovery(endpoints []string) (*ServiceDiscovery, error) {
    client, err := clientv3.New(clientv3.Config{
        Endpoints:   endpoints,
        DialTimeout: 5 * time.Second,
    })
    if err != nil {
        return nil, fmt.Errorf("failed to create etcd client: %v", err)
    }
    
    return &ServiceDiscovery{
        client:    client,
        cache:     make(map[string][]*ServiceInstance),
        watchers:  make(map[string]clientv3.WatchChan),
        callbacks: make(map[string][]ServiceChangeCallback),
    }, nil
}

// DiscoverServices 发现服务实例
func (sd *ServiceDiscovery) DiscoverServices(ctx context.Context, serviceName string) ([]*ServiceInstance, error) {
    sd.mutex.RLock()
    if instances, exists := sd.cache[serviceName]; exists {
        sd.mutex.RUnlock()
        return instances, nil
    }
    sd.mutex.RUnlock()
    
    // 从etcd获取服务实例
    key := fmt.Sprintf("/services/%s/", serviceName)
    resp, err := sd.client.Get(ctx, key, clientv3.WithPrefix())
    if err != nil {
        return nil, fmt.Errorf("failed to get services: %v", err)
    }
    
    instances := make([]*ServiceInstance, 0, len(resp.Kvs))
    for _, kv := range resp.Kvs {
        var instance ServiceInstance
        err := json.Unmarshal(kv.Value, &instance)
        if err != nil {
            log.Printf("Failed to unmarshal instance: %v", err)
            continue
        }
        
        // 只返回健康的实例
        if instance.Health.Status == "healthy" {
            instances = append(instances, &instance)
        }
    }
    
    // 更新缓存
    sd.mutex.Lock()
    sd.cache[serviceName] = instances
    sd.mutex.Unlock()
    
    // 启动监听
    sd.watchService(serviceName)
    
    return instances, nil
}

// watchService 监听服务变更
func (sd *ServiceDiscovery) watchService(serviceName string) {
    sd.mutex.Lock()
    if _, exists := sd.watchers[serviceName]; exists {
        sd.mutex.Unlock()
        return
    }
    
    key := fmt.Sprintf("/services/%s/", serviceName)
    watchCh := sd.client.Watch(context.Background(), key, clientv3.WithPrefix())
    sd.watchers[serviceName] = watchCh
    sd.mutex.Unlock()
    
    go func() {
        for watchResp := range watchCh {
            for _, event := range watchResp.Events {
                sd.handleServiceChange(serviceName, event)
            }
        }
    }()
}

// handleServiceChange 处理服务变更
func (sd *ServiceDiscovery) handleServiceChange(serviceName string, event *clientv3.Event) {
    // 重新获取服务实例列表
    ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
    defer cancel()
    
    key := fmt.Sprintf("/services/%s/", serviceName)
    resp, err := sd.client.Get(ctx, key, clientv3.WithPrefix())
    if err != nil {
        log.Printf("Failed to refresh service instances: %v", err)
        return
    }
    
    instances := make([]*ServiceInstance, 0, len(resp.Kvs))
    for _, kv := range resp.Kvs {
        var instance ServiceInstance
        err := json.Unmarshal(kv.Value, &instance)
        if err != nil {
            log.Printf("Failed to unmarshal instance: %v", err)
            continue
        }
        
        if instance.Health.Status == "healthy" {
            instances = append(instances, &instance)
        }
    }
    
    // 更新缓存
    sd.mutex.Lock()
    sd.cache[serviceName] = instances
    callbacks := sd.callbacks[serviceName]
    sd.mutex.Unlock()
    
    // 触发回调
    for _, callback := range callbacks {
        go callback(serviceName, instances)
    }
    
    log.Printf("Service %s instances updated: %d healthy instances", serviceName, len(instances))
}

// RegisterCallback 注册服务变更回调
func (sd *ServiceDiscovery) RegisterCallback(serviceName string, callback ServiceChangeCallback) {
    sd.mutex.Lock()
    defer sd.mutex.Unlock()
    
    if sd.callbacks[serviceName] == nil {
        sd.callbacks[serviceName] = make([]ServiceChangeCallback, 0)
    }
    sd.callbacks[serviceName] = append(sd.callbacks[serviceName], callback)
}

// GetHealthyInstances 获取健康的服务实例
func (sd *ServiceDiscovery) GetHealthyInstances(serviceName string) []*ServiceInstance {
    sd.mutex.RLock()
    defer sd.mutex.RUnlock()
    
    instances := sd.cache[serviceName]
    healthy := make([]*ServiceInstance, 0, len(instances))
    
    for _, instance := range instances {
        if instance.Health.Status == "healthy" {
            healthy = append(healthy, instance)
        }
    }
    
    return healthy
}

// Close 关闭服务发现器
func (sd *ServiceDiscovery) Close() error {
    sd.mutex.Lock()
    defer sd.mutex.Unlock()
    
    // 关闭所有监听器
    for _, watchCh := range sd.watchers {
        // watchCh会在client关闭时自动关闭
    }
    
    return sd.client.Close()
}
```

### 2.2 健康检查机制

```go
package healthcheck

import (
    "context"
    "fmt"
    "log"
    "net/http"
    "sync"
    "time"
)

// HealthChecker 健康检查器
type HealthChecker struct {
    registry    *ServiceRegistry
    checkURL    string
    interval    time.Duration
    timeout     time.Duration
    client      *http.Client
    stopCh      chan struct{}
    running     bool
    mutex       sync.RWMutex
}

// HealthCheckConfig 健康检查配置
type HealthCheckConfig struct {
    URL      string
    Interval time.Duration
    Timeout  time.Duration
}

// NewHealthChecker 创建健康检查器
func NewHealthChecker(registry *ServiceRegistry, config HealthCheckConfig) *HealthChecker {
    return &HealthChecker{
        registry: registry,
        checkURL: config.URL,
        interval: config.Interval,
        timeout:  config.Timeout,
        client: &http.Client{
            Timeout: config.Timeout,
        },
        stopCh: make(chan struct{}),
    }
}

// Start 启动健康检查
func (hc *HealthChecker) Start() {
    hc.mutex.Lock()
    if hc.running {
        hc.mutex.Unlock()
        return
    }
    hc.running = true
    hc.mutex.Unlock()
    
    go hc.checkLoop()
    log.Println("Health checker started")
}

// Stop 停止健康检查
func (hc *HealthChecker) Stop() {
    hc.mutex.Lock()
    defer hc.mutex.Unlock()
    
    if !hc.running {
        return
    }
    
    close(hc.stopCh)
    hc.running = false
    log.Println("Health checker stopped")
}

// checkLoop 健康检查循环
func (hc *HealthChecker) checkLoop() {
    ticker := time.NewTicker(hc.interval)
    defer ticker.Stop()
    
    for {
        select {
        case <-ticker.C:
            hc.performHealthCheck()
        case <-hc.stopCh:
            return
        }
    }
}

// performHealthCheck 执行健康检查
func (hc *HealthChecker) performHealthCheck() {
    ctx, cancel := context.WithTimeout(context.Background(), hc.timeout)
    defer cancel()
    
    req, err := http.NewRequestWithContext(ctx, "GET", hc.checkURL, nil)
    if err != nil {
        hc.updateHealthStatus("unhealthy", fmt.Sprintf("Failed to create request: %v", err))
        return
    }
    
    resp, err := hc.client.Do(req)
    if err != nil {
        hc.updateHealthStatus("unhealthy", fmt.Sprintf("Request failed: %v", err))
        return
    }
    defer resp.Body.Close()
    
    if resp.StatusCode >= 200 && resp.StatusCode < 300 {
        hc.updateHealthStatus("healthy", "OK")
    } else {
        hc.updateHealthStatus("unhealthy", fmt.Sprintf("HTTP %d", resp.StatusCode))
    }
}

// updateHealthStatus 更新健康状态
func (hc *HealthChecker) updateHealthStatus(status, message string) {
    health := HealthStatus{
        Status:    status,
        LastCheck: time.Now(),
        Message:   message,
    }
    
    ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
    defer cancel()
    
    err := hc.registry.UpdateHealth(ctx, health)
    if err != nil {
        log.Printf("Failed to update health status: %v", err)
    }
}
```

### 2.3 负载均衡算法

```go
package loadbalancer

import (
    "hash/crc32"
    "math/rand"
    "sort"
    "sync"
    "sync/atomic"
    "time"
)

// LoadBalancer 负载均衡器接口
type LoadBalancer interface {
    Select(instances []*ServiceInstance) *ServiceInstance
    Name() string
}

// RoundRobinBalancer 轮询负载均衡器
type RoundRobinBalancer struct {
    counter uint64
}

// NewRoundRobinBalancer 创建轮询负载均衡器
func NewRoundRobinBalancer() *RoundRobinBalancer {
    return &RoundRobinBalancer{}
}

// Select 选择服务实例
func (rrb *RoundRobinBalancer) Select(instances []*ServiceInstance) *ServiceInstance {
    if len(instances) == 0 {
        return nil
    }
    
    index := atomic.AddUint64(&rrb.counter, 1) % uint64(len(instances))
    return instances[index]
}

// Name 返回负载均衡器名称
func (rrb *RoundRobinBalancer) Name() string {
    return "round_robin"
}

// WeightedRoundRobinBalancer 加权轮询负载均衡器
type WeightedRoundRobinBalancer struct {
    instances []*WeightedInstance
    mutex     sync.Mutex
}

// WeightedInstance 加权实例
type WeightedInstance struct {
    Instance      *ServiceInstance
    Weight        int
    CurrentWeight int
}

// NewWeightedRoundRobinBalancer 创建加权轮询负载均衡器
func NewWeightedRoundRobinBalancer() *WeightedRoundRobinBalancer {
    return &WeightedRoundRobinBalancer{}
}

// Select 选择服务实例
func (wrrb *WeightedRoundRobinBalancer) Select(instances []*ServiceInstance) *ServiceInstance {
    if len(instances) == 0 {
        return nil
    }
    
    wrrb.mutex.Lock()
    defer wrrb.mutex.Unlock()
    
    // 初始化加权实例
    if len(wrrb.instances) != len(instances) {
        wrrb.instances = make([]*WeightedInstance, len(instances))
        for i, instance := range instances {
            weight := 1
            if w, exists := instance.Metadata["weight"]; exists {
                if parsed, err := strconv.Atoi(w); err == nil && parsed > 0 {
                    weight = parsed
                }
            }
            wrrb.instances[i] = &WeightedInstance{
                Instance:      instance,
                Weight:        weight,
                CurrentWeight: 0,
            }
        }
    }
    
    // 加权轮询算法
    totalWeight := 0
    var selected *WeightedInstance
    
    for _, wi := range wrrb.instances {
        wi.CurrentWeight += wi.Weight
        totalWeight += wi.Weight
        
        if selected == nil || wi.CurrentWeight > selected.CurrentWeight {
            selected = wi
        }
    }
    
    if selected != nil {
        selected.CurrentWeight -= totalWeight
        return selected.Instance
    }
    
    return instances[0]
}

// Name 返回负载均衡器名称
func (wrrb *WeightedRoundRobinBalancer) Name() string {
    return "weighted_round_robin"
}

// RandomBalancer 随机负载均衡器
type RandomBalancer struct {
    rand *rand.Rand
    mutex sync.Mutex
}

// NewRandomBalancer 创建随机负载均衡器
func NewRandomBalancer() *RandomBalancer {
    return &RandomBalancer{
        rand: rand.New(rand.NewSource(time.Now().UnixNano())),
    }
}

// Select 选择服务实例
func (rb *RandomBalancer) Select(instances []*ServiceInstance) *ServiceInstance {
    if len(instances) == 0 {
        return nil
    }
    
    rb.mutex.Lock()
    index := rb.rand.Intn(len(instances))
    rb.mutex.Unlock()
    
    return instances[index]
}

// Name 返回负载均衡器名称
func (rb *RandomBalancer) Name() string {
    return "random"
}

// ConsistentHashBalancer 一致性哈希负载均衡器
type ConsistentHashBalancer struct {
    hashRing map[uint32]*ServiceInstance
    sortedHashes []uint32
    virtualNodes int
    mutex        sync.RWMutex
}

// NewConsistentHashBalancer 创建一致性哈希负载均衡器
func NewConsistentHashBalancer(virtualNodes int) *ConsistentHashBalancer {
    return &ConsistentHashBalancer{
        hashRing:     make(map[uint32]*ServiceInstance),
        virtualNodes: virtualNodes,
    }
}

// Select 选择服务实例
func (chb *ConsistentHashBalancer) Select(instances []*ServiceInstance) *ServiceInstance {
    if len(instances) == 0 {
        return nil
    }
    
    chb.mutex.Lock()
    chb.buildHashRing(instances)
    chb.mutex.Unlock()
    
    // 使用请求的某个特征作为哈希键（这里简化为随机）
    key := fmt.Sprintf("request_%d", time.Now().UnixNano())
    hash := crc32.ChecksumIEEE([]byte(key))
    
    chb.mutex.RLock()
    defer chb.mutex.RUnlock()
    
    // 找到第一个大于等于hash的节点
    idx := sort.Search(len(chb.sortedHashes), func(i int) bool {
        return chb.sortedHashes[i] >= hash
    })
    
    if idx == len(chb.sortedHashes) {
        idx = 0
    }
    
    return chb.hashRing[chb.sortedHashes[idx]]
}

// buildHashRing 构建哈希环
func (chb *ConsistentHashBalancer) buildHashRing(instances []*ServiceInstance) {
    chb.hashRing = make(map[uint32]*ServiceInstance)
    chb.sortedHashes = make([]uint32, 0)
    
    for _, instance := range instances {
        for i := 0; i < chb.virtualNodes; i++ {
            virtualKey := fmt.Sprintf("%s:%d#%d", instance.Address, instance.Port, i)
            hash := crc32.ChecksumIEEE([]byte(virtualKey))
            chb.hashRing[hash] = instance
            chb.sortedHashes = append(chb.sortedHashes, hash)
        }
    }
    
    sort.Slice(chb.sortedHashes, func(i, j int) bool {
        return chb.sortedHashes[i] < chb.sortedHashes[j]
    })
}

// Name 返回负载均衡器名称
func (chb *ConsistentHashBalancer) Name() string {
    return "consistent_hash"
}

// LeastConnectionsBalancer 最少连接数负载均衡器
type LeastConnectionsBalancer struct {
    connections map[string]int64
    mutex       sync.RWMutex
}

// NewLeastConnectionsBalancer 创建最少连接数负载均衡器
func NewLeastConnectionsBalancer() *LeastConnectionsBalancer {
    return &LeastConnectionsBalancer{
        connections: make(map[string]int64),
    }
}

// Select 选择服务实例
func (lcb *LeastConnectionsBalancer) Select(instances []*ServiceInstance) *ServiceInstance {
    if len(instances) == 0 {
        return nil
    }
    
    lcb.mutex.RLock()
    defer lcb.mutex.RUnlock()
    
    var selected *ServiceInstance
    minConnections := int64(-1)
    
    for _, instance := range instances {
        key := fmt.Sprintf("%s:%d", instance.Address, instance.Port)
        connections := lcb.connections[key]
        
        if minConnections == -1 || connections < minConnections {
            minConnections = connections
            selected = instance
        }
    }
    
    return selected
}

// IncrementConnections 增加连接数
func (lcb *LeastConnectionsBalancer) IncrementConnections(instance *ServiceInstance) {
    key := fmt.Sprintf("%s:%d", instance.Address, instance.Port)
    lcb.mutex.Lock()
    lcb.connections[key]++
    lcb.mutex.Unlock()
}

// DecrementConnections 减少连接数
func (lcb *LeastConnectionsBalancer) DecrementConnections(instance *ServiceInstance) {
    key := fmt.Sprintf("%s:%d", instance.Address, instance.Port)
    lcb.mutex.Lock()
    if lcb.connections[key] > 0 {
        lcb.connections[key]--
    }
    lcb.mutex.Unlock()
}

// Name 返回负载均衡器名称
func (lcb *LeastConnectionsBalancer) Name() string {
    return "least_connections"
}
```

## 3. 主流服务发现方案对比

### 3.1 技术方案对比

| 特性 | Consul | etcd | Eureka | Zookeeper | Nacos |
|------|--------|------|--------|-----------|-------|
| **一致性模型** | CP | CP | AP | CP | CP/AP |
| **健康检查** | 内置 | 外部 | 内置 | 外部 | 内置 |
| **多数据中心** | 支持 | 不支持 | 不支持 | 不支持 | 支持 |
| **服务网格** | Connect | 不支持 | 不支持 | 不支持 | 不支持 |
| **配置管理** | KV存储 | KV存储 | 不支持 | 支持 | 支持 |
| **负载均衡** | 客户端 | 客户端 | 客户端 | 客户端 | 客户端 |
| **语言支持** | 多语言 | 多语言 | Java为主 | 多语言 | 多语言 |
| **运维复杂度** | 中等 | 低 | 低 | 高 | 中等 |
| **性能** | 高 | 高 | 中等 | 高 | 高 |

### 3.2 选型建议

**Consul**：
- 需要多数据中心支持
- 要求内置健康检查
- 计划使用服务网格
- 对运维复杂度要求不高

**etcd**：
- Kubernetes环境
- 对一致性要求高
- 运维团队熟悉etcd
- 需要简单可靠的方案

**Eureka**：
- Spring Cloud生态
- Java技术栈
- 对可用性要求高于一致性
- 网络分区容忍性要求高

**Nacos**：
- 阿里云环境
- 需要配置管理功能
- 中文文档和社区支持
- 动态配置推送需求

## 4. 生产环境最佳实践

### 4.1 高可用部署

#### 集群部署配置

```yaml
# etcd集群部署示例
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: etcd
spec:
  serviceName: etcd
  replicas: 3
  selector:
    matchLabels:
      app: etcd
  template:
    metadata:
      labels:
        app: etcd
    spec:
      containers:
      - name: etcd
        image: quay.io/coreos/etcd:v3.5.0
        ports:
        - containerPort: 2379
          name: client
        - containerPort: 2380
          name: peer
        env:
        - name: ETCD_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: ETCD_INITIAL_CLUSTER
          value: "etcd-0=http://etcd-0.etcd:2380,etcd-1=http://etcd-1.etcd:2380,etcd-2=http://etcd-2.etcd:2380"
        - name: ETCD_INITIAL_CLUSTER_STATE
          value: "new"
        - name: ETCD_INITIAL_CLUSTER_TOKEN
          value: "etcd-cluster"
        - name: ETCD_LISTEN_CLIENT_URLS
          value: "http://0.0.0.0:2379"
        - name: ETCD_ADVERTISE_CLIENT_URLS
          value: "http://$(ETCD_NAME).etcd:2379"
        - name: ETCD_LISTEN_PEER_URLS
          value: "http://0.0.0.0:2380"
        - name: ETCD_INITIAL_ADVERTISE_PEER_URLS
          value: "http://$(ETCD_NAME).etcd:2380"
        volumeMounts:
        - name: etcd-data
          mountPath: /var/lib/etcd
  volumeClaimTemplates:
  - metadata:
      name: etcd-data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi
```

### 4.2 监控与告警

```go
package monitoring

import (
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
)

var (
    // 服务注册指标
    serviceRegistrations = promauto.NewCounterVec(
        prometheus.CounterOpts{
            Name: "service_registrations_total",
            Help: "Total number of service registrations",
        },
        []string{"service_name", "status"},
    )
    
    // 服务发现指标
    serviceDiscoveries = promauto.NewCounterVec(
        prometheus.CounterOpts{
            Name: "service_discoveries_total",
            Help: "Total number of service discoveries",
        },
        []string{"service_name"},
    )
    
    // 健康检查指标
    healthChecks = promauto.NewCounterVec(
        prometheus.CounterOpts{
            Name: "health_checks_total",
            Help: "Total number of health checks",
        },
        []string{"service_name", "status"},
    )
    
    // 服务实例数量
    serviceInstances = promauto.NewGaugeVec(
        prometheus.GaugeOpts{
            Name: "service_instances",
            Help: "Number of service instances",
        },
        []string{"service_name", "status"},
    )
    
    // 负载均衡选择
    loadBalancerSelections = promauto.NewCounterVec(
        prometheus.CounterOpts{
            Name: "load_balancer_selections_total",
            Help: "Total number of load balancer selections",
        },
        []string{"service_name", "algorithm", "instance"},
    )
)

// RecordServiceRegistration 记录服务注册
func RecordServiceRegistration(serviceName, status string) {
    serviceRegistrations.WithLabelValues(serviceName, status).Inc()
}

// RecordServiceDiscovery 记录服务发现
func RecordServiceDiscovery(serviceName string) {
    serviceDiscoveries.WithLabelValues(serviceName).Inc()
}

// RecordHealthCheck 记录健康检查
func RecordHealthCheck(serviceName, status string) {
    healthChecks.WithLabelValues(serviceName, status).Inc()
}

// UpdateServiceInstances 更新服务实例数量
func UpdateServiceInstances(serviceName, status string, count float64) {
    serviceInstances.WithLabelValues(serviceName, status).Set(count)
}

// RecordLoadBalancerSelection 记录负载均衡选择
func RecordLoadBalancerSelection(serviceName, algorithm, instance string) {
    loadBalancerSelections.WithLabelValues(serviceName, algorithm, instance).Inc()
}
```

### 4.3 故障处理与恢复

```go
package failover

import (
    "context"
    "log"
    "sync"
    "time"
)

// FailoverManager 故障转移管理器
type FailoverManager struct {
    primaryRegistry   *ServiceRegistry
    backupRegistries  []*ServiceRegistry
    currentRegistry   *ServiceRegistry
    healthChecker     *RegistryHealthChecker
    mutex             sync.RWMutex
    failoverCallback  func(from, to *ServiceRegistry)
}

// RegistryHealthChecker 注册中心健康检查器
type RegistryHealthChecker struct {
    registries map[*ServiceRegistry]bool
    mutex      sync.RWMutex
    interval   time.Duration
    timeout    time.Duration
}

// NewFailoverManager 创建故障转移管理器
func NewFailoverManager(primary *ServiceRegistry, backups []*ServiceRegistry) *FailoverManager {
    fm := &FailoverManager{
        primaryRegistry:  primary,
        backupRegistries: backups,
        currentRegistry:  primary,
        healthChecker: &RegistryHealthChecker{
            registries: make(map[*ServiceRegistry]bool),
            interval:   10 * time.Second,
            timeout:    5 * time.Second,
        },
    }
    
    // 初始化健康状态
    fm.healthChecker.registries[primary] = true
    for _, backup := range backups {
        fm.healthChecker.registries[backup] = true
    }
    
    return fm
}

// Start 启动故障转移管理器
func (fm *FailoverManager) Start() {
    go fm.healthChecker.start(fm)
}

// GetCurrentRegistry 获取当前可用的注册中心
func (fm *FailoverManager) GetCurrentRegistry() *ServiceRegistry {
    fm.mutex.RLock()
    defer fm.mutex.RUnlock()
    return fm.currentRegistry
}

// SetFailoverCallback 设置故障转移回调
func (fm *FailoverManager) SetFailoverCallback(callback func(from, to *ServiceRegistry)) {
    fm.failoverCallback = callback
}

// start 启动健康检查
func (rhc *RegistryHealthChecker) start(fm *FailoverManager) {
    ticker := time.NewTicker(rhc.interval)
    defer ticker.Stop()
    
    for range ticker.C {
        rhc.checkHealth(fm)
    }
}

// checkHealth 检查注册中心健康状态
func (rhc *RegistryHealthChecker) checkHealth(fm *FailoverManager) {
    rhc.mutex.Lock()
    defer rhc.mutex.Unlock()
    
    // 检查主注册中心
    primaryHealthy := rhc.isRegistryHealthy(fm.primaryRegistry)
    rhc.registries[fm.primaryRegistry] = primaryHealthy
    
    // 检查备份注册中心
    for _, backup := range fm.backupRegistries {
        healthy := rhc.isRegistryHealthy(backup)
        rhc.registries[backup] = healthy
    }
    
    // 决定是否需要故障转移
    fm.mutex.Lock()
    currentRegistry := fm.currentRegistry
    
    if !rhc.registries[currentRegistry] {
        // 当前注册中心不健康，寻找健康的替代
        var newRegistry *ServiceRegistry
        
        // 优先使用主注册中心
        if rhc.registries[fm.primaryRegistry] {
            newRegistry = fm.primaryRegistry
        } else {
            // 寻找健康的备份注册中心
            for _, backup := range fm.backupRegistries {
                if rhc.registries[backup] {
                    newRegistry = backup
                    break
                }
            }
        }
        
        if newRegistry != nil && newRegistry != currentRegistry {
            oldRegistry := fm.currentRegistry
            fm.currentRegistry = newRegistry
            fm.mutex.Unlock()
            
            log.Printf("Failover: switched from %v to %v", oldRegistry, newRegistry)
            
            if fm.failoverCallback != nil {
                fm.failoverCallback(oldRegistry, newRegistry)
            }
        } else {
            fm.mutex.Unlock()
        }
    } else {
        fm.mutex.Unlock()
    }
}

// isRegistryHealthy 检查注册中心是否健康
func (rhc *RegistryHealthChecker) isRegistryHealthy(registry *ServiceRegistry) bool {
    ctx, cancel := context.WithTimeout(context.Background(), rhc.timeout)
    defer cancel()
    
    // 尝试执行一个简单的操作来检查连接
    _, err := registry.client.Get(ctx, "/health-check")
    return err == nil
}
```

## 5. 面试要点总结

### 5.1 核心概念理解

**1. 服务注册与发现的作用？**
- **解耦服务位置**：客户端无需硬编码服务地址
- **动态扩缩容**：支持服务实例的动态增减
- **故障隔离**：自动剔除不健康的服务实例
- **负载分发**：在多个实例间分配请求负载

**2. 客户端发现vs服务端发现？**
- **客户端发现**：客户端直接查询注册中心，性能好但逻辑复杂
- **服务端发现**：通过负载均衡器代理，客户端简单但增加网络跳数
- **选择依据**：根据性能要求、客户端复杂度、语言支持等因素决定

### 5.2 技术实现细节

**1. 如何保证服务注册的一致性？**
- **强一致性**：使用CP系统（如etcd、Consul），保证数据一致但可能影响可用性
- **最终一致性**：使用AP系统（如Eureka），优先保证可用性
- **混合模式**：根据业务场景选择不同的一致性级别

**2. 健康检查的实现方式？**
- **主动检查**：注册中心定期检查服务实例
- **被动检查**：服务实例主动上报健康状态
- **心跳机制**：通过租约续期维持服务注册
- **多维度检查**：HTTP、TCP、自定义检查等

**3. 如何处理网络分区？**
- **脑裂预防**：使用奇数个节点，要求多数派同意
- **优雅降级**：在分区期间使用本地缓存
- **自动恢复**：分区恢复后自动同步数据
- **监控告警**：及时发现和处理分区问题

### 5.3 性能优化策略

**1. 如何提高服务发现性能？**
- **本地缓存**：缓存服务实例列表，减少网络请求
- **增量更新**：只同步变更的服务信息
- **批量操作**：合并多个注册/注销操作
- **连接复用**：使用长连接和连接池

**2. 大规模集群的挑战？**
- **存储压力**：服务实例数量增长带来的存储压力
- **网络开销**：大量的健康检查和心跳请求
- **一致性延迟**：集群规模增大导致的一致性延迟
- **解决方案**：分层架构、区域化部署、异步处理

### 5.4 故障处理

**1. 注册中心故障如何处理？**
- **多副本部署**：部署多个注册中心实例
- **故障转移**：自动切换到备用注册中心
- **本地缓存**：在注册中心不可用时使用缓存
- **降级策略**：提供静态配置作为后备方案

**2. 服务实例异常如何处理？**
- **快速检测**：缩短健康检查间隔
- **自动剔除**：及时移除不健康实例
- **重试机制**：对失败请求进行重试
- **熔断保护**：防止故障传播

这份服务注册与发现文档提供了从基础概念到生产实践的完整指导，涵盖了微服务架构中服务发现的核心技术和最佳实践。