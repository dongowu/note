# API网关（API Gateway）

## 1. API网关概述

### 1.1 定义与作用

API网关是微服务架构中的关键组件，作为所有客户端请求的统一入口点，负责请求路由、协议转换、安全认证、流量控制等功能。

**核心职责**：
- **统一入口**：为所有微服务提供统一的访问入口
- **请求路由**：根据请求路径、头部信息等将请求转发到对应的后端服务
- **协议转换**：支持HTTP/HTTPS、WebSocket、gRPC等多种协议转换
- **安全控制**：统一处理身份认证、授权、API密钥验证等安全策略
- **流量管理**：实现限流、熔断、负载均衡等流量控制功能

### 1.2 架构优势

**1. 简化客户端复杂性**
- 客户端只需要知道API网关的地址，无需了解后端服务的具体位置
- 统一的API接口规范，降低客户端开发复杂度

**2. 横切关注点集中处理**
- 认证授权、日志记录、监控统计等功能在网关层统一实现
- 避免在每个微服务中重复实现相同的功能

**3. 服务解耦**
- 后端服务可以独立演进，不影响客户端
- 支持服务版本管理和灰度发布

## 2. 核心功能实现

### 2.1 请求路由与负载均衡

#### Go语言实现示例

```go
package gateway

import (
    "context"
    "fmt"
    "log"
    "net/http"
    "net/http/httputil"
    "net/url"
    "strings"
    "sync"
    "time"
)

// ServiceRegistry 服务注册表
type ServiceRegistry struct {
    services map[string][]*ServiceInstance
    mutex    sync.RWMutex
}

// ServiceInstance 服务实例
type ServiceInstance struct {
    ID       string
    Host     string
    Port     int
    Weight   int
    Healthy  bool
    LastSeen time.Time
}

// APIGateway API网关结构
type APIGateway struct {
    registry    *ServiceRegistry
    middlewares []Middleware
    router      *Router
}

// Middleware 中间件接口
type Middleware interface {
    Process(ctx context.Context, req *http.Request, next http.HandlerFunc) error
}

// Router 路由器
type Router struct {
    routes map[string]*Route
    mutex  sync.RWMutex
}

// Route 路由规则
type Route struct {
    Path        string
    Method      string
    ServiceName string
    Rewrite     string
    Timeout     time.Duration
    Retries     int
}

// NewAPIGateway 创建API网关实例
func NewAPIGateway() *APIGateway {
    return &APIGateway{
        registry: &ServiceRegistry{
            services: make(map[string][]*ServiceInstance),
        },
        router: &Router{
            routes: make(map[string]*Route),
        },
    }
}

// RegisterService 注册服务
func (sr *ServiceRegistry) RegisterService(serviceName string, instance *ServiceInstance) {
    sr.mutex.Lock()
    defer sr.mutex.Unlock()
    
    if sr.services[serviceName] == nil {
        sr.services[serviceName] = make([]*ServiceInstance, 0)
    }
    
    // 检查是否已存在相同实例
    for i, existing := range sr.services[serviceName] {
        if existing.ID == instance.ID {
            sr.services[serviceName][i] = instance
            return
        }
    }
    
    sr.services[serviceName] = append(sr.services[serviceName], instance)
    log.Printf("Service registered: %s -> %s:%d", serviceName, instance.Host, instance.Port)
}

// GetHealthyInstances 获取健康的服务实例
func (sr *ServiceRegistry) GetHealthyInstances(serviceName string) []*ServiceInstance {
    sr.mutex.RLock()
    defer sr.mutex.RUnlock()
    
    instances := sr.services[serviceName]
    healthy := make([]*ServiceInstance, 0)
    
    for _, instance := range instances {
        if instance.Healthy {
            healthy = append(healthy, instance)
        }
    }
    
    return healthy
}

// WeightedRoundRobinBalancer 加权轮询负载均衡器
type WeightedRoundRobinBalancer struct {
    instances []*ServiceInstance
    current   int
    weights   []int
    mutex     sync.Mutex
}

// SelectInstance 选择服务实例
func (wrr *WeightedRoundRobinBalancer) SelectInstance(instances []*ServiceInstance) *ServiceInstance {
    wrr.mutex.Lock()
    defer wrr.mutex.Unlock()
    
    if len(instances) == 0 {
        return nil
    }
    
    // 初始化权重数组
    if len(wrr.weights) != len(instances) {
        wrr.weights = make([]int, len(instances))
        for i, instance := range instances {
            wrr.weights[i] = instance.Weight
        }
    }
    
    // 加权轮询算法
    totalWeight := 0
    for i := range wrr.weights {
        wrr.weights[i] += instances[i].Weight
        totalWeight += instances[i].Weight
    }
    
    // 找到权重最大的实例
    maxWeight := 0
    selectedIndex := 0
    for i, weight := range wrr.weights {
        if weight > maxWeight {
            maxWeight = weight
            selectedIndex = i
        }
    }
    
    // 减去总权重
    wrr.weights[selectedIndex] -= totalWeight
    
    return instances[selectedIndex]
}

// AddRoute 添加路由规则
func (r *Router) AddRoute(route *Route) {
    r.mutex.Lock()
    defer r.mutex.Unlock()
    
    key := fmt.Sprintf("%s:%s", route.Method, route.Path)
    r.routes[key] = route
    log.Printf("Route added: %s -> %s", key, route.ServiceName)
}

// MatchRoute 匹配路由
func (r *Router) MatchRoute(method, path string) *Route {
    r.mutex.RLock()
    defer r.mutex.RUnlock()
    
    // 精确匹配
    key := fmt.Sprintf("%s:%s", method, path)
    if route, exists := r.routes[key]; exists {
        return route
    }
    
    // 前缀匹配
    for routeKey, route := range r.routes {
        if strings.HasPrefix(path, route.Path) {
            return route
        }
    }
    
    return nil
}

// ServeHTTP 处理HTTP请求
func (gw *APIGateway) ServeHTTP(w http.ResponseWriter, r *http.Request) {
    ctx := context.WithValue(r.Context(), "requestID", generateRequestID())
    
    // 匹配路由
    route := gw.router.MatchRoute(r.Method, r.URL.Path)
    if route == nil {
        http.Error(w, "Route not found", http.StatusNotFound)
        return
    }
    
    // 获取健康的服务实例
    instances := gw.registry.GetHealthyInstances(route.ServiceName)
    if len(instances) == 0 {
        http.Error(w, "Service unavailable", http.StatusServiceUnavailable)
        return
    }
    
    // 负载均衡选择实例
    balancer := &WeightedRoundRobinBalancer{}
    instance := balancer.SelectInstance(instances)
    if instance == nil {
        http.Error(w, "No available instance", http.StatusServiceUnavailable)
        return
    }
    
    // 构建目标URL
    targetURL := &url.URL{
        Scheme: "http",
        Host:   fmt.Sprintf("%s:%d", instance.Host, instance.Port),
        Path:   r.URL.Path,
    }
    
    if route.Rewrite != "" {
        targetURL.Path = strings.Replace(r.URL.Path, route.Path, route.Rewrite, 1)
    }
    
    // 创建反向代理
    proxy := httputil.NewSingleHostReverseProxy(targetURL)
    
    // 设置超时
    if route.Timeout > 0 {
        ctx, cancel := context.WithTimeout(ctx, route.Timeout)
        defer cancel()
        r = r.WithContext(ctx)
    }
    
    // 添加请求头
    r.Header.Set("X-Forwarded-For", r.RemoteAddr)
    r.Header.Set("X-Request-ID", ctx.Value("requestID").(string))
    
    // 执行代理请求
    proxy.ServeHTTP(w, r)
}

// generateRequestID 生成请求ID
func generateRequestID() string {
    return fmt.Sprintf("%d", time.Now().UnixNano())
}
```

