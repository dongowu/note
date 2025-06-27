# 系统设计完整流程模板

## 一、需求分析与范围界定（Requirements Analysis & Scope Definition）

### 1.1 业务需求澄清
- **功能性需求**：明确系统核心功能、用户角色、业务流程
- **非功能性需求**：性能指标（QPS、延迟、吞吐量）、可用性要求（SLA）、安全性要求
- **约束条件**：技术栈限制、预算约束、时间窗口、合规要求

### 1.2 规模评估（Scale Estimation）
- **用户规模**：DAU/MAU、并发用户数、用户增长预期
- **数据规模**：存储容量、读写比例、数据增长率
- **流量评估**：峰值QPS、平均QPS、带宽需求
- **成本预算**：硬件成本、运维成本、开发成本

### 1.3 关键指标定义
```
性能指标：
- 响应时间：P99 < 200ms
- 吞吐量：10,000 QPS
- 可用性：99.9% SLA

容量指标：
- 存储：100TB/年
- 带宽：1Gbps峰值
- 并发：10,000用户
```

## 二、高层架构设计（High-Level Architecture Design）

### 2.1 架构模式选择
- **单体 vs 微服务**：基于团队规模、业务复杂度、技术债务评估
- **同步 vs 异步**：基于实时性要求、系统解耦需求
- **有状态 vs 无状态**：基于扩展性、容错性要求

### 2.2 核心组件识别
- **接入层**：负载均衡、API网关、CDN
- **业务层**：核心服务、业务逻辑、工作流引擎
- **数据层**：数据库、缓存、消息队列、文件存储
- **基础设施层**：监控、日志、配置中心、服务发现

### 2.3 技术栈选型
```
编程语言：Go（高并发）、Java（生态丰富）、Python（快速开发）
数据库：MySQL（事务）、PostgreSQL（复杂查询）、MongoDB（文档）
缓存：Redis（内存）、Memcached（简单KV）
消息队列：Kafka（高吞吐）、RabbitMQ（可靠性）、RocketMQ（事务）
```

### 2.4 架构图绘制
- **系统架构图**：展示主要组件及其关系
- **部署架构图**：展示物理部署和网络拓扑
- **数据流图**：展示数据在系统中的流转

## 三、详细设计（Detailed Design）

### 3.1 数据库设计
- **数据模型设计**：ER图、表结构、字段类型、约束条件
- **分库分表策略**：水平分片、垂直分片、分片键选择
- **索引设计**：主键索引、唯一索引、复合索引、覆盖索引
- **读写分离**：主从复制、读写路由、数据一致性

### 3.2 API设计
- **RESTful API**：资源定义、HTTP方法、状态码、版本控制
- **GraphQL API**：Schema定义、查询优化、N+1问题解决
- **gRPC API**：Protocol Buffers、流式处理、负载均衡
- **API文档**：Swagger/OpenAPI、接口规范、示例代码

### 3.3 缓存策略
- **缓存模式**：Cache-Aside、Write-Through、Write-Behind
- **缓存层级**：浏览器缓存、CDN缓存、应用缓存、数据库缓存
- **缓存失效**：TTL策略、主动失效、缓存穿透/击穿/雪崩防护
- **一致性保证**：最终一致性、强一致性、分布式锁

### 3.4 消息队列设计
- **消息模型**：点对点、发布订阅、请求响应
- **消息可靠性**：消息持久化、确认机制、重试策略
- **消息顺序**：全局顺序、分区顺序、业务顺序
- **消息幂等**：幂等键、状态机、去重策略

## 四、可扩展性设计（Scalability Design）

### 4.1 水平扩展
- **无状态设计**：服务无状态化、会话外部化
- **负载均衡**：轮询、加权轮询、最少连接、一致性哈希
- **服务发现**：Consul、Etcd、Zookeeper、DNS
- **自动扩缩容**：基于CPU/内存、基于QPS、基于队列长度

### 4.2 垂直扩展
- **硬件升级**：CPU、内存、存储、网络
- **性能优化**：算法优化、数据结构优化、并发优化
- **资源池化**：连接池、线程池、对象池

### 4.3 分布式架构
- **微服务拆分**：业务边界、数据边界、团队边界
- **服务治理**：服务注册、健康检查、熔断降级
- **分布式事务**：2PC、TCC、Saga、本地消息表
- **分布式锁**：Redis分布式锁、Zookeeper分布式锁

## 五、可靠性设计（Reliability Design）

