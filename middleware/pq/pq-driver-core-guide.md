# Go PostgreSQL驱动(pq)核心技术指南

> 本文档从高级开发工程师和架构师视角，深入分析Go语言中pq驱动的核心原理、技术特点、优缺点及实际应用场景，为Go高级开发工程师面试提供全面的技术支持。

## 目录
- [pq驱动概述](#pq驱动概述)
- [核心原理](#核心原理)
- [核心组件](#核心组件)
- [技术亮点](#技术亮点)
- [优缺点分析](#优缺点分析)
- [使用场景](#使用场景)
- [常见问题与解决方案](#常见问题与解决方案)
- [最佳实践](#最佳实践)

## pq驱动概述

### 1. pq驱动简介

**pq**是Go语言中最流行的PostgreSQL数据库驱动之一，实现了Go标准库`database/sql`接口。

```go
import (
    "database/sql"
    _ "github.com/lib/pq"  // PostgreSQL驱动
)

// 基本连接
db, err := sql.Open("postgres", "postgres://user:password@localhost/dbname?sslmode=disable")
```

**核心特性**：
- 纯Go实现，无CGO依赖
- 完全实现database/sql接口
- 支持PostgreSQL所有数据类型
- 支持SSL/TLS加密连接
- 支持事务、预处理语句
- 支持LISTEN/NOTIFY机制
- 支持COPY协议

### 2. 架构设计

```
┌─────────────────┐
│   Application   │
└─────────┬───────┘
          │
┌─────────▼───────┐
│  database/sql   │  (Go标准库)
└─────────┬───────┘
          │
┌─────────▼───────┐
│   pq Driver     │  (github.com/lib/pq)
└─────────┬───────┘
          │
┌─────────▼───────┐
│  PostgreSQL     │  (数据库服务器)
│   Protocol      │
└─────────────────┘
```

## 核心原理

### 1. 连接管理

#### 连接池机制
```go
func setupConnectionPool() *sql.DB {
    db, err := sql.Open("postgres", dsn)
    if err != nil {
        log.Fatal(err)
    }
    
    // 连接池配置
    db.SetMaxOpenConns(100)        // 最大打开连接数
    db.SetMaxIdleConns(10)         // 最大空闲连接数
    db.SetConnMaxLifetime(time.Hour) // 连接最大生存时间
    db.SetConnMaxIdleTime(30 * time.Minute) // 连接最大空闲时间
    
    return db
}

// 连接池监控
func monitorConnectionPool(db *sql.DB) {
    stats := db.Stats()
    fmt.Printf("MaxOpenConnections: %d\n", stats.MaxOpenConnections)
    fmt.Printf("OpenConnections: %d\n", stats.OpenConnections)
    fmt.Printf("InUse: %d\n", stats.InUse)
    fmt.Printf("Idle: %d\n", stats.Idle)
    fmt.Printf("WaitCount: %d\n", stats.WaitCount)
    fmt.Printf("WaitDuration: %v\n", stats.WaitDuration)
}
```

#### 连接字符串解析
```go
// 标准连接字符串格式
dsn := "postgres://username:password@localhost:5432/database_name?sslmode=require"

// 键值对格式
dsn := "host=localhost port=5432 user=username password=password dbname=database_name sslmode=require"

// 连接参数详解
type ConnectionParams struct {
    Host     string // 主机地址
    Port     int    // 端口号
    User     string // 用户名
    Password string // 密码
    DBName   string // 数据库名
    SSLMode  string // SSL模式: disable, require, verify-ca, verify-full
    TimeZone string // 时区设置
    ConnectTimeout int // 连接超时时间
}
```

### 2. 协议实现

#### PostgreSQL前端/后端协议
```go
// 消息类型定义
const (
    msgTypeQuery          = 'Q'  // 简单查询
    msgTypeParse          = 'P'  // 解析预处理语句
    msgTypeBind           = 'B'  // 绑定参数
    msgTypeExecute        = 'E'  // 执行语句
    msgTypeSync           = 'S'  // 同步
    msgTypeTerminate      = 'X'  // 终止连接
)

// 消息处理流程
type MessageHandler struct {
    conn net.Conn
    buf  []byte
}

func (h *MessageHandler) sendQuery(query string) error {
    // 构造查询消息
    msg := make([]byte, 5+len(query)+1)
    msg[0] = msgTypeQuery
    binary.BigEndian.PutUint32(msg[1:5], uint32(len(query)+5))
    copy(msg[5:], query)
    msg[len(msg)-1] = 0 // null终止符
    
    _, err := h.conn.Write(msg)
    return err
}
```

### 3. 数据类型映射

#### Go类型与PostgreSQL类型映射
```go
// 基本类型映射
var typeMapping = map[string]reflect.Type{
    "int4":        reflect.TypeOf(int32(0)),
    "int8":        reflect.TypeOf(int64(0)),
    "float4":      reflect.TypeOf(float32(0)),
    "float8":      reflect.TypeOf(float64(0)),
    "bool":        reflect.TypeOf(false),
    "text":        reflect.TypeOf(""),
    "varchar":     reflect.TypeOf(""),
    "timestamp":   reflect.TypeOf(time.Time{}),
    "timestamptz": reflect.TypeOf(time.Time{}),
    "uuid":        reflect.TypeOf([16]byte{}),
    "json":        reflect.TypeOf([]byte{}),
    "jsonb":       reflect.TypeOf([]byte{}),
}

// 自定义类型处理
type NullString struct {
    String string
    Valid  bool
}

func (ns *NullString) Scan(value interface{}) error {
    if value == nil {
        ns.String, ns.Valid = "", false
        return nil
    }
    ns.Valid = true
    switch v := value.(type) {
    case string:
        ns.String = v
    case []byte:
        ns.String = string(v)
    default:
        return fmt.Errorf("cannot scan %T into NullString", value)
    }
    return nil
}
```

## 核心组件

### 1. 驱动注册机制

```go
// 驱动注册
func init() {
    sql.Register("postgres", &Driver{})
}

// 驱动接口实现
type Driver struct{}

func (d *Driver) Open(name string) (driver.Conn, error) {
    return Open(name)
}

// 连接接口实现
type conn struct {
    c         net.Conn
    buf       *bufio.Reader
    namei     int
    scratch   [512]byte
    txnStatus txnStatus
    parameterStatus map[string]string
}

func (cn *conn) Prepare(query string) (driver.Stmt, error) {
    return cn.prepareTo(query, cn.gname())
}
```

### 2. 事务管理

```go
// 事务接口实现
func (cn *conn) Begin() (driver.Tx, error) {
    return cn.begin("")
}

func (cn *conn) begin(mode string) (driver.Tx, error) {
    _, err := cn.simpleExec("BEGIN" + mode)
    if err != nil {
        return nil, err
    }
    return cn, nil
}

// 事务提交
func (cn *conn) Commit() error {
    _, err := cn.simpleExec("COMMIT")
    return err
}

// 事务回滚
func (cn *conn) Rollback() error {
    _, err := cn.simpleExec("ROLLBACK")
    return err
}

// 实际使用示例
func transferMoney(db *sql.DB, fromID, toID int, amount float64) error {
    tx, err := db.Begin()
    if err != nil {
        return err
    }
    defer func() {
        if err != nil {
            tx.Rollback()
        } else {
            tx.Commit()
        }
    }()
    
    // 扣款
    _, err = tx.Exec("UPDATE accounts SET balance = balance - $1 WHERE id = $2", amount, fromID)
    if err != nil {
        return err
    }
    
    // 入账
    _, err = tx.Exec("UPDATE accounts SET balance = balance + $1 WHERE id = $2", amount, toID)
    if err != nil {
        return err
    }
    
    return nil
}
```

### 3. 预处理语句

```go
// 预处理语句实现
type stmt struct {
    cn   *conn
    name string
    colNames []string
    colFmtCodes []format
    colTyps []fieldDesc
    closed bool
}

func (st *stmt) Exec(v []driver.Value) (driver.Result, error) {
    return st.exec(v)
}

func (st *stmt) Query(v []driver.Value) (driver.Rows, error) {
    return st.query(v)
}

// 使用示例
func batchInsert(db *sql.DB, users []User) error {
    stmt, err := db.Prepare("INSERT INTO users (name, email, age) VALUES ($1, $2, $3)")
    if err != nil {
        return err
    }
    defer stmt.Close()
    
    for _, user := range users {
        _, err = stmt.Exec(user.Name, user.Email, user.Age)
        if err != nil {
            return err
        }
    }
    return nil
}
```

## 技术亮点

### 1. 纯Go实现

**优势**：
- 无CGO依赖，编译简单
- 跨平台兼容性好
- 部署简单，单一二进制文件
- 调试友好，可以使用Go工具链

```go
// 无需额外的C库依赖
// 编译时不需要PostgreSQL客户端库
go build -o myapp main.go
```

### 2. 完整的PostgreSQL特性支持

#### LISTEN/NOTIFY支持
```go
func setupNotificationListener(db *sql.DB) {
    listener := pq.NewListener(dsn, 10*time.Second, time.Minute, func(ev pq.ListenerEventType, err error) {
        if err != nil {
            log.Printf("Listener error: %v", err)
        }
    })
    defer listener.Close()
    
    err := listener.Listen("user_updates")
    if err != nil {
        log.Fatal(err)
    }
    
    for {
        select {
        case n := <-listener.Notify:
            if n != nil {
                log.Printf("Received notification: %s - %s", n.Channel, n.Extra)
                handleUserUpdate(n.Extra)
            }
        case <-time.After(90 * time.Second):
            go listener.Ping()
        }
    }
}

// 发送通知
func notifyUserUpdate(db *sql.DB, userID int) error {
    _, err := db.Exec("NOTIFY user_updates, $1", fmt.Sprintf(`{"user_id": %d}`, userID))
    return err
}
```

#### COPY协议支持
```go
func bulkInsertWithCopy(db *sql.DB, data [][]string) error {
    txn, err := db.Begin()
    if err != nil {
        return err
    }
    defer txn.Rollback()
    
    stmt, err := txn.Prepare(pq.CopyIn("users", "name", "email", "age"))
    if err != nil {
        return err
    }
    
    for _, row := range data {
        _, err = stmt.Exec(row[0], row[1], row[2])
        if err != nil {
            return err
        }
    }
    
    _, err = stmt.Exec()
    if err != nil {
        return err
    }
    
    err = stmt.Close()
    if err != nil {
        return err
    }
    
    return txn.Commit()
}
```

### 3. 高级数据类型支持

#### 数组类型
```go
import "github.com/lib/pq"

// 插入数组
func insertArrayData(db *sql.DB) error {
    tags := pq.Array([]string{"golang", "postgresql", "database"})
    numbers := pq.Array([]int{1, 2, 3, 4, 5})
    
    _, err := db.Exec("INSERT INTO posts (title, tags, numbers) VALUES ($1, $2, $3)",
        "Sample Post", tags, numbers)
    return err
}

// 查询数组
func queryArrayData(db *sql.DB, postID int) ([]string, []int, error) {
    var tags pq.StringArray
    var numbers pq.Int64Array
    
    err := db.QueryRow("SELECT tags, numbers FROM posts WHERE id = $1", postID).
        Scan(&tags, &numbers)
    if err != nil {
        return nil, nil, err
    }
    
    return []string(tags), []int64(numbers), nil
}
```

#### JSON/JSONB支持
```go
type UserProfile struct {
    Name     string            `json:"name"`
    Settings map[string]string `json:"settings"`
    Metadata interface{}       `json:"metadata"`
}

func insertJSONData(db *sql.DB, profile UserProfile) error {
    profileJSON, err := json.Marshal(profile)
    if err != nil {
        return err
    }
    
    _, err = db.Exec("INSERT INTO users (profile) VALUES ($1)", profileJSON)
    return err
}

func queryJSONData(db *sql.DB, userID int) (*UserProfile, error) {
    var profileJSON []byte
    err := db.QueryRow("SELECT profile FROM users WHERE id = $1", userID).
        Scan(&profileJSON)
    if err != nil {
        return nil, err
    }
    
    var profile UserProfile
    err = json.Unmarshal(profileJSON, &profile)
    if err != nil {
        return nil, err
    }
    
    return &profile, nil
}
```

## 优缺点分析

### 优点

#### 1. 性能优势
- **纯Go实现**：无CGO调用开销
- **连接池管理**：高效的连接复用
- **预处理语句**：减少SQL解析开销
- **批量操作**：支持COPY协议进行高速数据导入

```go
// 性能测试示例
func BenchmarkQuery(b *testing.B) {
    db := setupDB()
    defer db.Close()
    
    stmt, err := db.Prepare("SELECT id, name FROM users WHERE age > $1")
    if err != nil {
        b.Fatal(err)
    }
    defer stmt.Close()
    
    b.ResetTimer()
    for i := 0; i < b.N; i++ {
        rows, err := stmt.Query(25)
        if err != nil {
            b.Fatal(err)
        }
        rows.Close()
    }
}
```

#### 2. 功能完整性
- **完整的PostgreSQL特性支持**
- **丰富的数据类型映射**
- **事务支持**
- **SSL/TLS加密**
- **异步通知机制**

#### 3. 开发友好
- **标准database/sql接口**
- **详细的错误信息**
- **良好的文档和社区支持**
- **活跃的维护**

### 缺点

#### 1. 功能限制
- **不支持连接池的高级特性**（如连接预热、健康检查）
- **缺少内置的重试机制**
- **不支持读写分离**
- **缺少内置的监控指标**

#### 2. 性能考虑
- **单连接性能**：相比C库可能略低
- **内存使用**：Go的GC可能带来延迟
- **大结果集处理**：需要注意内存管理

```go
// 大结果集处理最佳实践
func processLargeResultSet(db *sql.DB) error {
    rows, err := db.Query("SELECT * FROM large_table")
    if err != nil {
        return err
    }
    defer rows.Close()
    
    // 逐行处理，避免一次性加载所有数据到内存
    for rows.Next() {
        var record Record
        err := rows.Scan(&record.ID, &record.Data)
        if err != nil {
            return err
        }
        
        // 处理单条记录
        processRecord(record)
    }
    
    return rows.Err()
}
```

#### 3. 生态系统
- **相比其他语言的PostgreSQL驱动，功能可能不够丰富**
- **第三方扩展较少**
- **ORM集成可能不如专门的驱动**

## 使用场景

### 1. 适用场景

#### Web应用后端
```go
// RESTful API示例
type UserHandler struct {
    db *sql.DB
}

func (h *UserHandler) GetUser(w http.ResponseWriter, r *http.Request) {
    userID := mux.Vars(r)["id"]
    
    var user User
    err := h.db.QueryRow("SELECT id, name, email FROM users WHERE id = $1", userID).
        Scan(&user.ID, &user.Name, &user.Email)
    
    if err == sql.ErrNoRows {
        http.NotFound(w, r)
        return
    } else if err != nil {
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
    
    json.NewEncoder(w).Encode(user)
}

func (h *UserHandler) CreateUser(w http.ResponseWriter, r *http.Request) {
    var user User
    if err := json.NewDecoder(r.Body).Decode(&user); err != nil {
        http.Error(w, err.Error(), http.StatusBadRequest)
        return
    }
    
    err := h.db.QueryRow("INSERT INTO users (name, email) VALUES ($1, $2) RETURNING id",
        user.Name, user.Email).Scan(&user.ID)
    
    if err != nil {
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
    
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(user)
}
```

#### 微服务架构
```go
// 微服务中的数据访问层
type UserService struct {
    db *sql.DB
}

func NewUserService(dsn string) (*UserService, error) {
    db, err := sql.Open("postgres", dsn)
    if err != nil {
        return nil, err
    }
    
    // 配置连接池
    db.SetMaxOpenConns(50)
    db.SetMaxIdleConns(10)
    db.SetConnMaxLifetime(time.Hour)
    
    return &UserService{db: db}, nil
}

func (s *UserService) GetUserByID(ctx context.Context, id int) (*User, error) {
    var user User
    err := s.db.QueryRowContext(ctx, "SELECT id, name, email FROM users WHERE id = $1", id).
        Scan(&user.ID, &user.Name, &user.Email)
    
    if err == sql.ErrNoRows {
        return nil, ErrUserNotFound
    }
    
    return &user, err
}

func (s *UserService) CreateUser(ctx context.Context, user *User) error {
    return s.db.QueryRowContext(ctx,
        "INSERT INTO users (name, email) VALUES ($1, $2) RETURNING id",
        user.Name, user.Email).Scan(&user.ID)
}
```

#### 数据分析应用
```go
// 数据分析查询
func generateUserReport(db *sql.DB, startDate, endDate time.Time) (*UserReport, error) {
    query := `
        SELECT 
            COUNT(*) as total_users,
            COUNT(*) FILTER (WHERE created_at >= $1) as new_users,
            AVG(age) as avg_age,
            COUNT(*) FILTER (WHERE last_login >= $1) as active_users
        FROM users 
        WHERE created_at <= $2
    `
    
    var report UserReport
    err := db.QueryRow(query, startDate, endDate).Scan(
        &report.TotalUsers,
        &report.NewUsers,
        &report.AvgAge,
        &report.ActiveUsers,
    )
    
    return &report, err
}

// 批量数据处理
func processBatchData(db *sql.DB, batchSize int) error {
    offset := 0
    
    for {
        rows, err := db.Query("SELECT id, data FROM raw_data ORDER BY id LIMIT $1 OFFSET $2",
            batchSize, offset)
        if err != nil {
            return err
        }
        
        var processed int
        for rows.Next() {
            var id int
            var data string
            
            if err := rows.Scan(&id, &data); err != nil {
                rows.Close()
                return err
            }
            
            // 处理数据
            processedData := processData(data)
            
            // 插入处理结果
            _, err = db.Exec("INSERT INTO processed_data (raw_id, result) VALUES ($1, $2)",
                id, processedData)
            if err != nil {
                rows.Close()
                return err
            }
            
            processed++
        }
        
        rows.Close()
        
        if processed < batchSize {
            break // 没有更多数据
        }
        
        offset += batchSize
    }
    
    return nil
}
```

### 2. 不适用场景

#### 高并发写入场景
```go
// 问题：大量并发写入可能导致连接池耗尽
// 解决方案：使用消息队列缓冲写入请求

type WriteBuffer struct {
    db     *sql.DB
    buffer chan WriteRequest
    done   chan struct{}
}

func NewWriteBuffer(db *sql.DB, bufferSize int) *WriteBuffer {
    wb := &WriteBuffer{
        db:     db,
        buffer: make(chan WriteRequest, bufferSize),
        done:   make(chan struct{}),
    }
    
    go wb.processWrites()
    return wb
}

func (wb *WriteBuffer) processWrites() {
    ticker := time.NewTicker(100 * time.Millisecond)
    defer ticker.Stop()
    
    var batch []WriteRequest
    
    for {
        select {
        case req := <-wb.buffer:
            batch = append(batch, req)
            if len(batch) >= 100 {
                wb.flushBatch(batch)
                batch = batch[:0]
            }
        case <-ticker.C:
            if len(batch) > 0 {
                wb.flushBatch(batch)
                batch = batch[:0]
            }
        case <-wb.done:
            return
        }
    }
}
```

#### 需要特殊PostgreSQL扩展的场景
```go
// 某些PostgreSQL扩展可能需要特殊的驱动支持
// 例如：PostGIS地理信息系统扩展
// 可能需要使用专门的驱动如pgx
```

## 常见问题与解决方案

### 1. 连接问题

#### 连接超时
```go
// 问题：连接数据库超时
// 解决方案：设置合适的超时参数

func connectWithTimeout(dsn string) (*sql.DB, error) {
    // 在DSN中设置连接超时
    dsn += "&connect_timeout=10"
    
    db, err := sql.Open("postgres", dsn)
    if err != nil {
        return nil, err
    }
    
    // 使用context控制连接超时
    ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
    defer cancel()
    
    err = db.PingContext(ctx)
    if err != nil {
        return nil, fmt.Errorf("failed to connect to database: %w", err)
    }
    
    return db, nil
}
```

#### 连接池耗尽
```go
// 问题：连接池耗尽导致应用阻塞
// 解决方案：合理配置连接池参数

func configureConnectionPool(db *sql.DB) {
    // 根据应用负载调整参数
    maxOpenConns := runtime.NumCPU() * 2
    maxIdleConns := maxOpenConns / 2
    
    db.SetMaxOpenConns(maxOpenConns)
    db.SetMaxIdleConns(maxIdleConns)
    db.SetConnMaxLifetime(time.Hour)
    db.SetConnMaxIdleTime(30 * time.Minute)
}

// 监控连接池状态
func monitorConnectionPool(db *sql.DB) {
    ticker := time.NewTicker(30 * time.Second)
    defer ticker.Stop()
    
    for range ticker.C {
        stats := db.Stats()
        
        // 检查连接池是否接近耗尽
        if stats.OpenConnections >= stats.MaxOpenConnections*0.8 {
            log.Printf("Warning: Connection pool usage high: %d/%d",
                stats.OpenConnections, stats.MaxOpenConnections)
        }
        
        // 检查等待时间是否过长
        if stats.WaitDuration > time.Second {
            log.Printf("Warning: High connection wait time: %v", stats.WaitDuration)
        }
    }
}
```

### 2. 性能问题

#### 慢查询优化
```go
// 问题：查询性能差
// 解决方案：使用EXPLAIN分析查询计划

func analyzeQuery(db *sql.DB, query string, args ...interface{}) error {
    explainQuery := "EXPLAIN (ANALYZE, BUFFERS, VERBOSE) " + query
    
    rows, err := db.Query(explainQuery, args...)
    if err != nil {
        return err
    }
    defer rows.Close()
    
    fmt.Println("Query Plan:")
    for rows.Next() {
        var line string
        if err := rows.Scan(&line); err != nil {
            return err
        }
        fmt.Println(line)
    }
    
    return rows.Err()
}

// 使用索引提示
func optimizedQuery(db *sql.DB, userID int) (*User, error) {
    // 确保有合适的索引
    query := `
        SELECT id, name, email 
        FROM users 
        WHERE id = $1  -- 确保id字段有索引
    `
    
    var user User
    err := db.QueryRow(query, userID).Scan(&user.ID, &user.Name, &user.Email)
    return &user, err
}
```

#### 批量操作优化
```go
// 问题：大量单条插入性能差
// 解决方案：使用批量插入

func batchInsertOptimized(db *sql.DB, users []User) error {
    // 方法1：使用VALUES子句批量插入
    if len(users) == 0 {
        return nil
    }
    
    valueStrings := make([]string, 0, len(users))
    valueArgs := make([]interface{}, 0, len(users)*3)
    
    for i, user := range users {
        valueStrings = append(valueStrings, fmt.Sprintf("($%d, $%d, $%d)",
            i*3+1, i*3+2, i*3+3))
        valueArgs = append(valueArgs, user.Name, user.Email, user.Age)
    }
    
    query := fmt.Sprintf("INSERT INTO users (name, email, age) VALUES %s",
        strings.Join(valueStrings, ","))
    
    _, err := db.Exec(query, valueArgs...)
    return err
}

func batchInsertWithCOPY(db *sql.DB, users []User) error {
    // 方法2：使用COPY协议（最快）
    txn, err := db.Begin()
    if err != nil {
        return err
    }
    defer txn.Rollback()
    
    stmt, err := txn.Prepare(pq.CopyIn("users", "name", "email", "age"))
    if err != nil {
        return err
    }
    
    for _, user := range users {
        _, err = stmt.Exec(user.Name, user.Email, user.Age)
        if err != nil {
            return err
        }
    }
    
    _, err = stmt.Exec()
    if err != nil {
        return err
    }
    
    err = stmt.Close()
    if err != nil {
        return err
    }
    
    return txn.Commit()
}
```

### 3. 事务问题

#### 死锁处理
```go
// 问题：事务死锁
// 解决方案：实现重试机制

func executeWithRetry(db *sql.DB, operation func(*sql.Tx) error, maxRetries int) error {
    for attempt := 0; attempt <= maxRetries; attempt++ {
        tx, err := db.Begin()
        if err != nil {
            return err
        }
        
        err = operation(tx)
        if err != nil {
            tx.Rollback()
            
            // 检查是否是死锁错误
            if pqErr, ok := err.(*pq.Error); ok {
                if pqErr.Code == "40P01" { // deadlock_detected
                    if attempt < maxRetries {
                        // 随机延迟后重试
                        time.Sleep(time.Duration(rand.Intn(100)) * time.Millisecond)
                        continue
                    }
                }
            }
            
            return err
        }
        
        err = tx.Commit()
        if err != nil {
            return err
        }
        
        return nil
    }
    
    return fmt.Errorf("operation failed after %d retries", maxRetries)
}

// 使用示例
func transferMoneyWithRetry(db *sql.DB, fromID, toID int, amount float64) error {
    return executeWithRetry(db, func(tx *sql.Tx) error {
        // 按固定顺序获取锁，避免死锁
        firstID, secondID := fromID, toID
        if fromID > toID {
            firstID, secondID = toID, fromID
        }
        
        // 锁定账户（按ID顺序）
        _, err := tx.Exec("SELECT balance FROM accounts WHERE id = $1 FOR UPDATE", firstID)
        if err != nil {
            return err
        }
        
        _, err = tx.Exec("SELECT balance FROM accounts WHERE id = $1 FOR UPDATE", secondID)
        if err != nil {
            return err
        }
        
        // 执行转账
        _, err = tx.Exec("UPDATE accounts SET balance = balance - $1 WHERE id = $2", amount, fromID)
        if err != nil {
            return err
        }
        
        _, err = tx.Exec("UPDATE accounts SET balance = balance + $1 WHERE id = $2", amount, toID)
        return err
    }, 3)
}
```

#### 长事务处理
```go
// 问题：长事务导致锁等待
// 解决方案：拆分事务或使用乐观锁

func updateUserWithOptimisticLock(db *sql.DB, userID int, updateFunc func(*User) error) error {
    for attempt := 0; attempt < 10; attempt++ {
        // 读取当前版本
        var user User
        var version int
        err := db.QueryRow("SELECT id, name, email, version FROM users WHERE id = $1",
            userID).Scan(&user.ID, &user.Name, &user.Email, &version)
        if err != nil {
            return err
        }
        
        // 应用更新
        err = updateFunc(&user)
        if err != nil {
            return err
        }
        
        // 尝试更新（检查版本）
        result, err := db.Exec(
            "UPDATE users SET name = $1, email = $2, version = version + 1 WHERE id = $3 AND version = $4",
            user.Name, user.Email, userID, version)
        if err != nil {
            return err
        }
        
        rowsAffected, err := result.RowsAffected()
        if err != nil {
            return err
        }
        
        if rowsAffected == 1 {
            return nil // 更新成功
        }
        
        // 版本冲突，重试
        time.Sleep(time.Duration(rand.Intn(10)) * time.Millisecond)
    }
    
    return fmt.Errorf("failed to update user after multiple attempts")
}
```

### 4. 内存问题

#### 大结果集处理
```go
// 问题：大结果集导致内存溢出
// 解决方案：流式处理

func processLargeDataset(db *sql.DB, batchSize int, processor func([]Record) error) error {
    offset := 0
    
    for {
        rows, err := db.Query(
            "SELECT id, data FROM large_table ORDER BY id LIMIT $1 OFFSET $2",
            batchSize, offset)
        if err != nil {
            return err
        }
        
        var batch []Record
        for rows.Next() {
            var record Record
            if err := rows.Scan(&record.ID, &record.Data); err != nil {
                rows.Close()
                return err
            }
            batch = append(batch, record)
        }
        
        rows.Close()
        
        if len(batch) == 0 {
            break
        }
        
        if err := processor(batch); err != nil {
            return err
        }
        
        if len(batch) < batchSize {
            break
        }
        
        offset += batchSize
    }
    
    return nil
}

// 使用游标处理大结果集
func processWithCursor(db *sql.DB, processor func(Record) error) error {
    tx, err := db.Begin()
    if err != nil {
        return err
    }
    defer tx.Rollback()
    
    // 声明游标
    _, err = tx.Exec("DECLARE large_cursor CURSOR FOR SELECT id, data FROM large_table")
    if err != nil {
        return err
    }
    
    for {
        rows, err := tx.Query("FETCH 1000 FROM large_cursor")
        if err != nil {
            return err
        }
        
        var count int
        for rows.Next() {
            var record Record
            if err := rows.Scan(&record.ID, &record.Data); err != nil {
                rows.Close()
                return err
            }
            
            if err := processor(record); err != nil {
                rows.Close()
                return err
            }
            count++
        }
        
        rows.Close()
        
        if count == 0 {
            break
        }
    }
    
    return tx.Commit()
}
```

## 最佳实践

### 1. 连接管理

```go
// 单例数据库连接
var (
    db   *sql.DB
    once sync.Once
)

func GetDB() *sql.DB {
    once.Do(func() {
        var err error
        db, err = initDB()
        if err != nil {
            log.Fatal("Failed to initialize database:", err)
        }
    })
    return db
}

func initDB() (*sql.DB, error) {
    db, err := sql.Open("postgres", os.Getenv("DATABASE_URL"))
    if err != nil {
        return nil, err
    }
    
    // 配置连接池
    db.SetMaxOpenConns(100)
    db.SetMaxIdleConns(10)
    db.SetConnMaxLifetime(time.Hour)
    db.SetConnMaxIdleTime(30 * time.Minute)
    
    // 验证连接
    ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
    defer cancel()
    
    if err := db.PingContext(ctx); err != nil {
        return nil, err
    }
    
    return db, nil
}
```

### 2. 错误处理

```go
// 统一错误处理
func handleDBError(err error) error {
    if err == nil {
        return nil
    }
    
    if err == sql.ErrNoRows {
        return ErrNotFound
    }
    
    if pqErr, ok := err.(*pq.Error); ok {
        switch pqErr.Code {
        case "23505": // unique_violation
            return ErrDuplicateKey
        case "23503": // foreign_key_violation
            return ErrForeignKeyViolation
        case "23514": // check_violation
            return ErrCheckViolation
        case "40P01": // deadlock_detected
            return ErrDeadlock
        }
    }
    
    return err
}

// 使用示例
func CreateUser(db *sql.DB, user *User) error {
    err := db.QueryRow(
        "INSERT INTO users (name, email) VALUES ($1, $2) RETURNING id",
        user.Name, user.Email).Scan(&user.ID)
    
    return handleDBError(err)
}
```

### 3. 查询优化

```go
// 使用预处理语句
type UserRepository struct {
    db              *sql.DB
    getUserStmt     *sql.Stmt
    createUserStmt  *sql.Stmt
    updateUserStmt  *sql.Stmt
}

func NewUserRepository(db *sql.DB) (*UserRepository, error) {
    repo := &UserRepository{db: db}
    
    var err error
    repo.getUserStmt, err = db.Prepare("SELECT id, name, email FROM users WHERE id = $1")
    if err != nil {
        return nil, err
    }
    
    repo.createUserStmt, err = db.Prepare("INSERT INTO users (name, email) VALUES ($1, $2) RETURNING id")
    if err != nil {
        return nil, err
    }
    
    repo.updateUserStmt, err = db.Prepare("UPDATE users SET name = $1, email = $2 WHERE id = $3")
    if err != nil {
        return nil, err
    }
    
    return repo, nil
}

func (r *UserRepository) GetUser(id int) (*User, error) {
    var user User
    err := r.getUserStmt.QueryRow(id).Scan(&user.ID, &user.Name, &user.Email)
    if err != nil {
        return nil, handleDBError(err)
    }
    return &user, nil
}

func (r *UserRepository) Close() error {
    var errs []error
    
    if err := r.getUserStmt.Close(); err != nil {
        errs = append(errs, err)
    }
    if err := r.createUserStmt.Close(); err != nil {
        errs = append(errs, err)
    }
    if err := r.updateUserStmt.Close(); err != nil {
        errs = append(errs, err)
    }
    
    if len(errs) > 0 {
        return fmt.Errorf("errors closing statements: %v", errs)
    }
    
    return nil
}
```

### 4. 监控和日志

```go
// 数据库操作监控
type DBMonitor struct {
    db *sql.DB
}

func (m *DBMonitor) LogStats() {
    stats := m.db.Stats()
    
    log.Printf("DB Stats - Open: %d, InUse: %d, Idle: %d, WaitCount: %d, WaitDuration: %v",
        stats.OpenConnections,
        stats.InUse,
        stats.Idle,
        stats.WaitCount,
        stats.WaitDuration)
}

// 查询执行时间监控
func (m *DBMonitor) QueryWithMetrics(query string, args ...interface{}) (*sql.Rows, error) {
    start := time.Now()
    rows, err := m.db.Query(query, args...)
    duration := time.Since(start)
    
    log.Printf("Query executed in %v: %s", duration, query)
    
    if duration > time.Second {
        log.Printf("SLOW QUERY WARNING: %s took %v", query, duration)
    }
    
    return rows, err
}

// 健康检查
func (m *DBMonitor) HealthCheck() error {
    ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
    defer cancel()
    
    return m.db.PingContext(ctx)
}
```

### 5. 测试

```go
// 数据库测试工具
func setupTestDB() *sql.DB {
    db, err := sql.Open("postgres", "postgres://test:test@localhost/testdb?sslmode=disable")
    if err != nil {
        panic(err)
    }
    
    // 创建测试表
    _, err = db.Exec(`
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(100) UNIQUE NOT NULL
        )
    `)
    if err != nil {
        panic(err)
    }
    
    return db
}

func cleanupTestDB(db *sql.DB) {
    db.Exec("TRUNCATE TABLE users RESTART IDENTITY")
}

// 测试示例
func TestUserRepository(t *testing.T) {
    db := setupTestDB()
    defer db.Close()
    defer cleanupTestDB(db)
    
    repo, err := NewUserRepository(db)
    if err != nil {
        t.Fatal(err)
    }
    defer repo.Close()
    
    // 测试创建用户
    user := &User{Name: "Test User", Email: "test@example.com"}
    err = repo.CreateUser(user)
    if err != nil {
        t.Fatal(err)
    }
    
    // 测试获取用户
    retrieved, err := repo.GetUser(user.ID)
    if err != nil {
        t.Fatal(err)
    }
    
    if retrieved.Name != user.Name || retrieved.Email != user.Email {
        t.Errorf("Retrieved user doesn't match: got %+v, want %+v", retrieved, user)
    }
}
```

这个文档提供了pq驱动的全面技术指南，涵盖了核心原理、组件、优缺点、使用场景和最佳实践。接下来我将创建更多专门的文档来补充面试资料。