### 2.2 认证与授权中间件

```go
package middleware

import (
    "context"
    "encoding/json"
    "fmt"
    "net/http"
    "strings"
    "time"
    
    "github.com/golang-jwt/jwt/v4"
)

// AuthMiddleware 认证中间件
type AuthMiddleware struct {
    jwtSecret []byte
    skipPaths []string
}

// JWTClaims JWT声明
type JWTClaims struct {
    UserID   string   `json:"user_id"`
    Username string   `json:"username"`
    Roles    []string `json:"roles"`
    jwt.RegisteredClaims
}

// NewAuthMiddleware 创建认证中间件
func NewAuthMiddleware(secret string, skipPaths []string) *AuthMiddleware {
    return &AuthMiddleware{
        jwtSecret: []byte(secret),
        skipPaths: skipPaths,
    }
}

// Process 处理认证
func (am *AuthMiddleware) Process(ctx context.Context, req *http.Request, next http.HandlerFunc) error {
    // 检查是否跳过认证
    for _, path := range am.skipPaths {
        if strings.HasPrefix(req.URL.Path, path) {
            next.ServeHTTP(nil, req)
            return nil
        }
    }
    
    // 获取Authorization头
    authHeader := req.Header.Get("Authorization")
    if authHeader == "" {
        return fmt.Errorf("missing authorization header")
    }
    
    // 解析Bearer token
    tokenString := strings.TrimPrefix(authHeader, "Bearer ")
    if tokenString == authHeader {
        return fmt.Errorf("invalid authorization header format")
    }
    
    // 验证JWT token
    token, err := jwt.ParseWithClaims(tokenString, &JWTClaims{}, func(token *jwt.Token) (interface{}, error) {
        if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
            return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
        }
        return am.jwtSecret, nil
    })
    
    if err != nil {
        return fmt.Errorf("invalid token: %v", err)
    }
    
    claims, ok := token.Claims.(*JWTClaims)
    if !ok || !token.Valid {
        return fmt.Errorf("invalid token claims")
    }
    
    // 将用户信息添加到请求上下文
    ctx = context.WithValue(ctx, "userID", claims.UserID)
    ctx = context.WithValue(ctx, "username", claims.Username)
    ctx = context.WithValue(ctx, "roles", claims.Roles)
    
    req = req.WithContext(ctx)
    next.ServeHTTP(nil, req)
    
    return nil
}

// RateLimitMiddleware 限流中间件
type RateLimitMiddleware struct {
    limiter map[string]*TokenBucket
    mutex   sync.RWMutex
}

// TokenBucket 令牌桶
type TokenBucket struct {
    capacity    int64
    tokens      int64
    refillRate  int64
    lastRefill  time.Time
    mutex       sync.Mutex
}

// NewTokenBucket 创建令牌桶
func NewTokenBucket(capacity, refillRate int64) *TokenBucket {
    return &TokenBucket{
        capacity:   capacity,
        tokens:     capacity,
        refillRate: refillRate,
        lastRefill: time.Now(),
    }
}

// TryConsume 尝试消费令牌
func (tb *TokenBucket) TryConsume(tokens int64) bool {
    tb.mutex.Lock()
    defer tb.mutex.Unlock()
    
    now := time.Now()
    elapsed := now.Sub(tb.lastRefill)
    
    // 计算需要添加的令牌数
    tokensToAdd := int64(elapsed.Seconds()) * tb.refillRate
    tb.tokens = min(tb.capacity, tb.tokens+tokensToAdd)
    tb.lastRefill = now
    
    if tb.tokens >= tokens {
        tb.tokens -= tokens
        return true
    }
    
    return false
}

// Process 处理限流
func (rlm *RateLimitMiddleware) Process(ctx context.Context, req *http.Request, next http.HandlerFunc) error {
    // 获取客户端IP作为限流key
    clientIP := getClientIP(req)
    
    rlm.mutex.RLock()
    bucket, exists := rlm.limiter[clientIP]
    rlm.mutex.RUnlock()
    
    if !exists {
        rlm.mutex.Lock()
        bucket = NewTokenBucket(100, 10) // 容量100，每秒补充10个令牌
        rlm.limiter[clientIP] = bucket
        rlm.mutex.Unlock()
    }
    
    if !bucket.TryConsume(1) {
        return fmt.Errorf("rate limit exceeded")
    }
    
    next.ServeHTTP(nil, req)
    return nil
}

// getClientIP 获取客户端IP
func getClientIP(req *http.Request) string {
    // 检查X-Forwarded-For头
    if xff := req.Header.Get("X-Forwarded-For"); xff != "" {
        ips := strings.Split(xff, ",")
        return strings.TrimSpace(ips[0])
    }
    
    // 检查X-Real-IP头
    if xri := req.Header.Get("X-Real-IP"); xri != "" {
        return xri
    }
    
    // 使用RemoteAddr
    ip := req.RemoteAddr
    if colon := strings.LastIndex(ip, ":"); colon != -1 {
        ip = ip[:colon]
    }
    
    return ip
}

func min(a, b int64) int64 {
    if a < b {
        return a
    }
    return b
}
```