### 5.1 高可用设计
- **冗余设计**：主备模式、主主模式、集群模式
- **故障检测**：健康检查、心跳机制、故障转移
- **容错机制**：重试、熔断、降级、限流
- **灾备方案**：同城双活、异地多活、冷备份

### 5.2 数据可靠性
- **数据备份**：全量备份、增量备份、差异备份
- **数据恢复**：PITR、快照恢复、日志回放
- **数据一致性**：ACID、CAP理论、最终一致性
- **数据校验**：校验和、数据审计、一致性检查

### 5.3 监控告警
- **指标监控**：业务指标、系统指标、应用指标
- **日志监控**：错误日志、访问日志、审计日志
- **链路追踪**：分布式追踪、性能分析、依赖分析
- **告警策略**：阈值告警、趋势告警、异常检测

## 六、安全性设计（Security Design）

### 6.1 认证授权
- **身份认证**：用户名密码、多因子认证、SSO、OAuth2.0
- **权限控制**：RBAC、ABAC、ACL、权限继承
- **会话管理**：Session、JWT、Token刷新、会话超时
- **API安全**：API Key、签名验证、频率限制

### 6.2 数据安全
- **数据加密**：传输加密（TLS）、存储加密（AES）、字段加密
- **数据脱敏**：静态脱敏、动态脱敏、格式保留
- **数据隔离**：多租户隔离、网络隔离、存储隔离
- **数据审计**：操作日志、访问日志、变更记录

### 6.3 网络安全
- **网络隔离**：VPC、子网、安全组、防火墙
- **DDoS防护**：流量清洗、黑白名单、限流策略
- **入侵检测**：WAF、IDS/IPS、异常行为检测
- **安全扫描**：漏洞扫描、代码审计、依赖检查

### 6.4 OAuth2.0/JWT认证授权深度实现

#### 6.4.1 OAuth2.0授权流程实现
```go
// OAuth2.0授权服务器实现
type AuthorizationServer struct {
    clientStore    ClientStore
    tokenStore     TokenStore
    userStore      UserStore
    jwtSecret      []byte
    tokenExpiry    time.Duration
    refreshExpiry  time.Duration
}

// 授权码模式实现
func (as *AuthorizationServer) AuthorizeCode(w http.ResponseWriter, r *http.Request) {
    clientID := r.URL.Query().Get("client_id")
    redirectURI := r.URL.Query().Get("redirect_uri")
    scope := r.URL.Query().Get("scope")
    state := r.URL.Query().Get("state")
    
    // 验证客户端
    client, err := as.clientStore.GetClient(clientID)
    if err != nil || !client.ValidateRedirectURI(redirectURI) {
        http.Error(w, "Invalid client", http.StatusBadRequest)
        return
    }
    
    // 用户认证（简化示例）
    userID := as.authenticateUser(r)
    if userID == "" {
        // 重定向到登录页面
        http.Redirect(w, r, "/login", http.StatusFound)
        return
    }
    
    // 生成授权码
    authCode := as.generateAuthCode(clientID, userID, scope)
    
    // 重定向回客户端
    redirectURL := fmt.Sprintf("%s?code=%s&state=%s", redirectURI, authCode, state)
    http.Redirect(w, r, redirectURL, http.StatusFound)
}

// 访问令牌交换
func (as *AuthorizationServer) ExchangeToken(w http.ResponseWriter, r *http.Request) {
    grantType := r.FormValue("grant_type")
    
    switch grantType {
    case "authorization_code":
        as.handleAuthorizationCodeGrant(w, r)
    case "refresh_token":
        as.handleRefreshTokenGrant(w, r)
    case "client_credentials":
        as.handleClientCredentialsGrant(w, r)
    default:
        http.Error(w, "Unsupported grant type", http.StatusBadRequest)
    }
}

func (as *AuthorizationServer) handleAuthorizationCodeGrant(w http.ResponseWriter, r *http.Request) {
    code := r.FormValue("code")
    clientID := r.FormValue("client_id")
    clientSecret := r.FormValue("client_secret")
    redirectURI := r.FormValue("redirect_uri")
    
    // 验证客户端凭据
    if !as.validateClientCredentials(clientID, clientSecret) {
        http.Error(w, "Invalid client credentials", http.StatusUnauthorized)
        return
    }
    
    // 验证授权码
    authInfo, err := as.tokenStore.GetAuthCode(code)
    if err != nil || authInfo.IsExpired() {
        http.Error(w, "Invalid or expired authorization code", http.StatusBadRequest)
        return
    }
    
    // 生成访问令牌和刷新令牌
    accessToken := as.generateJWT(authInfo.UserID, authInfo.Scope, as.tokenExpiry)
    refreshToken := as.generateRefreshToken(authInfo.UserID, clientID)
    
    response := TokenResponse{
        AccessToken:  accessToken,
        TokenType:    "Bearer",
        ExpiresIn:    int(as.tokenExpiry.Seconds()),
        RefreshToken: refreshToken,
        Scope:        authInfo.Scope,
    }
    
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(response)
}
```

#### 6.4.2 JWT令牌实现与验证
```go
// JWT令牌生成器
type JWTManager struct {
    secretKey     []byte
    tokenDuration time.Duration
    issuer        string
}

type Claims struct {
    UserID    string   `json:"user_id"`
    Username  string   `json:"username"`
    Roles     []string `json:"roles"`
    Scope     string   `json:"scope"`
    jwt.RegisteredClaims
}

func (manager *JWTManager) Generate(userID, username string, roles []string, scope string) (string, error) {
    claims := Claims{
        UserID:   userID,
        Username: username,
        Roles:    roles,
        Scope:    scope,
        RegisteredClaims: jwt.RegisteredClaims{
            ExpiresAt: jwt.NewNumericDate(time.Now().Add(manager.tokenDuration)),
            IssuedAt:  jwt.NewNumericDate(time.Now()),
            NotBefore: jwt.NewNumericDate(time.Now()),
            Issuer:    manager.issuer,
            Subject:   userID,
        },
    }
    
    token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
    return token.SignedString(manager.secretKey)
}

func (manager *JWTManager) Verify(tokenString string) (*Claims, error) {
    token, err := jwt.ParseWithClaims(tokenString, &Claims{}, func(token *jwt.Token) (interface{}, error) {
        if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
            return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
        }
        return manager.secretKey, nil
    })
    
    if err != nil {
        return nil, err
    }
    
    if claims, ok := token.Claims.(*Claims); ok && token.Valid {
        return claims, nil
    }
    
    return nil, fmt.Errorf("invalid token")
}

// JWT中间件
func JWTAuthMiddleware(jwtManager *JWTManager) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            authHeader := r.Header.Get("Authorization")
            if authHeader == "" {
                http.Error(w, "Missing authorization header", http.StatusUnauthorized)
                return
            }
            
            tokenString := strings.TrimPrefix(authHeader, "Bearer ")
            claims, err := jwtManager.Verify(tokenString)
            if err != nil {
                http.Error(w, "Invalid token", http.StatusUnauthorized)
                return
            }
            
            // 将用户信息添加到请求上下文
            ctx := context.WithValue(r.Context(), "user_claims", claims)
            next.ServeHTTP(w, r.WithContext(ctx))
        })
    }
}
```

### 6.5 加密算法应用与密钥管理

#### 6.5.1 对称加密实现
```go
// AES加密服务
type AESCryptoService struct {
    key []byte
}

func NewAESCryptoService(key []byte) *AESCryptoService {
    return &AESCryptoService{key: key}
}

func (acs *AESCryptoService) Encrypt(plaintext []byte) ([]byte, error) {
    block, err := aes.NewCipher(acs.key)
    if err != nil {
        return nil, err
    }
    
    // 使用GCM模式
    gcm, err := cipher.NewGCM(block)
    if err != nil {
        return nil, err
    }
    
    // 生成随机nonce
    nonce := make([]byte, gcm.NonceSize())
    if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
        return nil, err
    }
    
    // 加密
    ciphertext := gcm.Seal(nonce, nonce, plaintext, nil)
    return ciphertext, nil
}

func (acs *AESCryptoService) Decrypt(ciphertext []byte) ([]byte, error) {
    block, err := aes.NewCipher(acs.key)
    if err != nil {
        return nil, err
    }
    
    gcm, err := cipher.NewGCM(block)
    if err != nil {
        return nil, err
    }
    
    nonceSize := gcm.NonceSize()
    if len(ciphertext) < nonceSize {
        return nil, errors.New("ciphertext too short")
    }
    
    nonce, ciphertext := ciphertext[:nonceSize], ciphertext[nonceSize:]
    return gcm.Open(nil, nonce, ciphertext, nil)
}
```