### 2.3 熔断器实现

```go
package circuitbreaker

import (
    "context"
    "fmt"
    "sync"
    "time"
)

// State 熔断器状态
type State int

const (
    StateClosed State = iota
    StateOpen
    StateHalfOpen
)

// CircuitBreaker 熔断器
type CircuitBreaker struct {
    name            string
    maxRequests     uint32
    interval        time.Duration
    timeout         time.Duration
    readyToTrip     func(counts Counts) bool
    onStateChange   func(name string, from State, to State)
    
    mutex      sync.Mutex
    state      State
    generation uint64
    counts     Counts
    expiry     time.Time
}

// Counts 计数器
type Counts struct {
    Requests        uint32
    TotalSuccesses  uint32
    TotalFailures   uint32
    ConsecutiveSuccesses uint32
    ConsecutiveFailures  uint32
}

// Settings 熔断器配置
type Settings struct {
    Name        string
    MaxRequests uint32
    Interval    time.Duration
    Timeout     time.Duration
    ReadyToTrip func(counts Counts) bool
    OnStateChange func(name string, from State, to State)
}

// NewCircuitBreaker 创建熔断器
func NewCircuitBreaker(st Settings) *CircuitBreaker {
    cb := &CircuitBreaker{
        name:        st.Name,
        maxRequests: st.MaxRequests,
        interval:    st.Interval,
        timeout:     st.Timeout,
        readyToTrip: st.ReadyToTrip,
        onStateChange: st.OnStateChange,
    }
    
    if cb.maxRequests == 0 {
        cb.maxRequests = 1
    }
    
    if cb.interval <= 0 {
        cb.interval = time.Duration(0)
    }
    
    if cb.timeout <= 0 {
        cb.timeout = 60 * time.Second
    }
    
    if cb.readyToTrip == nil {
        cb.readyToTrip = func(counts Counts) bool {
            return counts.ConsecutiveFailures > 5
        }
    }
    
    cb.toNewGeneration(time.Now())
    
    return cb
}

// Execute 执行请求
func (cb *CircuitBreaker) Execute(req func() (interface{}, error)) (interface{}, error) {
    generation, err := cb.beforeRequest()
    if err != nil {
        return nil, err
    }
    
    defer func() {
        e := recover()
        if e != nil {
            cb.afterRequest(generation, false)
            panic(e)
        }
    }()
    
    result, err := req()
    cb.afterRequest(generation, err == nil)
    return result, err
}

// beforeRequest 请求前检查
func (cb *CircuitBreaker) beforeRequest() (uint64, error) {
    cb.mutex.Lock()
    defer cb.mutex.Unlock()
    
    now := time.Now()
    state, generation := cb.currentState(now)
    
    if state == StateOpen {
        return generation, fmt.Errorf("circuit breaker is open")
    } else if state == StateHalfOpen && cb.counts.Requests >= cb.maxRequests {
        return generation, fmt.Errorf("too many requests")
    }
    
    cb.counts.onRequest()
    return generation, nil
}

// afterRequest 请求后处理
func (cb *CircuitBreaker) afterRequest(before uint64, success bool) {
    cb.mutex.Lock()
    defer cb.mutex.Unlock()
    
    now := time.Now()
    state, generation := cb.currentState(now)
    if generation != before {
        return
    }
    
    if success {
        cb.onSuccess(state, now)
    } else {
        cb.onFailure(state, now)
    }
}

// currentState 获取当前状态
func (cb *CircuitBreaker) currentState(now time.Time) (State, uint64) {
    switch cb.state {
    case StateClosed:
        if !cb.expiry.IsZero() && cb.expiry.Before(now) {
            cb.toNewGeneration(now)
        }
    case StateOpen:
        if cb.expiry.Before(now) {
            cb.setState(StateHalfOpen, now)
        }
    }
    return cb.state, cb.generation
}

// onSuccess 成功处理
func (cb *CircuitBreaker) onSuccess(state State, now time.Time) {
    switch state {
    case StateClosed:
        cb.counts.onSuccess()
    case StateHalfOpen:
        cb.counts.onSuccess()
        if cb.counts.ConsecutiveSuccesses >= cb.maxRequests {
            cb.setState(StateClosed, now)
        }
    }
}

// onFailure 失败处理
func (cb *CircuitBreaker) onFailure(state State, now time.Time) {
    switch state {
    case StateClosed:
        cb.counts.onFailure()
        if cb.readyToTrip(cb.counts) {
            cb.setState(StateOpen, now)
        }
    case StateHalfOpen:
        cb.setState(StateOpen, now)
    }
}

// setState 设置状态
func (cb *CircuitBreaker) setState(state State, now time.Time) {
    if cb.state == state {
        return
    }
    
    prev := cb.state
    cb.state = state
    
    cb.toNewGeneration(now)
    
    if cb.onStateChange != nil {
        cb.onStateChange(cb.name, prev, state)
    }
}

// toNewGeneration 新一代
func (cb *CircuitBreaker) toNewGeneration(now time.Time) {
    cb.generation++
    cb.counts.clear()
    
    var zero time.Time
    switch cb.state {
    case StateClosed:
        if cb.interval == 0 {
            cb.expiry = zero
        } else {
            cb.expiry = now.Add(cb.interval)
        }
    case StateOpen:
        cb.expiry = now.Add(cb.timeout)
    default: // StateHalfOpen
        cb.expiry = zero
    }
}

// onRequest 请求计数
func (c *Counts) onRequest() {
    c.Requests++
}

// onSuccess 成功计数
func (c *Counts) onSuccess() {
    c.TotalSuccesses++
    c.ConsecutiveSuccesses++
    c.ConsecutiveFailures = 0
}

// onFailure 失败计数
func (c *Counts) onFailure() {
    c.TotalFailures++
    c.ConsecutiveFailures++
    c.ConsecutiveSuccesses = 0
}

// clear 清空计数
func (c *Counts) clear() {
    c.Requests = 0
    c.TotalSuccesses = 0
    c.TotalFailures = 0
    c.ConsecutiveSuccesses = 0
    c.ConsecutiveFailures = 0
}
```