#### 6.5.2 非对称加密与数字签名
```go
// RSA加密服务
type RSACryptoService struct {
    privateKey *rsa.PrivateKey
    publicKey  *rsa.PublicKey
}

func NewRSACryptoService(keySize int) (*RSACryptoService, error) {
    privateKey, err := rsa.GenerateKey(rand.Reader, keySize)
    if err != nil {
        return nil, err
    }
    
    return &RSACryptoService{
        privateKey: privateKey,
        publicKey:  &privateKey.PublicKey,
    }, nil
}

func (rcs *RSACryptoService) Encrypt(plaintext []byte) ([]byte, error) {
    return rsa.EncryptOAEP(sha256.New(), rand.Reader, rcs.publicKey, plaintext, nil)
}

func (rcs *RSACryptoService) Decrypt(ciphertext []byte) ([]byte, error) {
    return rsa.DecryptOAEP(sha256.New(), rand.Reader, rcs.privateKey, ciphertext, nil)
}

func (rcs *RSACryptoService) Sign(data []byte) ([]byte, error) {
    hash := sha256.Sum256(data)
    return rsa.SignPKCS1v15(rand.Reader, rcs.privateKey, crypto.SHA256, hash[:])
}

func (rcs *RSACryptoService) Verify(data, signature []byte) error {
    hash := sha256.Sum256(data)
    return rsa.VerifyPKCS1v15(rcs.publicKey, crypto.SHA256, hash[:], signature)
}
```

#### 6.5.3 密钥管理系统
```go
// 密钥管理服务
type KeyManagementService struct {
    vault      VaultInterface
    rotationPeriod time.Duration
    encryptionKeys map[string]*EncryptionKey
    mu            sync.RWMutex
}

type EncryptionKey struct {
    ID        string
    Key       []byte
    Algorithm string
    CreatedAt time.Time
    ExpiresAt time.Time
    Status    KeyStatus
}

type KeyStatus int

const (
    KeyStatusActive KeyStatus = iota
    KeyStatusRotating
    KeyStatusDeprecated
    KeyStatusRevoked
)

func (kms *KeyManagementService) GenerateKey(algorithm string) (*EncryptionKey, error) {
    keyID := generateKeyID()
    var key []byte
    var err error
    
    switch algorithm {
    case "AES-256":
        key = make([]byte, 32)
        _, err = rand.Read(key)
    case "AES-128":
        key = make([]byte, 16)
        _, err = rand.Read(key)
    default:
        return nil, fmt.Errorf("unsupported algorithm: %s", algorithm)
    }
    
    if err != nil {
        return nil, err
    }
    
    encKey := &EncryptionKey{
        ID:        keyID,
        Key:       key,
        Algorithm: algorithm,
        CreatedAt: time.Now(),
        ExpiresAt: time.Now().Add(kms.rotationPeriod),
        Status:    KeyStatusActive,
    }
    
    // 存储到密钥保险库
    if err := kms.vault.StoreKey(keyID, encKey); err != nil {
        return nil, err
    }
    
    kms.mu.Lock()
    kms.encryptionKeys[keyID] = encKey
    kms.mu.Unlock()
    
    return encKey, nil
}

func (kms *KeyManagementService) RotateKey(keyID string) error {
    kms.mu.Lock()
    defer kms.mu.Unlock()
    
    oldKey, exists := kms.encryptionKeys[keyID]
    if !exists {
        return fmt.Errorf("key not found: %s", keyID)
    }
    
    // 生成新密钥
    newKey, err := kms.GenerateKey(oldKey.Algorithm)
    if err != nil {
        return err
    }
    
    // 标记旧密钥为已弃用
    oldKey.Status = KeyStatusDeprecated
    kms.vault.UpdateKey(keyID, oldKey)
    
    // 更新密钥映射
    kms.encryptionKeys[newKey.ID] = newKey
    
    return nil
}

func (kms *KeyManagementService) GetActiveKey(algorithm string) (*EncryptionKey, error) {
    kms.mu.RLock()
    defer kms.mu.RUnlock()
    
    for _, key := range kms.encryptionKeys {
        if key.Algorithm == algorithm && key.Status == KeyStatusActive {
            return key, nil
        }
    }
    
    return nil, fmt.Errorf("no active key found for algorithm: %s", algorithm)
}
```

### 6.6 Web安全防护实现

#### 6.6.1 XSS防护
```go
// XSS防护中间件
func XSSProtectionMiddleware() func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            // 设置XSS保护头
            w.Header().Set("X-XSS-Protection", "1; mode=block")
            w.Header().Set("X-Content-Type-Options", "nosniff")
            w.Header().Set("X-Frame-Options", "DENY")
            
            // 设置CSP头
            csp := "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
            w.Header().Set("Content-Security-Policy", csp)
            
            next.ServeHTTP(w, r)
        })
    }
}

// HTML转义函数
func SanitizeHTML(input string) string {
    // 使用bluemonday库进行HTML清理
    p := bluemonday.UGCPolicy()
    return p.Sanitize(input)
}

// 输入验证和清理
type InputValidator struct {
    htmlPolicy *bluemonday.Policy
}

func NewInputValidator() *InputValidator {
    return &InputValidator{
        htmlPolicy: bluemonday.UGCPolicy(),
    }
}

func (iv *InputValidator) ValidateAndSanitize(input string, inputType string) (string, error) {
    switch inputType {
    case "html":
        return iv.htmlPolicy.Sanitize(input), nil
    case "email":
        if !isValidEmail(input) {
            return "", errors.New("invalid email format")
        }
        return input, nil
    case "url":
        if !isValidURL(input) {
            return "", errors.New("invalid URL format")
        }
        return input, nil
    default:
        // 默认进行HTML转义
        return html.EscapeString(input), nil
    }
}
```

#### 6.6.2 CSRF防护
```go
// CSRF防护中间件
type CSRFProtection struct {
    secret    []byte
    tokenName string
    secure    bool
    sameSite  http.SameSite
}

func NewCSRFProtection(secret []byte) *CSRFProtection {
    return &CSRFProtection{
        secret:    secret,
        tokenName: "csrf_token",
        secure:    true,
        sameSite:  http.SameSiteStrictMode,
    }
}

func (csrf *CSRFProtection) Middleware() func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            // 对于安全方法（GET、HEAD、OPTIONS）不需要CSRF保护
            if r.Method == "GET" || r.Method == "HEAD" || r.Method == "OPTIONS" {
                // 生成并设置CSRF令牌
                token := csrf.generateToken(r)
                csrf.setTokenCookie(w, token)
                next.ServeHTTP(w, r)
                return
            }
            
            // 验证CSRF令牌
            if !csrf.validateToken(r) {
                http.Error(w, "CSRF token validation failed", http.StatusForbidden)
                return
            }
            
            next.ServeHTTP(w, r)
        })
    }
}

func (csrf *CSRFProtection) generateToken(r *http.Request) string {
    // 使用会话ID和时间戳生成令牌
    sessionID := getSessionID(r)
    timestamp := time.Now().Unix()
    
    h := hmac.New(sha256.New, csrf.secret)
    h.Write([]byte(fmt.Sprintf("%s:%d", sessionID, timestamp)))
    
    token := base64.URLEncoding.EncodeToString(h.Sum(nil))
    return fmt.Sprintf("%s:%d", token, timestamp)
}

func (csrf *CSRFProtection) validateToken(r *http.Request) bool {
    // 从表单或头部获取令牌
    token := r.FormValue(csrf.tokenName)
    if token == "" {
        token = r.Header.Get("X-CSRF-Token")
    }
    
    if token == "" {
        return false
    }
    
    // 解析令牌
    parts := strings.Split(token, ":")
    if len(parts) != 2 {
        return false
    }
    
    tokenHash := parts[0]
    timestamp, err := strconv.ParseInt(parts[1], 10, 64)
    if err != nil {
        return false
    }
    
    // 检查令牌是否过期（1小时）
    if time.Now().Unix()-timestamp > 3600 {
        return false
    }
    
    // 验证令牌
    sessionID := getSessionID(r)
    h := hmac.New(sha256.New, csrf.secret)
    h.Write([]byte(fmt.Sprintf("%s:%d", sessionID, timestamp)))
    expectedHash := base64.URLEncoding.EncodeToString(h.Sum(nil))
    
    return hmac.Equal([]byte(tokenHash), []byte(expectedHash))
}
```