## 3. 主流API网关对比

### 3.1 技术选型对比

| 特性 | Kong | Zuul | Spring Cloud Gateway | Envoy | Traefik |
|------|------|------|---------------------|-------|--------|
| **语言** | Lua/Go | Java | Java | C++ | Go |
| **性能** | 高 | 中 | 高 | 极高 | 高 |
| **插件生态** | 丰富 | 中等 | 丰富 | 中等 | 中等 |
| **配置方式** | 数据库/文件 | 配置文件 | 配置文件 | 文件/API | 文件/API |
| **服务发现** | 支持 | 支持 | 支持 | 支持 | 支持 |
| **负载均衡** | 支持 | 支持 | 支持 | 支持 | 支持 |
| **熔断器** | 插件 | 内置 | 内置 | 内置 | 支持 |
| **限流** | 插件 | 插件 | 内置 | 内置 | 内置 |
| **监控** | 插件 | 支持 | 支持 | 丰富 | 支持 |
| **部署复杂度** | 中 | 低 | 低 | 高 | 低 |

### 3.2 使用场景建议

**Kong**：
- 适合需要丰富插件生态的企业级应用
- 对性能要求较高的场景
- 需要复杂的API管理功能

**Spring Cloud Gateway**：
- Spring生态系统项目
- Java技术栈团队
- 需要与Spring Cloud其他组件集成

**Envoy**：
- 服务网格场景（Istio数据平面）
- 对性能要求极高的场景
- 需要高级流量管理功能

**Traefik**：
- 容器化部署（Docker/Kubernetes）
- 需要自动服务发现
- 配置简单的场景

## 4. 生产环境最佳实践

### 4.1 性能优化

**1. 连接池优化**
```go
// HTTP客户端连接池配置
transport := &http.Transport{
    MaxIdleConns:        100,
    MaxIdleConnsPerHost: 10,
    IdleConnTimeout:     90 * time.Second,
    DisableKeepAlives:   false,
}

client := &http.Client{
    Transport: transport,
    Timeout:   30 * time.Second,
}
```

**2. 缓存策略**
```go
// 响应缓存中间件
type CacheMiddleware struct {
    cache map[string]*CacheEntry
    mutex sync.RWMutex
    ttl   time.Duration
}

type CacheEntry struct {
    Data      []byte
    Headers   http.Header
    Status    int
    ExpiresAt time.Time
}

func (cm *CacheMiddleware) Process(ctx context.Context, req *http.Request, next http.HandlerFunc) error {
    // 只缓存GET请求
    if req.Method != "GET" {
        next.ServeHTTP(nil, req)
        return nil
    }
    
    cacheKey := generateCacheKey(req)
    
    // 检查缓存
    cm.mutex.RLock()
    entry, exists := cm.cache[cacheKey]
    cm.mutex.RUnlock()
    
    if exists && time.Now().Before(entry.ExpiresAt) {
        // 返回缓存的响应
        w := ctx.Value("responseWriter").(http.ResponseWriter)
        for k, v := range entry.Headers {
            w.Header()[k] = v
        }
        w.WriteHeader(entry.Status)
        w.Write(entry.Data)
        return nil
    }
    
    // 执行请求并缓存响应
    next.ServeHTTP(nil, req)
    return nil
}
```