#### 6.6.3 SQL注入防护
```go
// 安全的数据库操作封装
type SafeDB struct {
    db *sql.DB
}

func NewSafeDB(db *sql.DB) *SafeDB {
    return &SafeDB{db: db}
}

// 参数化查询示例
func (sdb *SafeDB) GetUserByID(userID int) (*User, error) {
    query := "SELECT id, username, email, created_at FROM users WHERE id = ?"
    
    var user User
    err := sdb.db.QueryRow(query, userID).Scan(
        &user.ID,
        &user.Username,
        &user.Email,
        &user.CreatedAt,
    )
    
    if err != nil {
        if err == sql.ErrNoRows {
            return nil, ErrUserNotFound
        }
        return nil, err
    }
    
    return &user, nil
}

// 动态查询构建器（防止SQL注入）
type QueryBuilder struct {
    query  strings.Builder
    args   []interface{}
    params int
}

func NewQueryBuilder() *QueryBuilder {
    return &QueryBuilder{}
}

func (qb *QueryBuilder) Select(columns ...string) *QueryBuilder {
    qb.query.WriteString("SELECT ")
    qb.query.WriteString(strings.Join(columns, ", "))
    return qb
}

func (qb *QueryBuilder) From(table string) *QueryBuilder {
    qb.query.WriteString(" FROM ")
    qb.query.WriteString(table)
    return qb
}

func (qb *QueryBuilder) Where(condition string, args ...interface{}) *QueryBuilder {
    qb.query.WriteString(" WHERE ")
    qb.query.WriteString(condition)
    qb.args = append(qb.args, args...)
    return qb
}

func (qb *QueryBuilder) Build() (string, []interface{}) {
    return qb.query.String(), qb.args
}

// 输入验证器
type SQLInputValidator struct{}

func (siv *SQLInputValidator) ValidateTableName(tableName string) error {
    // 只允许字母、数字和下划线
    matched, _ := regexp.MatchString("^[a-zA-Z_][a-zA-Z0-9_]*$", tableName)
    if !matched {
        return errors.New("invalid table name")
    }
    return nil
}

func (siv *SQLInputValidator) ValidateColumnName(columnName string) error {
    // 只允许字母、数字和下划线
    matched, _ := regexp.MatchString("^[a-zA-Z_][a-zA-Z0-9_]*$", columnName)
    if !matched {
        return errors.New("invalid column name")
    }
    return nil
}
```

### 6.7 API安全最佳实践

#### 6.7.1 API认证与授权
```go
// API密钥管理
type APIKeyManager struct {
    keys map[string]*APIKey
    mu   sync.RWMutex
}

type APIKey struct {
    ID          string
    Key         string
    Secret      string
    UserID      string
    Permissions []string
    RateLimit   RateLimit
    CreatedAt   time.Time
    ExpiresAt   time.Time
    IsActive    bool
}

type RateLimit struct {
    RequestsPerMinute int
    RequestsPerHour   int
    RequestsPerDay    int
}

func (akm *APIKeyManager) ValidateAPIKey(keyID, signature, timestamp, nonce string, body []byte) (*APIKey, error) {
    akm.mu.RLock()
    apiKey, exists := akm.keys[keyID]
    akm.mu.RUnlock()
    
    if !exists || !apiKey.IsActive {
        return nil, errors.New("invalid API key")
    }
    
    if time.Now().After(apiKey.ExpiresAt) {
        return nil, errors.New("API key expired")
    }
    
    // 验证签名
    expectedSignature := akm.generateSignature(apiKey.Secret, timestamp, nonce, body)
    if !hmac.Equal([]byte(signature), []byte(expectedSignature)) {
        return nil, errors.New("invalid signature")
    }
    
    // 验证时间戳（防止重放攻击）
    ts, err := strconv.ParseInt(timestamp, 10, 64)
    if err != nil {
        return nil, errors.New("invalid timestamp")
    }
    
    if math.Abs(float64(time.Now().Unix()-ts)) > 300 { // 5分钟窗口
        return nil, errors.New("timestamp too old")
    }
    
    return apiKey, nil
}

func (akm *APIKeyManager) generateSignature(secret, timestamp, nonce string, body []byte) string {
    h := hmac.New(sha256.New, []byte(secret))
    h.Write([]byte(timestamp))
    h.Write([]byte(nonce))
    h.Write(body)
    return base64.StdEncoding.EncodeToString(h.Sum(nil))
}
```

#### 6.7.2 API限流与熔断
```go
// 令牌桶限流器
type TokenBucketLimiter struct {
    capacity int64
    tokens   int64
    refillRate int64
    lastRefill time.Time
    mu        sync.Mutex
}

func NewTokenBucketLimiter(capacity, refillRate int64) *TokenBucketLimiter {
    return &TokenBucketLimiter{
        capacity:   capacity,
        tokens:     capacity,
        refillRate: refillRate,
        lastRefill: time.Now(),
    }
}

func (tbl *TokenBucketLimiter) Allow() bool {
    tbl.mu.Lock()
    defer tbl.mu.Unlock()
    
    now := time.Now()
    elapsed := now.Sub(tbl.lastRefill)
    
    // 补充令牌
    tokensToAdd := int64(elapsed.Seconds()) * tbl.refillRate
    tbl.tokens = min(tbl.capacity, tbl.tokens+tokensToAdd)
    tbl.lastRefill = now
    
    if tbl.tokens > 0 {
        tbl.tokens--
        return true
    }
    
    return false
}

// 熔断器实现
type CircuitBreaker struct {
    maxFailures int
    resetTimeout time.Duration
    failures    int
    lastFailTime time.Time
    state       CircuitState
    mu          sync.RWMutex
}

type CircuitState int

const (
    StateClosed CircuitState = iota
    StateOpen
    StateHalfOpen
)

func NewCircuitBreaker(maxFailures int, resetTimeout time.Duration) *CircuitBreaker {
    return &CircuitBreaker{
        maxFailures:  maxFailures,
        resetTimeout: resetTimeout,
        state:        StateClosed,
    }
}

func (cb *CircuitBreaker) Call(fn func() error) error {
    cb.mu.Lock()
    defer cb.mu.Unlock()
    
    if cb.state == StateOpen {
        if time.Since(cb.lastFailTime) > cb.resetTimeout {
            cb.state = StateHalfOpen
            cb.failures = 0
        } else {
            return errors.New("circuit breaker is open")
        }
    }
    
    err := fn()
    
    if err != nil {
        cb.failures++
        cb.lastFailTime = time.Now()
        
        if cb.failures >= cb.maxFailures {
            cb.state = StateOpen
        }
        
        return err
    }
    
    if cb.state == StateHalfOpen {
        cb.state = StateClosed
    }
    
    cb.failures = 0
    return nil
}
```