### 4.2 监控与日志

**1. 指标收集**
```go
package metrics

import (
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
)

var (
    requestsTotal = promauto.NewCounterVec(
        prometheus.CounterOpts{
            Name: "gateway_requests_total",
            Help: "Total number of requests",
        },
        []string{"method", "path", "status"},
    )
    
    requestDuration = promauto.NewHistogramVec(
        prometheus.HistogramOpts{
            Name:    "gateway_request_duration_seconds",
            Help:    "Request duration in seconds",
            Buckets: prometheus.DefBuckets,
        },
        []string{"method", "path"},
    )
    
    activeConnections = promauto.NewGauge(
        prometheus.GaugeOpts{
            Name: "gateway_active_connections",
            Help: "Number of active connections",
        },
    )
)

// RecordRequest 记录请求指标
func RecordRequest(method, path, status string, duration float64) {
    requestsTotal.WithLabelValues(method, path, status).Inc()
    requestDuration.WithLabelValues(method, path).Observe(duration)
}
```

**2. 结构化日志**
```go
package logging

import (
    "encoding/json"
    "log"
    "time"
)

// LogEntry 日志条目
type LogEntry struct {
    Timestamp   time.Time `json:"timestamp"`
    RequestID   string    `json:"request_id"`
    Method      string    `json:"method"`
    Path        string    `json:"path"`
    StatusCode  int       `json:"status_code"`
    Duration    int64     `json:"duration_ms"`
    ClientIP    string    `json:"client_ip"`
    UserAgent   string    `json:"user_agent"`
    ServiceName string    `json:"service_name"`
    Error       string    `json:"error,omitempty"`
}

// LogRequest 记录请求日志
func LogRequest(entry LogEntry) {
    data, _ := json.Marshal(entry)
    log.Println(string(data))
}
```

### 4.3 安全加固

**1. HTTPS配置**
```go
// TLS配置
tlsConfig := &tls.Config{
    MinVersion:               tls.VersionTLS12,
    CurvePreferences:         []tls.CurveID{tls.CurveP521, tls.CurveP384, tls.CurveP256},
    PreferServerCipherSuites: true,
    CipherSuites: []uint16{
        tls.TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384,
        tls.TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305,
        tls.TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256,
    },
}

server := &http.Server{
    Addr:         ":8443",
    Handler:      gateway,
    TLSConfig:    tlsConfig,
    ReadTimeout:  15 * time.Second,
    WriteTimeout: 15 * time.Second,
    IdleTimeout:  60 * time.Second,
}
```

**2. 安全头设置**
```go
// 安全头中间件
func SecurityHeadersMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        w.Header().Set("X-Content-Type-Options", "nosniff")
        w.Header().Set("X-Frame-Options", "DENY")
        w.Header().Set("X-XSS-Protection", "1; mode=block")
        w.Header().Set("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        w.Header().Set("Content-Security-Policy", "default-src 'self'")
        
        next.ServeHTTP(w, r)
    })
}
```

## 5. 面试要点总结

### 5.1 核心概念

**1. API网关的作用是什么？**
- 统一入口：为所有微服务提供统一的访问入口
- 横切关注点：认证、授权、限流、监控等功能集中处理
- 协议转换：支持不同协议间的转换
- 服务聚合：将多个微服务的响应聚合为一个响应

**2. API网关与反向代理的区别？**
- **功能范围**：API网关功能更丰富，包含业务逻辑处理
- **协议支持**：API网关支持更多协议和数据格式
- **服务发现**：API网关通常集成服务注册发现功能
- **业务感知**：API网关具备业务逻辑处理能力

### 5.2 技术实现

**1. 如何实现高可用？**
- 多实例部署：部署多个网关实例，避免单点故障
- 健康检查：定期检查后端服务健康状态
- 熔断机制：快速失败，避免级联故障
- 降级策略：在服务不可用时提供降级响应

**2. 如何处理高并发？**
- 连接池：复用HTTP连接，减少连接开销
- 异步处理：使用异步I/O模型提高吞吐量
- 缓存策略：缓存热点数据和响应
- 负载均衡：合理分配请求到后端服务

**3. 如何保证安全性？**
- 认证授权：JWT、OAuth2等认证机制
- HTTPS：加密传输数据
- 限流防护：防止恶意攻击和过载
- 输入验证：验证请求参数，防止注入攻击

### 5.3 性能优化

**1. 延迟优化策略？**
- 减少网络跳数：优化路由路径
- 连接复用：使用HTTP/2和连接池
- 缓存策略：缓存静态内容和计算结果
- 压缩传输：启用gzip压缩

**2. 吞吐量优化策略？**
- 异步处理：使用事件驱动架构
- 批量处理：合并多个请求
- 资源池化：复用昂贵资源
- 水平扩展：增加网关实例数量

这份API网关文档涵盖了从基础概念到生产实践的完整内容，为微服务架构中的API网关组件提供了全面的技术指导。