#### 6.7.3 API安全中间件集成
```go
// 综合安全中间件
type SecurityMiddleware struct {
    jwtManager    *JWTManager
    apiKeyManager *APIKeyManager
    rateLimiter   *TokenBucketLimiter
    csrfProtection *CSRFProtection
}

func (sm *SecurityMiddleware) SecureAPI() func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            // 1. HTTPS检查
            if r.TLS == nil && r.Header.Get("X-Forwarded-Proto") != "https" {
                http.Error(w, "HTTPS required", http.StatusBadRequest)
                return
            }
            
            // 2. 设置安全头
            w.Header().Set("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
            w.Header().Set("X-Content-Type-Options", "nosniff")
            w.Header().Set("X-Frame-Options", "DENY")
            w.Header().Set("X-XSS-Protection", "1; mode=block")
            
            // 3. 限流检查
            if !sm.rateLimiter.Allow() {
                http.Error(w, "Rate limit exceeded", http.StatusTooManyRequests)
                return
            }
            
            // 4. 认证检查
            if !sm.authenticate(r) {
                http.Error(w, "Authentication required", http.StatusUnauthorized)
                return
            }
            
            // 5. CSRF保护（对于状态改变操作）
            if r.Method != "GET" && r.Method != "HEAD" && r.Method != "OPTIONS" {
                if !sm.csrfProtection.validateToken(r) {
                    http.Error(w, "CSRF token validation failed", http.StatusForbidden)
                    return
                }
            }
            
            next.ServeHTTP(w, r)
        })
    }
}

func (sm *SecurityMiddleware) authenticate(r *http.Request) bool {
    // 尝试JWT认证
    authHeader := r.Header.Get("Authorization")
    if strings.HasPrefix(authHeader, "Bearer ") {
        tokenString := strings.TrimPrefix(authHeader, "Bearer ")
        _, err := sm.jwtManager.Verify(tokenString)
        return err == nil
    }
    
    // 尝试API密钥认证
    apiKey := r.Header.Get("X-API-Key")
    signature := r.Header.Get("X-Signature")
    timestamp := r.Header.Get("X-Timestamp")
    nonce := r.Header.Get("X-Nonce")
    
    if apiKey != "" && signature != "" {
        body, _ := io.ReadAll(r.Body)
        r.Body = io.NopCloser(bytes.NewBuffer(body))
        
        _, err := sm.apiKeyManager.ValidateAPIKey(apiKey, signature, timestamp, nonce, body)
        return err == nil
    }
    
    return false
}
```

## 七、性能优化（Performance Optimization）

### 7.1 应用层优化
- **代码优化**：算法优化、数据结构选择、内存管理
- **并发优化**：线程池、协程、异步处理、锁优化
- **缓存优化**：本地缓存、分布式缓存、缓存预热
- **连接优化**：连接池、长连接、连接复用

### 7.2 数据库优化
- **查询优化**：SQL优化、索引优化、执行计划分析
- **存储优化**：分区表、压缩、归档、冷热分离
- **配置优化**：内存配置、连接数配置、缓冲区配置
- **读写优化**：读写分离、分库分表、批量操作

### 7.3 网络优化
- **CDN加速**：静态资源缓存、边缘计算、智能路由
- **压缩优化**：Gzip压缩、图片压缩、协议压缩
- **协议优化**：HTTP/2、QUIC、长连接、多路复用
- **带宽优化**：流量控制、QoS、带宽分配

## 八、部署运维（Deployment & Operations）

### 8.1 部署策略
- **部署模式**：蓝绿部署、滚动部署、金丝雀部署、A/B测试
- **容器化**：Docker、Kubernetes、服务网格、镜像管理
- **CI/CD**：代码管理、自动构建、自动测试、自动部署
- **环境管理**：开发环境、测试环境、预发环境、生产环境

### 8.2 运维监控
- **基础监控**：CPU、内存、磁盘、网络、进程
- **应用监控**：QPS、延迟、错误率、业务指标
- **日志管理**：日志收集、日志分析、日志存储、日志检索
- **告警处理**：告警规则、告警通知、故障处理、事后分析

### 8.3 容量规划
- **容量评估**：历史数据分析、业务增长预测、压力测试
- **资源规划**：硬件规划、软件规划、网络规划、存储规划
- **成本优化**：资源利用率、成本分析、优化建议
- **扩容策略**：自动扩容、手动扩容、预扩容、弹性扩容

## 九、技术债务与重构（Technical Debt & Refactoring）

### 9.1 技术债务识别
- **代码质量**：代码复杂度、重复代码、代码覆盖率
- **架构债务**：架构腐化、组件耦合、技术栈老化
- **性能债务**：性能瓶颈、资源浪费、扩展性问题
- **安全债务**：安全漏洞、合规问题、权限混乱

### 9.2 重构策略
- **渐进式重构**：小步快跑、持续改进、风险控制
- **大爆炸重构**：全面重写、技术升级、架构重构
- **绞杀者模式**：新老系统并存、逐步替换、平滑迁移
- **分支抽象**：功能开关、特性分支、灰度发布

### 9.3 迁移方案
- **数据迁移**：数据同步、数据校验、回滚方案
- **服务迁移**：服务替换、流量切换、监控验证
- **架构演进**：单体到微服务、同步到异步、本地到云端

## 十、面试要点总结（Interview Key Points）

### 10.1 系统设计思路
1. **需求澄清**：主动提问、明确边界、量化指标
2. **架构设计**：从简到繁、分层设计、组件职责
3. **技术选型**：权衡利弊、结合场景、考虑成本
4. **扩展性**：水平扩展、垂直扩展、分布式设计
5. **可靠性**：高可用、容错、监控告警

### 10.2 常见考察点
- **数据存储**：SQL vs NoSQL、分库分表、一致性
- **缓存设计**：缓存策略、缓存更新、缓存穿透
- **消息队列**：消息可靠性、消息顺序、消息幂等
- **负载均衡**：负载策略、会话保持、健康检查
- **微服务**：服务拆分、服务治理、分布式事务

### 10.3 回答技巧
- **结构化思考**：按照流程逐步展开，逻辑清晰
- **权衡分析**：分析各种方案的优缺点，说明选择理由
- **具体化描述**：给出具体的技术方案和实现细节
- **扩展思考**：考虑系统演进和优化方向
- **实战经验**：结合实际项目经验，增加说服力

## 十一、Go语言实现要点（Go Implementation Points）

### 11.1 并发编程
```go
// Goroutine池模式
type WorkerPool struct {
    workers    int
    jobQueue   chan Job
    workerPool chan chan Job
    quit       chan bool
}

// 优雅关闭
func (p *WorkerPool) Stop() {
    close(p.quit)
}
```

### 11.2 错误处理
```go
// 错误包装
func processData(data []byte) error {
    if err := validate(data); err != nil {
        return fmt.Errorf("validation failed: %w", err)
    }
    return nil
}

// 错误类型判断
if errors.Is(err, ErrNotFound) {
    // 处理未找到错误
}
```

### 11.3 性能优化
```go
// 内存池
var bufferPool = sync.Pool{
    New: func() interface{} {
        return make([]byte, 1024)
    },
}

// 使用内存池
buf := bufferPool.Get().([]byte)
defer bufferPool.Put(buf)
```

### 11.4 监控指标
```go
// Prometheus指标
var (
    requestDuration = prometheus.NewHistogramVec(
        prometheus.HistogramOpts{
            Name: "http_request_duration_seconds",
            Help: "HTTP request duration",
        },
        []string{"method", "endpoint"},
    )
)
```
---

**总结**：系统设计是一个系统性工程，需要从业务需求出发，综合考虑功能性和非功能性需求，采用分层架构思想，逐步细化设计，并在实施过程中持续优化和演进。关键在于平衡各种技术方案的优缺点，选择最适合当前业务场景和团队能力的技术栈。
