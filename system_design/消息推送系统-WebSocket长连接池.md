# 消息推送系统：WebSocket + 长连接池的实时通信架构

## 1. 系统概述

### 1.1 业务场景
- **用户规模**: 1000万+在线用户
- **消息类型**: 即时消息、系统通知、直播弹幕、状态更新
- **性能要求**:
  - 消息延迟: < 100ms
  - 连接并发: 100万+
  - 消息吞吐: 100万条/秒
  - 可用性: 99.99%

### 1.2 技术挑战
- **海量长连接**: 百万级WebSocket连接管理
- **消息路由**: 高效的消息分发和路由
- **连接保活**: 网络断线检测和自动重连
- **水平扩展**: 多节点间的连接和消息同步
- **消息可靠性**: 消息确认和重试机制

---

## 2. 整体架构设计

### 2.1 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        客户端层                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Web App   │  │ Mobile App  │  │   Desktop   │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
├─────────────────────────────────────────────────────────────┤
│                      负载均衡层                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Nginx 1   │  │   Nginx 2   │  │   Nginx 3   │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
├─────────────────────────────────────────────────────────────┤
│                    WebSocket网关层                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │  Gateway 1  │  │  Gateway 2  │  │  Gateway 3  │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
├─────────────────────────────────────────────────────────────┤
│                      业务服务层                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │  消息服务   │  │  用户服务   │  │  推送服务   │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
├─────────────────────────────────────────────────────────────┤
│                      中间件层                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │    Redis    │  │    Kafka    │  │   Consul    │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
├─────────────────────────────────────────────────────────────┤
│                      数据存储层                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │    MySQL    │  │  MongoDB    │  │ ElasticSearch│         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 核心组件

#### WebSocket网关
- **连接管理**: 维护海量WebSocket长连接
- **消息路由**: 根据用户ID路由消息到对应连接
- **负载均衡**: 连接在多个网关节点间均匀分布
- **心跳检测**: 检测连接状态，清理无效连接

#### 消息服务
- **消息处理**: 消息的接收、验证、转换
- **消息存储**: 离线消息存储和历史消息查询
- **消息推送**: 实时消息推送和批量推送

#### 连接池管理
- **连接注册**: 用户连接信息注册和维护
- **连接路由**: 根据用户ID查找对应的网关节点
- **连接监控**: 连接状态监控和统计

---

## 3. WebSocket网关实现

### 3.1 连接管理器

#### 基础数据结构
```go
package gateway

import (
    "context"
    "encoding/json"
    "fmt"
    "log"
    "net/http"
    "sync"
    "time"
    
    "github.com/gorilla/websocket"
    "github.com/go-redis/redis/v8"
)

// WebSocket连接
type Connection struct {
    ID          string
    UserID      int64
    Conn        *websocket.Conn
    Send        chan []byte
    LastPing    time.Time
    Metadata    map[string]interface{}
    mu          sync.RWMutex
}

// 连接管理器
type ConnectionManager struct {
    connections    map[string]*Connection    // 连接ID -> 连接
    userConns      map[int64][]*Connection  // 用户ID -> 连接列表
    mu             sync.RWMutex
    register       chan *Connection
    unregister     chan *Connection
    broadcast      chan *Message
    redis          *redis.Client
    nodeID         string
    heartbeatInterval time.Duration
}

// 消息结构
type Message struct {
    ID        string                 `json:"id"`
    Type      string                 `json:"type"`
    From      int64                  `json:"from"`
    To        int64                  `json:"to"`
    Content   interface{}            `json:"content"`
    Timestamp int64                  `json:"timestamp"`
    Metadata  map[string]interface{} `json:"metadata,omitempty"`
}

// 创建连接管理器
func NewConnectionManager(nodeID string, redisClient *redis.Client) *ConnectionManager {
    return &ConnectionManager{
        connections:       make(map[string]*Connection),
        userConns:        make(map[int64][]*Connection),
        register:         make(chan *Connection, 1000),
        unregister:       make(chan *Connection, 1000),
        broadcast:        make(chan *Message, 10000),
        redis:            redisClient,
        nodeID:           nodeID,
        heartbeatInterval: 30 * time.Second,
    }
}
```

#### 连接生命周期管理
```go
// 启动连接管理器
func (cm *ConnectionManager) Start() {
    go cm.run()
    go cm.heartbeatChecker()
    go cm.messageProcessor()
}

// 主运行循环
func (cm *ConnectionManager) run() {
    for {
        select {
        case conn := <-cm.register:
            cm.registerConnection(conn)
            
        case conn := <-cm.unregister:
            cm.unregisterConnection(conn)
            
        case message := <-cm.broadcast:
            cm.broadcastMessage(message)
        }
    }
}

// 注册连接
func (cm *ConnectionManager) registerConnection(conn *Connection) {
    cm.mu.Lock()
    defer cm.mu.Unlock()
    
    // 添加到连接映射
    cm.connections[conn.ID] = conn
    
    // 添加到用户连接映射
    cm.userConns[conn.UserID] = append(cm.userConns[conn.UserID], conn)
    
    // 在Redis中注册连接信息
    connInfo := map[string]interface{}{
        "node_id":    cm.nodeID,
        "conn_id":    conn.ID,
        "user_id":    conn.UserID,
        "created_at": time.Now().Unix(),
    }
    
    data, _ := json.Marshal(connInfo)
    cm.redis.HSet(context.Background(), "connections", conn.ID, data)
    cm.redis.SAdd(context.Background(), fmt.Sprintf("user_conns:%d", conn.UserID), conn.ID)
    
    log.Printf("Connection registered: %s for user %d", conn.ID, conn.UserID)
    
    // 启动连接处理协程
    go cm.handleConnection(conn)
}

// 注销连接
func (cm *ConnectionManager) unregisterConnection(conn *Connection) {
    cm.mu.Lock()
    defer cm.mu.Unlock()
    
    // 从连接映射中删除
    delete(cm.connections, conn.ID)
    
    // 从用户连接映射中删除
    userConns := cm.userConns[conn.UserID]
    for i, c := range userConns {
        if c.ID == conn.ID {
            cm.userConns[conn.UserID] = append(userConns[:i], userConns[i+1:]...)
            break
        }
    }
    
    // 如果用户没有其他连接，删除用户映射
    if len(cm.userConns[conn.UserID]) == 0 {
        delete(cm.userConns, conn.UserID)
    }
    
    // 从Redis中删除连接信息
    cm.redis.HDel(context.Background(), "connections", conn.ID)
    cm.redis.SRem(context.Background(), fmt.Sprintf("user_conns:%d", conn.UserID), conn.ID)
    
    // 关闭连接
    close(conn.Send)
    conn.Conn.Close()
    
    log.Printf("Connection unregistered: %s for user %d", conn.ID, conn.UserID)
}

// 处理单个连接
func (cm *ConnectionManager) handleConnection(conn *Connection) {
    defer func() {
        cm.unregister <- conn
    }()
    
    // 启动写协程
    go cm.writeLoop(conn)
    
    // 读循环
    cm.readLoop(conn)
}

// 读循环
func (cm *ConnectionManager) readLoop(conn *Connection) {
    defer conn.Conn.Close()
    
    // 设置读取超时
    conn.Conn.SetReadDeadline(time.Now().Add(60 * time.Second))
    conn.Conn.SetPongHandler(func(string) error {
        conn.mu.Lock()
        conn.LastPing = time.Now()
        conn.mu.Unlock()
        conn.Conn.SetReadDeadline(time.Now().Add(60 * time.Second))
        return nil
    })
    
    for {
        _, messageData, err := conn.Conn.ReadMessage()
        if err != nil {
            if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
                log.Printf("WebSocket error: %v", err)
            }
            break
        }
        
        // 解析消息
        var message Message
        if err := json.Unmarshal(messageData, &message); err != nil {
            log.Printf("Invalid message format: %v", err)
            continue
        }
        
        // 设置消息来源
        message.From = conn.UserID
        message.Timestamp = time.Now().Unix()
        
        // 处理消息
        cm.handleMessage(conn, &message)
    }
}

// 写循环
func (cm *ConnectionManager) writeLoop(conn *Connection) {
    ticker := time.NewTicker(54 * time.Second)
    defer func() {
        ticker.Stop()
        conn.Conn.Close()
    }()
    
    for {
        select {
        case message, ok := <-conn.Send:
            conn.Conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
            if !ok {
                conn.Conn.WriteMessage(websocket.CloseMessage, []byte{})
                return
            }
            
            if err := conn.Conn.WriteMessage(websocket.TextMessage, message); err != nil {
                log.Printf("Write error: %v", err)
                return
            }
            
        case <-ticker.C:
            conn.Conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
            if err := conn.Conn.WriteMessage(websocket.PingMessage, nil); err != nil {
                return
            }
        }
    }
}
```

### 3.2 消息路由

#### 消息处理器
```go
// 处理消息
func (cm *ConnectionManager) handleMessage(conn *Connection, message *Message) {
    switch message.Type {
    case "ping":
        cm.handlePing(conn)
    case "chat":
        cm.handleChatMessage(conn, message)
    case "join_room":
        cm.handleJoinRoom(conn, message)
    case "leave_room":
        cm.handleLeaveRoom(conn, message)
    case "broadcast":
        cm.handleBroadcast(conn, message)
    default:
        log.Printf("Unknown message type: %s", message.Type)
    }
}

// 处理ping消息
func (cm *ConnectionManager) handlePing(conn *Connection) {
    pong := &Message{
        Type:      "pong",
        Timestamp: time.Now().Unix(),
    }
    
    data, _ := json.Marshal(pong)
    select {
    case conn.Send <- data:
    default:
        close(conn.Send)
    }
}

// 处理聊天消息
func (cm *ConnectionManager) handleChatMessage(conn *Connection, message *Message) {
    // 验证消息
    if message.To == 0 {
        log.Printf("Invalid chat message: missing recipient")
        return
    }
    
    // 存储消息到数据库
    go cm.storeMessage(message)
    
    // 路由消息
    cm.routeMessage(message)
}

// 路由消息
func (cm *ConnectionManager) routeMessage(message *Message) {
    // 检查目标用户是否在本节点
    cm.mu.RLock()
    targetConns := cm.userConns[message.To]
    cm.mu.RUnlock()
    
    if len(targetConns) > 0 {
        // 本地投递
        cm.deliverToLocalConnections(targetConns, message)
    } else {
        // 跨节点投递
        cm.deliverToRemoteNode(message)
    }
}

// 本地投递
func (cm *ConnectionManager) deliverToLocalConnections(conns []*Connection, message *Message) {
    data, err := json.Marshal(message)
    if err != nil {
        log.Printf("Failed to marshal message: %v", err)
        return
    }
    
    for _, conn := range conns {
        select {
        case conn.Send <- data:
        default:
            // 连接阻塞，关闭连接
            close(conn.Send)
        }
    }
}

// 跨节点投递
func (cm *ConnectionManager) deliverToRemoteNode(message *Message) {
    // 查找目标用户的连接信息
    connIDs, err := cm.redis.SMembers(context.Background(), fmt.Sprintf("user_conns:%d", message.To)).Result()
    if err != nil {
        log.Printf("Failed to get user connections: %v", err)
        return
    }
    
    for _, connID := range connIDs {
        // 获取连接信息
        connData, err := cm.redis.HGet(context.Background(), "connections", connID).Result()
        if err != nil {
            continue
        }
        
        var connInfo map[string]interface{}
        if err := json.Unmarshal([]byte(connData), &connInfo); err != nil {
            continue
        }
        
        nodeID := connInfo["node_id"].(string)
        if nodeID != cm.nodeID {
            // 发送到目标节点
            cm.sendToNode(nodeID, message)
        }
    }
}

// 发送消息到指定节点
func (cm *ConnectionManager) sendToNode(nodeID string, message *Message) {
    // 通过消息队列发送到目标节点
    routeMessage := &RouteMessage{
        TargetNode: nodeID,
        Message:    message,
    }
    
    data, _ := json.Marshal(routeMessage)
    cm.redis.Publish(context.Background(), fmt.Sprintf("node:%s", nodeID), data)
}

type RouteMessage struct {
    TargetNode string   `json:"target_node"`
    Message    *Message `json:"message"`
}
```

### 3.3 房间管理

#### 房间数据结构
```go
// 房间管理器
type RoomManager struct {
    rooms   map[string]*Room
    mu      sync.RWMutex
    redis   *redis.Client
    nodeID  string
}

// 房间
type Room struct {
    ID          string
    Name        string
    Members     map[int64]*Connection
    MaxMembers  int
    CreatedAt   time.Time
    mu          sync.RWMutex
}

// 创建房间管理器
func NewRoomManager(nodeID string, redisClient *redis.Client) *RoomManager {
    return &RoomManager{
        rooms:  make(map[string]*Room),
        redis:  redisClient,
        nodeID: nodeID,
    }
}

// 加入房间
func (rm *RoomManager) JoinRoom(roomID string, conn *Connection) error {
    rm.mu.Lock()
    defer rm.mu.Unlock()
    
    room, exists := rm.rooms[roomID]
    if !exists {
        // 创建新房间
        room = &Room{
            ID:         roomID,
            Members:    make(map[int64]*Connection),
            MaxMembers: 1000,
            CreatedAt:  time.Now(),
        }
        rm.rooms[roomID] = room
    }
    
    room.mu.Lock()
    defer room.mu.Unlock()
    
    // 检查房间是否已满
    if len(room.Members) >= room.MaxMembers {
        return fmt.Errorf("room is full")
    }
    
    // 添加成员
    room.Members[conn.UserID] = conn
    
    // 在Redis中记录房间成员
    rm.redis.SAdd(context.Background(), fmt.Sprintf("room:%s:members", roomID), conn.UserID)
    rm.redis.HSet(context.Background(), fmt.Sprintf("room:%s:connections", roomID), fmt.Sprintf("%d", conn.UserID), fmt.Sprintf("%s:%s", rm.nodeID, conn.ID))
    
    // 通知房间其他成员
    joinMessage := &Message{
        Type:      "user_joined",
        From:      0,
        Content:   map[string]interface{}{"user_id": conn.UserID, "room_id": roomID},
        Timestamp: time.Now().Unix(),
    }
    
    rm.broadcastToRoom(room, joinMessage, conn.UserID)
    
    log.Printf("User %d joined room %s", conn.UserID, roomID)
    return nil
}

// 离开房间
func (rm *RoomManager) LeaveRoom(roomID string, conn *Connection) error {
    rm.mu.Lock()
    defer rm.mu.Unlock()
    
    room, exists := rm.rooms[roomID]
    if !exists {
        return fmt.Errorf("room not found")
    }
    
    room.mu.Lock()
    defer room.mu.Unlock()
    
    // 移除成员
    delete(room.Members, conn.UserID)
    
    // 从Redis中移除
    rm.redis.SRem(context.Background(), fmt.Sprintf("room:%s:members", roomID), conn.UserID)
    rm.redis.HDel(context.Background(), fmt.Sprintf("room:%s:connections", roomID), fmt.Sprintf("%d", conn.UserID))
    
    // 如果房间为空，删除房间
    if len(room.Members) == 0 {
        delete(rm.rooms, roomID)
        rm.redis.Del(context.Background(), fmt.Sprintf("room:%s:members", roomID))
        rm.redis.Del(context.Background(), fmt.Sprintf("room:%s:connections", roomID))
    } else {
        // 通知房间其他成员
        leaveMessage := &Message{
            Type:      "user_left",
            From:      0,
            Content:   map[string]interface{}{"user_id": conn.UserID, "room_id": roomID},
            Timestamp: time.Now().Unix(),
        }
        
        rm.broadcastToRoom(room, leaveMessage, conn.UserID)
    }
    
    log.Printf("User %d left room %s", conn.UserID, roomID)
    return nil
}

// 房间广播
func (rm *RoomManager) broadcastToRoom(room *Room, message *Message, excludeUserID int64) {
    data, err := json.Marshal(message)
    if err != nil {
        log.Printf("Failed to marshal room message: %v", err)
        return
    }
    
    for userID, conn := range room.Members {
        if userID != excludeUserID {
            select {
            case conn.Send <- data:
            default:
                // 连接阻塞，从房间中移除
                delete(room.Members, userID)
                close(conn.Send)
            }
        }
    }
}

// 跨节点房间广播
func (rm *RoomManager) BroadcastToRoomGlobal(roomID string, message *Message, excludeUserID int64) {
    // 获取房间所有成员的连接信息
    connections, err := rm.redis.HGetAll(context.Background(), fmt.Sprintf("room:%s:connections", roomID)).Result()
    if err != nil {
        log.Printf("Failed to get room connections: %v", err)
        return
    }
    
    // 按节点分组
    nodeMessages := make(map[string][]*Message)
    
    for userIDStr, connInfo := range connections {
        userID, _ := strconv.ParseInt(userIDStr, 10, 64)
        if userID == excludeUserID {
            continue
        }
        
        parts := strings.Split(connInfo, ":")
        if len(parts) != 2 {
            continue
        }
        
        nodeID := parts[0]
        if nodeID == rm.nodeID {
            // 本地投递
            rm.mu.RLock()
            if room, exists := rm.rooms[roomID]; exists {
                if conn, exists := room.Members[userID]; exists {
                    data, _ := json.Marshal(message)
                    select {
                    case conn.Send <- data:
                    default:
                        close(conn.Send)
                    }
                }
            }
            rm.mu.RUnlock()
        } else {
            // 远程投递
            nodeMessages[nodeID] = append(nodeMessages[nodeID], message)
        }
    }
    
    // 发送到远程节点
    for nodeID, messages := range nodeMessages {
        for _, msg := range messages {
            rm.sendToNode(nodeID, msg)
        }
    }
}
```

---

## 4. 连接池优化

### 4.1 连接池管理

#### 连接池实现
```go
package pool

import (
    "context"
    "sync"
    "sync/atomic"
    "time"
)

// 连接池
type ConnectionPool struct {
    factory    ConnectionFactory
    pool       chan *PooledConnection
    mu         sync.RWMutex
    minSize    int
    maxSize    int
    currentSize int64
    maxIdleTime time.Duration
    closed     bool
}

// 池化连接
type PooledConnection struct {
    conn       *Connection
    pool       *ConnectionPool
    lastUsed   time.Time
    inUse      bool
    mu         sync.RWMutex
}

// 连接工厂
type ConnectionFactory interface {
    Create() (*Connection, error)
    Validate(*Connection) bool
    Close(*Connection) error
}

// 创建连接池
func NewConnectionPool(factory ConnectionFactory, minSize, maxSize int, maxIdleTime time.Duration) *ConnectionPool {
    pool := &ConnectionPool{
        factory:     factory,
        pool:        make(chan *PooledConnection, maxSize),
        minSize:     minSize,
        maxSize:     maxSize,
        maxIdleTime: maxIdleTime,
    }
    
    // 预创建最小连接数
    for i := 0; i < minSize; i++ {
        conn, err := factory.Create()
        if err != nil {
            continue
        }
        
        pooledConn := &PooledConnection{
            conn:     conn,
            pool:     pool,
            lastUsed: time.Now(),
        }
        
        pool.pool <- pooledConn
        atomic.AddInt64(&pool.currentSize, 1)
    }
    
    // 启动清理协程
    go pool.cleaner()
    
    return pool
}

// 获取连接
func (p *ConnectionPool) Get(ctx context.Context) (*PooledConnection, error) {
    if p.closed {
        return nil, fmt.Errorf("connection pool is closed")
    }
    
    select {
    case conn := <-p.pool:
        // 验证连接有效性
        if p.factory.Validate(conn.conn) {
            conn.mu.Lock()
            conn.inUse = true
            conn.lastUsed = time.Now()
            conn.mu.Unlock()
            return conn, nil
        } else {
            // 连接无效，关闭并创建新连接
            p.factory.Close(conn.conn)
            atomic.AddInt64(&p.currentSize, -1)
            return p.createNewConnection()
        }
        
    case <-ctx.Done():
        return nil, ctx.Err()
        
    default:
        // 池中没有可用连接，尝试创建新连接
        if atomic.LoadInt64(&p.currentSize) < int64(p.maxSize) {
            return p.createNewConnection()
        }
        
        // 等待连接归还
        select {
        case conn := <-p.pool:
            if p.factory.Validate(conn.conn) {
                conn.mu.Lock()
                conn.inUse = true
                conn.lastUsed = time.Now()
                conn.mu.Unlock()
                return conn, nil
            } else {
                p.factory.Close(conn.conn)
                atomic.AddInt64(&p.currentSize, -1)
                return p.createNewConnection()
            }
        case <-ctx.Done():
            return nil, ctx.Err()
        }
    }
}

// 创建新连接
func (p *ConnectionPool) createNewConnection() (*PooledConnection, error) {
    conn, err := p.factory.Create()
    if err != nil {
        return nil, err
    }
    
    pooledConn := &PooledConnection{
        conn:     conn,
        pool:     p,
        lastUsed: time.Now(),
        inUse:    true,
    }
    
    atomic.AddInt64(&p.currentSize, 1)
    return pooledConn, nil
}

// 归还连接
func (pc *PooledConnection) Release() {
    pc.mu.Lock()
    defer pc.mu.Unlock()
    
    if !pc.inUse {
        return
    }
    
    pc.inUse = false
    pc.lastUsed = time.Now()
    
    select {
    case pc.pool.pool <- pc:
        // 成功归还到池中
    default:
        // 池已满，关闭连接
        pc.pool.factory.Close(pc.conn)
        atomic.AddInt64(&pc.pool.currentSize, -1)
    }
}

// 清理器
func (p *ConnectionPool) cleaner() {
    ticker := time.NewTicker(30 * time.Second)
    defer ticker.Stop()
    
    for range ticker.C {
        if p.closed {
            return
        }
        
        p.cleanIdleConnections()
    }
}

// 清理空闲连接
func (p *ConnectionPool) cleanIdleConnections() {
    now := time.Now()
    var toClose []*PooledConnection
    
    // 从池中取出空闲连接进行检查
    for {
        select {
        case conn := <-p.pool:
            conn.mu.RLock()
            if !conn.inUse && now.Sub(conn.lastUsed) > p.maxIdleTime {
                toClose = append(toClose, conn)
            } else {
                // 连接仍然有效，放回池中
                select {
                case p.pool <- conn:
                default:
                    toClose = append(toClose, conn)
                }
            }
            conn.mu.RUnlock()
        default:
            // 池中没有更多连接
            goto cleanup
        }
    }
    
cleanup:
    // 关闭需要清理的连接
    for _, conn := range toClose {
        p.factory.Close(conn.conn)
        atomic.AddInt64(&p.currentSize, -1)
    }
    
    // 确保最小连接数
    currentSize := atomic.LoadInt64(&p.currentSize)
    for int(currentSize) < p.minSize {
        conn, err := p.factory.Create()
        if err != nil {
            break
        }
        
        pooledConn := &PooledConnection{
            conn:     conn,
            pool:     p,
            lastUsed: time.Now(),
        }
        
        select {
        case p.pool <- pooledConn:
            atomic.AddInt64(&p.currentSize, 1)
            currentSize++
        default:
            p.factory.Close(conn)
            break
        }
    }
}
```

### 4.2 负载均衡

#### 一致性哈希负载均衡
```go
package balancer

import (
    "crypto/sha1"
    "fmt"
    "sort"
    "sync"
)

// 负载均衡器
type LoadBalancer struct {
    nodes    map[string]*Node
    ring     []uint32
    nodeMap  map[uint32]*Node
    replicas int
    mu       sync.RWMutex
}

// 节点
type Node struct {
    ID       string
    Address  string
    Weight   int
    Active   bool
    ConnCount int64
    mu       sync.RWMutex
}

// 创建负载均衡器
func NewLoadBalancer(replicas int) *LoadBalancer {
    return &LoadBalancer{
        nodes:    make(map[string]*Node),
        nodeMap:  make(map[uint32]*Node),
        replicas: replicas,
    }
}

// 添加节点
func (lb *LoadBalancer) AddNode(node *Node) {
    lb.mu.Lock()
    defer lb.mu.Unlock()
    
    lb.nodes[node.ID] = node
    
    // 根据权重添加虚拟节点
    virtualNodes := lb.replicas * node.Weight
    for i := 0; i < virtualNodes; i++ {
        virtualKey := fmt.Sprintf("%s#%d", node.ID, i)
        hash := lb.hash(virtualKey)
        lb.ring = append(lb.ring, hash)
        lb.nodeMap[hash] = node
    }
    
    // 保持环有序
    sort.Slice(lb.ring, func(i, j int) bool {
        return lb.ring[i] < lb.ring[j]
    })
}

// 移除节点
func (lb *LoadBalancer) RemoveNode(nodeID string) {
    lb.mu.Lock()
    defer lb.mu.Unlock()
    
    node, exists := lb.nodes[nodeID]
    if !exists {
        return
    }
    
    delete(lb.nodes, nodeID)
    
    // 移除虚拟节点
    virtualNodes := lb.replicas * node.Weight
    for i := 0; i < virtualNodes; i++ {
        virtualKey := fmt.Sprintf("%s#%d", nodeID, i)
        hash := lb.hash(virtualKey)
        delete(lb.nodeMap, hash)
        
        // 从环中移除
        for j, ringHash := range lb.ring {
            if ringHash == hash {
                lb.ring = append(lb.ring[:j], lb.ring[j+1:]...)
                break
            }
        }
    }
}

// 选择节点
func (lb *LoadBalancer) SelectNode(key string) *Node {
    lb.mu.RLock()
    defer lb.mu.RUnlock()
    
    if len(lb.ring) == 0 {
        return nil
    }
    
    hash := lb.hash(key)
    
    // 二分查找
    idx := sort.Search(len(lb.ring), func(i int) bool {
        return lb.ring[i] >= hash
    })
    
    if idx == len(lb.ring) {
        idx = 0
    }
    
    node := lb.nodeMap[lb.ring[idx]]
    
    // 检查节点是否活跃
    if node.Active {
        return node
    }
    
    // 查找下一个活跃节点
    for i := 1; i < len(lb.ring); i++ {
        nextIdx := (idx + i) % len(lb.ring)
        nextNode := lb.nodeMap[lb.ring[nextIdx]]
        if nextNode.Active {
            return nextNode
        }
    }
    
    return nil
}

// 最少连接负载均衡
func (lb *LoadBalancer) SelectLeastConnNode() *Node {
    lb.mu.RLock()
    defer lb.mu.RUnlock()
    
    var selectedNode *Node
    minConnections := int64(^uint64(0) >> 1) // 最大int64值
    
    for _, node := range lb.nodes {
        if node.Active && node.ConnCount < minConnections {
            selectedNode = node
            minConnections = node.ConnCount
        }
    }
    
    return selectedNode
}

// 加权轮询负载均衡
type WeightedRoundRobin struct {
    nodes   []*WeightedNode
    current int
    mu      sync.Mutex
}

type WeightedNode struct {
    Node           *Node
    Weight         int
    CurrentWeight  int
    EffectiveWeight int
}

func (wrr *WeightedRoundRobin) SelectNode() *Node {
    wrr.mu.Lock()
    defer wrr.mu.Unlock()
    
    if len(wrr.nodes) == 0 {
        return nil
    }
    
    var selected *WeightedNode
    totalWeight := 0
    
    for _, node := range wrr.nodes {
        if !node.Node.Active {
            continue
        }
        
        node.CurrentWeight += node.EffectiveWeight
        totalWeight += node.EffectiveWeight
        
        if node.EffectiveWeight < node.Weight {
            node.EffectiveWeight++
        }
        
        if selected == nil || node.CurrentWeight > selected.CurrentWeight {
            selected = node
        }
    }
    
    if selected == nil {
        return nil
    }
    
    selected.CurrentWeight -= totalWeight
    return selected.Node
}

// 哈希函数
func (lb *LoadBalancer) hash(key string) uint32 {
    h := sha1.Sum([]byte(key))
    return uint32(h[0])<<24 | uint32(h[1])<<16 | uint32(h[2])<<8 | uint32(h[3])
}
```

---

## 5. 消息可靠性保证

### 5.1 消息确认机制

#### 消息确认实现
```go
package reliability

import (
    "context"
    "encoding/json"
    "fmt"
    "sync"
    "time"
    
    "github.com/go-redis/redis/v8"
)

// 消息确认管理器
type MessageAckManager struct {
    pendingMessages map[string]*PendingMessage
    mu              sync.RWMutex
    redis           *redis.Client
    retryInterval   time.Duration
    maxRetries      int
}

// 待确认消息
type PendingMessage struct {
    ID          string
    Message     *Message
    Timestamp   time.Time
    RetryCount  int
    MaxRetries  int
    Callback    func(*Message, error)
}

// 消息状态
type MessageStatus struct {
    ID        string    `json:"id"`
    Status    string    `json:"status"` // pending, delivered, failed
    Timestamp time.Time `json:"timestamp"`
    Error     string    `json:"error,omitempty"`
}

// 创建消息确认管理器
func NewMessageAckManager(redisClient *redis.Client) *MessageAckManager {
    manager := &MessageAckManager{
        pendingMessages: make(map[string]*PendingMessage),
        redis:           redisClient,
        retryInterval:   5 * time.Second,
        maxRetries:      3,
    }
    
    // 启动重试协程
    go manager.retryLoop()
    
    return manager
}

// 发送需要确认的消息
func (mam *MessageAckManager) SendWithAck(message *Message, timeout time.Duration, callback func(*Message, error)) {
    // 生成消息ID
    if message.ID == "" {
        message.ID = generateMessageID()
    }
    
    // 添加到待确认列表
    pendingMsg := &PendingMessage{
        ID:         message.ID,
        Message:    message,
        Timestamp:  time.Now(),
        RetryCount: 0,
        MaxRetries: mam.maxRetries,
        Callback:   callback,
    }
    
    mam.mu.Lock()
    mam.pendingMessages[message.ID] = pendingMsg
    mam.mu.Unlock()
    
    // 存储到Redis（持久化）
    mam.storePendingMessage(pendingMsg)
    
    // 发送消息
    mam.deliverMessage(message)
    
    // 设置超时
    time.AfterFunc(timeout, func() {
        mam.handleTimeout(message.ID)
    })
}

// 处理消息确认
func (mam *MessageAckManager) HandleAck(messageID string, success bool, errorMsg string) {
    mam.mu.Lock()
    pendingMsg, exists := mam.pendingMessages[messageID]
    if !exists {
        mam.mu.Unlock()
        return
    }
    
    delete(mam.pendingMessages, messageID)
    mam.mu.Unlock()
    
    // 从Redis中删除
    mam.redis.HDel(context.Background(), "pending_messages", messageID)
    
    // 更新消息状态
    status := &MessageStatus{
        ID:        messageID,
        Timestamp: time.Now(),
    }
    
    if success {
        status.Status = "delivered"
    } else {
        status.Status = "failed"
        status.Error = errorMsg
    }
    
    mam.updateMessageStatus(status)
    
    // 执行回调
    if pendingMsg.Callback != nil {
        var err error
        if !success {
            err = fmt.Errorf(errorMsg)
        }
        go pendingMsg.Callback(pendingMsg.Message, err)
    }
}

// 处理超时
func (mam *MessageAckManager) handleTimeout(messageID string) {
    mam.mu.Lock()
    pendingMsg, exists := mam.pendingMessages[messageID]
    if !exists {
        mam.mu.Unlock()
        return
    }
    
    pendingMsg.RetryCount++
    
    if pendingMsg.RetryCount >= pendingMsg.MaxRetries {
        // 达到最大重试次数，标记为失败
        delete(mam.pendingMessages, messageID)
        mam.mu.Unlock()
        
        mam.redis.HDel(context.Background(), "pending_messages", messageID)
        
        status := &MessageStatus{
            ID:        messageID,
            Status:    "failed",
            Timestamp: time.Now(),
            Error:     "max retries exceeded",
        }
        mam.updateMessageStatus(status)
        
        if pendingMsg.Callback != nil {
            go pendingMsg.Callback(pendingMsg.Message, fmt.Errorf("max retries exceeded"))
        }
    } else {
        // 重试
        mam.mu.Unlock()
        mam.retryMessage(pendingMsg)
    }
}

// 重试消息
func (mam *MessageAckManager) retryMessage(pendingMsg *PendingMessage) {
    // 指数退避
    delay := time.Duration(pendingMsg.RetryCount) * mam.retryInterval
    time.AfterFunc(delay, func() {
        mam.deliverMessage(pendingMsg.Message)
        
        // 重新设置超时
        timeout := 30 * time.Second
        time.AfterFunc(timeout, func() {
            mam.handleTimeout(pendingMsg.ID)
        })
    })
}

// 重试循环（处理系统重启后的恢复）
func (mam *MessageAckManager) retryLoop() {
    ticker := time.NewTicker(mam.retryInterval)
    defer ticker.Stop()
    
    for range ticker.C {
        mam.recoverPendingMessages()
    }
}

// 恢复待确认消息
func (mam *MessageAckManager) recoverPendingMessages() {
    // 从Redis中获取所有待确认消息
    pendingData, err := mam.redis.HGetAll(context.Background(), "pending_messages").Result()
    if err != nil {
        return
    }
    
    for messageID, data := range pendingData {
        var pendingMsg PendingMessage
        if err := json.Unmarshal([]byte(data), &pendingMsg); err != nil {
            continue
        }
        
        // 检查是否已超时
        if time.Since(pendingMsg.Timestamp) > 5*time.Minute {
            // 超时太久，标记为失败
            mam.redis.HDel(context.Background(), "pending_messages", messageID)
            
            status := &MessageStatus{
                ID:        messageID,
                Status:    "failed",
                Timestamp: time.Now(),
                Error:     "timeout after recovery",
            }
            mam.updateMessageStatus(status)
            continue
        }
        
        // 重新加入待确认列表
        mam.mu.Lock()
        if _, exists := mam.pendingMessages[messageID]; !exists {
            mam.pendingMessages[messageID] = &pendingMsg
        }
        mam.mu.Unlock()
    }
}

// 存储待确认消息
func (mam *MessageAckManager) storePendingMessage(pendingMsg *PendingMessage) {
    data, _ := json.Marshal(pendingMsg)
    mam.redis.HSet(context.Background(), "pending_messages", pendingMsg.ID, data)
}

// 更新消息状态
func (mam *MessageAckManager) updateMessageStatus(status *MessageStatus) {
    data, _ := json.Marshal(status)
    mam.redis.HSet(context.Background(), "message_status", status.ID, data)
    mam.redis.Expire(context.Background(), "message_status", 24*time.Hour)
}

// 投递消息（实际发送逻辑）
func (mam *MessageAckManager) deliverMessage(message *Message) {
    // 这里实现实际的消息投递逻辑
    // 例如通过WebSocket发送、HTTP推送等
}
```

### 5.2 离线消息处理

#### 离线消息存储
```go
package offline

import (
    "context"
    "encoding/json"
    "fmt"
    "time"
    
    "github.com/go-redis/redis/v8"
    "go.mongodb.org/mongo-driver/mongo"
    "go.mongodb.org/mongo-driver/bson"
)

// 离线消息管理器
type OfflineMessageManager struct {
    redis   *redis.Client
    mongodb *mongo.Collection
    maxSize int // 每个用户最大离线消息数
}

// 离线消息
type OfflineMessage struct {
    ID        string                 `json:"id" bson:"_id"`
    UserID    int64                  `json:"user_id" bson:"user_id"`
    Message   *Message               `json:"message" bson:"message"`
    CreatedAt time.Time              `json:"created_at" bson:"created_at"`
    ExpireAt  time.Time              `json:"expire_at" bson:"expire_at"`
    Metadata  map[string]interface{} `json:"metadata" bson:"metadata"`
}

// 创建离线消息管理器
func NewOfflineMessageManager(redisClient *redis.Client, mongoCollection *mongo.Collection) *OfflineMessageManager {
    return &OfflineMessageManager{
        redis:   redisClient,
        mongodb: mongoCollection,
        maxSize: 1000, // 每个用户最多1000条离线消息
    }
}

// 存储离线消息
func (omm *OfflineMessageManager) StoreOfflineMessage(userID int64, message *Message) error {
    // 检查用户是否在线
    online, err := omm.isUserOnline(userID)
    if err != nil {
        return err
    }
    
    if online {
        return nil // 用户在线，不需要存储离线消息
    }
    
    // 创建离线消息
    offlineMsg := &OfflineMessage{
        ID:        generateMessageID(),
        UserID:    userID,
        Message:   message,
        CreatedAt: time.Now(),
        ExpireAt:  time.Now().Add(7 * 24 * time.Hour), // 7天过期
    }
    
    // 存储到Redis（快速访问）
    if err := omm.storeToRedis(offlineMsg); err != nil {
        return err
    }
    
    // 存储到MongoDB（持久化）
    if err := omm.storeToMongoDB(offlineMsg); err != nil {
        return err
    }
    
    // 检查并清理超出限制的消息
    go omm.cleanupExcessMessages(userID)
    
    return nil
}

// 获取离线消息
func (omm *OfflineMessageManager) GetOfflineMessages(userID int64, limit int) ([]*OfflineMessage, error) {
    // 首先从Redis获取
    messages, err := omm.getFromRedis(userID, limit)
    if err == nil && len(messages) > 0 {
        return messages, nil
    }
    
    // Redis中没有，从MongoDB获取
    return omm.getFromMongoDB(userID, limit)
}

// 删除离线消息
func (omm *OfflineMessageManager) DeleteOfflineMessages(userID int64, messageIDs []string) error {
    // 从Redis删除
    for _, messageID := range messageIDs {
        omm.redis.ZRem(context.Background(), fmt.Sprintf("offline:%d", userID), messageID)
        omm.redis.HDel(context.Background(), "offline_messages", messageID)
    }
    
    // 从MongoDB删除
    filter := bson.M{
        "user_id": userID,
        "_id":     bson.M{"$in": messageIDs},
    }
    
    _, err := omm.mongodb.DeleteMany(context.Background(), filter)
    return err
}

// 用户上线处理
func (omm *OfflineMessageManager) HandleUserOnline(userID int64) ([]*OfflineMessage, error) {
    // 获取所有离线消息
    messages, err := omm.GetOfflineMessages(userID, omm.maxSize)
    if err != nil {
        return nil, err
    }
    
    // 标记用户为在线状态
    omm.redis.Set(context.Background(), fmt.Sprintf("user_online:%d", userID), "1", time.Hour)
    
    return messages, nil
}

// 用户下线处理
func (omm *OfflineMessageManager) HandleUserOffline(userID int64) {
    // 删除在线状态
    omm.redis.Del(context.Background(), fmt.Sprintf("user_online:%d", userID))
}

// 检查用户是否在线
func (omm *OfflineMessageManager) isUserOnline(userID int64) (bool, error) {
    result, err := omm.redis.Get(context.Background(), fmt.Sprintf("user_online:%d", userID)).Result()
    if err == redis.Nil {
        return false, nil
    }
    if err != nil {
        return false, err
    }
    return result == "1", nil
}

// 存储到Redis
func (omm *OfflineMessageManager) storeToRedis(message *OfflineMessage) error {
    // 存储消息详情
    data, err := json.Marshal(message)
    if err != nil {
        return err
    }
    
    omm.redis.HSet(context.Background(), "offline_messages", message.ID, data)
    
    // 添加到用户的离线消息列表（有序集合，按时间排序）
    score := float64(message.CreatedAt.Unix())
    omm.redis.ZAdd(context.Background(), fmt.Sprintf("offline:%d", message.UserID), &redis.Z{
        Score:  score,
        Member: message.ID,
    })
    
    // 设置过期时间
    omm.redis.Expire(context.Background(), "offline_messages", 7*24*time.Hour)
    omm.redis.Expire(context.Background(), fmt.Sprintf("offline:%d", message.UserID), 7*24*time.Hour)
    
    return nil
}

// 存储到MongoDB
func (omm *OfflineMessageManager) storeToMongoDB(message *OfflineMessage) error {
    _, err := omm.mongodb.InsertOne(context.Background(), message)
    return err
}

// 从Redis获取
func (omm *OfflineMessageManager) getFromRedis(userID int64, limit int) ([]*OfflineMessage, error) {
    // 获取消息ID列表
    messageIDs, err := omm.redis.ZRevRange(context.Background(), fmt.Sprintf("offline:%d", userID), 0, int64(limit-1)).Result()
    if err != nil {
        return nil, err
    }
    
    if len(messageIDs) == 0 {
        return nil, nil
    }
    
    // 批量获取消息详情
    messageData, err := omm.redis.HMGet(context.Background(), "offline_messages", messageIDs...).Result()
    if err != nil {
        return nil, err
    }
    
    var messages []*OfflineMessage
    for _, data := range messageData {
        if data == nil {
            continue
        }
        
        var message OfflineMessage
        if err := json.Unmarshal([]byte(data.(string)), &message); err != nil {
            continue
        }
        
        messages = append(messages, &message)
    }
    
    return messages, nil
}

// 从MongoDB获取
func (omm *OfflineMessageManager) getFromMongoDB(userID int64, limit int) ([]*OfflineMessage, error) {
    filter := bson.M{
        "user_id": userID,
        "expire_at": bson.M{"$gt": time.Now()},
    }
    
    opts := options.Find().
        SetSort(bson.D{{"created_at", -1}}).
        SetLimit(int64(limit))
    
    cursor, err := omm.mongodb.Find(context.Background(), filter, opts)
    if err != nil {
        return nil, err
    }
    defer cursor.Close(context.Background())
    
    var messages []*OfflineMessage
    for cursor.Next(context.Background()) {
        var message OfflineMessage
        if err := cursor.Decode(&message); err != nil {
            continue
        }
        messages = append(messages, &message)
    }
    
    return messages, nil
}

// 清理超出限制的消息
func (omm *OfflineMessageManager) cleanupExcessMessages(userID int64) {
    // 获取消息总数
    count, err := omm.redis.ZCard(context.Background(), fmt.Sprintf("offline:%d", userID)).Result()
    if err != nil || count <= int64(omm.maxSize) {
        return
    }
    
    // 删除最旧的消息
    excessCount := count - int64(omm.maxSize)
    
    // 获取要删除的消息ID
    oldMessageIDs, err := omm.redis.ZRange(context.Background(), fmt.Sprintf("offline:%d", userID), 0, excessCount-1).Result()
    if err != nil {
        return
    }
    
    // 删除消息
    omm.DeleteOfflineMessages(userID, oldMessageIDs)
}

// 清理过期消息
func (omm *OfflineMessageManager) CleanupExpiredMessages() {
    // 从MongoDB删除过期消息
    filter := bson.M{
        "expire_at": bson.M{"$lt": time.Now()},
    }
    
    omm.mongodb.DeleteMany(context.Background(), filter)
    
    // 清理Redis中的过期消息引用
    // 这里可以通过定期扫描实现
}
```

---

## 6. 监控与运维

### 6.1 性能监控

#### 监控指标收集
```go
package monitoring

import (
    "context"
    "sync"
    "sync/atomic"
    "time"
    
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
)

// 监控指标
type Metrics struct {
    // 连接指标
    ActiveConnections    prometheus.Gauge
    TotalConnections     prometheus.Counter
    ConnectionDuration   prometheus.Histogram
    
    // 消息指标
    MessagesSent         prometheus.Counter
    MessagesReceived     prometheus.Counter
    MessageLatency       prometheus.Histogram
    MessageErrors        prometheus.Counter
    
    // 系统指标
    CPUUsage            prometheus.Gauge
    MemoryUsage         prometheus.Gauge
    GoroutineCount      prometheus.Gauge
    
    // 业务指标
    OnlineUsers         prometheus.Gauge
    RoomCount           prometheus.Gauge
    OfflineMessages     prometheus.Gauge
}

// 监控管理器
type MonitorManager struct {
    metrics     *Metrics
    nodeID      string
    startTime   time.Time
    
    // 实时统计
    connCount   int64
    msgCount    int64
    errorCount  int64
    
    mu sync.RWMutex
}

// 创建监控管理器
func NewMonitorManager(nodeID string) *MonitorManager {
    metrics := &Metrics{
        ActiveConnections: promauto.NewGauge(prometheus.GaugeOpts{
            Name: "websocket_active_connections",
            Help: "Number of active WebSocket connections",
            ConstLabels: prometheus.Labels{"node": nodeID},
        }),
        
        TotalConnections: promauto.NewCounter(prometheus.CounterOpts{
            Name: "websocket_total_connections",
            Help: "Total number of WebSocket connections",
            ConstLabels: prometheus.Labels{"node": nodeID},
        }),
        
        ConnectionDuration: promauto.NewHistogram(prometheus.HistogramOpts{
            Name: "websocket_connection_duration_seconds",
            Help: "Duration of WebSocket connections",
            Buckets: []float64{1, 5, 10, 30, 60, 300, 600, 1800, 3600},
            ConstLabels: prometheus.Labels{"node": nodeID},
        }),
        
        MessagesSent: promauto.NewCounter(prometheus.CounterOpts{
            Name: "websocket_messages_sent_total",
            Help: "Total number of messages sent",
            ConstLabels: prometheus.Labels{"node": nodeID},
        }),
        
        MessagesReceived: promauto.NewCounter(prometheus.CounterOpts{
            Name: "websocket_messages_received_total",
            Help: "Total number of messages received",
            ConstLabels: prometheus.Labels{"node": nodeID},
        }),
        
        MessageLatency: promauto.NewHistogram(prometheus.HistogramOpts{
            Name: "websocket_message_latency_seconds",
            Help: "Message processing latency",
            Buckets: []float64{0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 5},
            ConstLabels: prometheus.Labels{"node": nodeID},
        }),
        
        MessageErrors: promauto.NewCounter(prometheus.CounterOpts{
            Name: "websocket_message_errors_total",
            Help: "Total number of message errors",
            ConstLabels: prometheus.Labels{"node": nodeID},
        }),
        
        CPUUsage: promauto.NewGauge(prometheus.GaugeOpts{
            Name: "system_cpu_usage_percent",
            Help: "CPU usage percentage",
            ConstLabels: prometheus.Labels{"node": nodeID},
        }),
        
        MemoryUsage: promauto.NewGauge(prometheus.GaugeOpts{
            Name: "system_memory_usage_bytes",
            Help: "Memory usage in bytes",
            ConstLabels: prometheus.Labels{"node": nodeID},
        }),
        
        GoroutineCount: promauto.NewGauge(prometheus.GaugeOpts{
            Name: "system_goroutine_count",
            Help: "Number of goroutines",
            ConstLabels: prometheus.Labels{"node": nodeID},
        }),
        
        OnlineUsers: promauto.NewGauge(prometheus.GaugeOpts{
            Name: "business_online_users",
            Help: "Number of online users",
            ConstLabels: prometheus.Labels{"node": nodeID},
        }),
        
        RoomCount: promauto.NewGauge(prometheus.GaugeOpts{
            Name: "business_room_count",
            Help: "Number of active rooms",
            ConstLabels: prometheus.Labels{"node": nodeID},
        }),
        
        OfflineMessages: promauto.NewGauge(prometheus.GaugeOpts{
            Name: "business_offline_messages",
            Help: "Number of offline messages",
            ConstLabels: prometheus.Labels{"node": nodeID},
        }),
    }
    
    manager := &MonitorManager{
        metrics:   metrics,
        nodeID:    nodeID,
        startTime: time.Now(),
    }
    
    // 启动系统指标收集
    go manager.collectSystemMetrics()
    
    return manager
}

// 记录连接建立
func (mm *MonitorManager) RecordConnectionEstablished() {
    atomic.AddInt64(&mm.connCount, 1)
    mm.metrics.ActiveConnections.Inc()
    mm.metrics.TotalConnections.Inc()
}

// 记录连接关闭
func (mm *MonitorManager) RecordConnectionClosed(duration time.Duration) {
    atomic.AddInt64(&mm.connCount, -1)
    mm.metrics.ActiveConnections.Dec()
    mm.metrics.ConnectionDuration.Observe(duration.Seconds())
}

// 记录消息发送
func (mm *MonitorManager) RecordMessageSent(latency time.Duration) {
    atomic.AddInt64(&mm.msgCount, 1)
    mm.metrics.MessagesSent.Inc()
    mm.metrics.MessageLatency.Observe(latency.Seconds())
}

// 记录消息接收
func (mm *MonitorManager) RecordMessageReceived() {
    mm.metrics.MessagesReceived.Inc()
}

// 记录消息错误
func (mm *MonitorManager) RecordMessageError() {
    atomic.AddInt64(&mm.errorCount, 1)
    mm.metrics.MessageErrors.Inc()
}

// 更新业务指标
func (mm *MonitorManager) UpdateBusinessMetrics(onlineUsers, roomCount, offlineMessages int) {
    mm.metrics.OnlineUsers.Set(float64(onlineUsers))
    mm.metrics.RoomCount.Set(float64(roomCount))
    mm.metrics.OfflineMessages.Set(float64(offlineMessages))
}

// 收集系统指标
func (mm *MonitorManager) collectSystemMetrics() {
    ticker := time.NewTicker(10 * time.Second)
    defer ticker.Stop()
    
    for range ticker.C {
        // CPU使用率
        cpuUsage := mm.getCPUUsage()
        mm.metrics.CPUUsage.Set(cpuUsage)
        
        // 内存使用
        memUsage := mm.getMemoryUsage()
        mm.metrics.MemoryUsage.Set(float64(memUsage))
        
        // Goroutine数量
        goroutineCount := runtime.NumGoroutine()
        mm.metrics.GoroutineCount.Set(float64(goroutineCount))
    }
}

// 获取统计信息
func (mm *MonitorManager) GetStats() map[string]interface{} {
    return map[string]interface{}{
        "node_id":         mm.nodeID,
        "uptime":          time.Since(mm.startTime).Seconds(),
        "connections":     atomic.LoadInt64(&mm.connCount),
        "messages":        atomic.LoadInt64(&mm.msgCount),
        "errors":          atomic.LoadInt64(&mm.errorCount),
        "goroutines":      runtime.NumGoroutine(),
        "memory_usage":    mm.getMemoryUsage(),
        "cpu_usage":       mm.getCPUUsage(),
    }
}

// 获取CPU使用率
func (mm *MonitorManager) getCPUUsage() float64 {
    // 实现CPU使用率获取逻辑
    // 这里简化处理，实际应该使用系统调用
    return 0.0
}

// 获取内存使用量
func (mm *MonitorManager) getMemoryUsage() uint64 {
    var m runtime.MemStats
    runtime.ReadMemStats(&m)
    return m.Alloc
}
```

### 6.2 告警系统

#### 告警规则引擎
```go
package alerting

import (
    "context"
    "encoding/json"
    "fmt"
    "log"
    "sync"
    "time"
)

// 告警规则
type AlertRule struct {
    ID          string                 `json:"id"`
    Name        string                 `json:"name"`
    Metric      string                 `json:"metric"`
    Operator    string                 `json:"operator"` // >, <, >=, <=, ==, !=
    Threshold   float64                `json:"threshold"`
    Duration    time.Duration          `json:"duration"`
    Severity    string                 `json:"severity"` // critical, warning, info
    Enabled     bool                   `json:"enabled"`
    Actions     []AlertAction          `json:"actions"`
    Metadata    map[string]interface{} `json:"metadata"`
}

// 告警动作
type AlertAction struct {
    Type   string                 `json:"type"`   // email, sms, webhook, dingtalk
    Target string                 `json:"target"` // 接收者
    Config map[string]interface{} `json:"config"`
}

// 告警事件
type AlertEvent struct {
    ID        string                 `json:"id"`
    RuleID    string                 `json:"rule_id"`
    RuleName  string                 `json:"rule_name"`
    Metric    string                 `json:"metric"`
    Value     float64                `json:"value"`
    Threshold float64                `json:"threshold"`
    Severity  string                 `json:"severity"`
    Status    string                 `json:"status"` // firing, resolved
    StartTime time.Time              `json:"start_time"`
    EndTime   *time.Time             `json:"end_time,omitempty"`
    NodeID    string                 `json:"node_id"`
    Metadata  map[string]interface{} `json:"metadata"`
}

// 告警管理器
type AlertManager struct {
    rules       map[string]*AlertRule
    events      map[string]*AlertEvent
    mu          sync.RWMutex
    metricsChan chan MetricData
    actionChan  chan *AlertEvent
    notifiers   map[string]Notifier
}

// 指标数据
type MetricData struct {
    Name      string
    Value     float64
    Timestamp time.Time
    Labels    map[string]string
}

// 通知器接口
type Notifier interface {
    Send(event *AlertEvent, action *AlertAction) error
}

// 创建告警管理器
func NewAlertManager() *AlertManager {
    am := &AlertManager{
        rules:       make(map[string]*AlertRule),
        events:      make(map[string]*AlertEvent),
        metricsChan: make(chan MetricData, 1000),
        actionChan:  make(chan *AlertEvent, 100),
        notifiers:   make(map[string]Notifier),
    }
    
    // 注册通知器
    am.notifiers["email"] = &EmailNotifier{}
    am.notifiers["webhook"] = &WebhookNotifier{}
    am.notifiers["dingtalk"] = &DingTalkNotifier{}
    
    // 启动处理协程
    go am.processMetrics()
    go am.processActions()
    
    return am
}

// 添加告警规则
func (am *AlertManager) AddRule(rule *AlertRule) {
    am.mu.Lock()
    defer am.mu.Unlock()
    am.rules[rule.ID] = rule
}

// 删除告警规则
func (am *AlertManager) RemoveRule(ruleID string) {
    am.mu.Lock()
    defer am.mu.Unlock()
    delete(am.rules, ruleID)
}

// 接收指标数据
func (am *AlertManager) ReceiveMetric(metric MetricData) {
    select {
    case am.metricsChan <- metric:
    default:
        log.Printf("Metrics channel full, dropping metric: %s", metric.Name)
    }
}

// 处理指标
func (am *AlertManager) processMetrics() {
    for metric := range am.metricsChan {
        am.evaluateRules(metric)
    }
}

// 评估规则
func (am *AlertManager) evaluateRules(metric MetricData) {
    am.mu.RLock()
    defer am.mu.RUnlock()
    
    for _, rule := range am.rules {
        if !rule.Enabled || rule.Metric != metric.Name {
            continue
        }
        
        if am.evaluateCondition(rule, metric.Value) {
            am.handleAlert(rule, metric)
        } else {
            am.handleResolve(rule, metric)
        }
    }
}

// 评估条件
func (am *AlertManager) evaluateCondition(rule *AlertRule, value float64) bool {
    switch rule.Operator {
    case ">":
        return value > rule.Threshold
    case "<":
        return value < rule.Threshold
    case ">=":
        return value >= rule.Threshold
    case "<=":
        return value <= rule.Threshold
    case "==":
        return value == rule.Threshold
    case "!=":
        return value != rule.Threshold
    default:
        return false
    }
}

// 处理告警
func (am *AlertManager) handleAlert(rule *AlertRule, metric MetricData) {
    eventID := fmt.Sprintf("%s_%s", rule.ID, metric.Labels["node"])
    
    am.mu.Lock()
    event, exists := am.events[eventID]
    if !exists {
        // 新告警
        event = &AlertEvent{
            ID:        eventID,
            RuleID:    rule.ID,
            RuleName:  rule.Name,
            Metric:    rule.Metric,
            Value:     metric.Value,
            Threshold: rule.Threshold,
            Severity:  rule.Severity,
            Status:    "firing",
            StartTime: metric.Timestamp,
            NodeID:    metric.Labels["node"],
            Metadata:  rule.Metadata,
        }
        am.events[eventID] = event
        am.mu.Unlock()
        
        // 发送告警
        select {
        case am.actionChan <- event:
        default:
            log.Printf("Action channel full, dropping alert: %s", eventID)
        }
    } else {
        // 更新现有告警
        event.Value = metric.Value
        am.mu.Unlock()
    }
}

// 处理恢复
func (am *AlertManager) handleResolve(rule *AlertRule, metric MetricData) {
    eventID := fmt.Sprintf("%s_%s", rule.ID, metric.Labels["node"])
    
    am.mu.Lock()
    event, exists := am.events[eventID]
    if exists && event.Status == "firing" {
        event.Status = "resolved"
        endTime := metric.Timestamp
        event.EndTime = &endTime
        am.mu.Unlock()
        
        // 发送恢复通知
        select {
        case am.actionChan <- event:
        default:
            log.Printf("Action channel full, dropping resolve: %s", eventID)
        }
        
        // 清理已恢复的事件
        time.AfterFunc(time.Hour, func() {
            am.mu.Lock()
            delete(am.events, eventID)
            am.mu.Unlock()
        })
    } else {
        am.mu.Unlock()
    }
}

// 处理告警动作
func (am *AlertManager) processActions() {
    for event := range am.actionChan {
        am.mu.RLock()
        rule := am.rules[event.RuleID]
        am.mu.RUnlock()
        
        if rule == nil {
            continue
        }
        
        for _, action := range rule.Actions {
            if notifier, exists := am.notifiers[action.Type]; exists {
                go func(n Notifier, e *AlertEvent, a AlertAction) {
                    if err := n.Send(e, &a); err != nil {
                        log.Printf("Failed to send alert notification: %v", err)
                    }
                }(notifier, event, action)
            }
        }
    }
}
```

#### 通知器实现
```go
// 邮件通知器
type EmailNotifier struct{}

func (en *EmailNotifier) Send(event *AlertEvent, action *AlertAction) error {
    subject := fmt.Sprintf("[%s] %s", event.Severity, event.RuleName)
    body := fmt.Sprintf(`
告警详情:
- 规则: %s
- 指标: %s
- 当前值: %.2f
- 阈值: %.2f
- 状态: %s
- 节点: %s
- 时间: %s
`,
        event.RuleName,
        event.Metric,
        event.Value,
        event.Threshold,
        event.Status,
        event.NodeID,
        event.StartTime.Format("2006-01-02 15:04:05"),
    )
    
    // 实现邮件发送逻辑
    log.Printf("Sending email to %s: %s", action.Target, subject)
    return nil
}

// 钉钉通知器
type DingTalkNotifier struct{}

func (dn *DingTalkNotifier) Send(event *AlertEvent, action *AlertAction) error {
    webhook := action.Config["webhook"].(string)
    
    message := map[string]interface{}{
        "msgtype": "markdown",
        "markdown": map[string]interface{}{
            "title": fmt.Sprintf("[%s] %s", event.Severity, event.RuleName),
            "text": fmt.Sprintf(`
### 告警通知

- **规则**: %s
- **指标**: %s
- **当前值**: %.2f
- **阈值**: %.2f
- **状态**: %s
- **节点**: %s
- **时间**: %s
`,
                event.RuleName,
                event.Metric,
                event.Value,
                event.Threshold,
                event.Status,
                event.NodeID,
                event.StartTime.Format("2006-01-02 15:04:05"),
            ),
        },
    }
    
    // 实现钉钉webhook发送逻辑
    data, _ := json.Marshal(message)
    log.Printf("Sending DingTalk message to %s: %s", webhook, string(data))
    return nil
}

// Webhook通知器
type WebhookNotifier struct{}

func (wn *WebhookNotifier) Send(event *AlertEvent, action *AlertAction) error {
    url := action.Target
    
    payload := map[string]interface{}{
        "event": event,
        "timestamp": time.Now().Unix(),
    }
    
    data, _ := json.Marshal(payload)
    log.Printf("Sending webhook to %s: %s", url, string(data))
    return nil
}
```

---

## 7. 部署与配置

### 7.1 Docker容器化

#### Dockerfile
```dockerfile
# WebSocket网关Dockerfile
FROM golang:1.21-alpine AS builder

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o websocket-gateway ./cmd/gateway

FROM alpine:latest
RUN apk --no-cache add ca-certificates tzdata
WORKDIR /root/

COPY --from=builder /app/websocket-gateway .
COPY --from=builder /app/configs ./configs

EXPOSE 8080
CMD ["./websocket-gateway"]
```

#### Docker Compose配置
```yaml
# docker-compose.yml
version: '3.8'

services:
  # Nginx负载均衡
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
    depends_on:
      - gateway-1
      - gateway-2
      - gateway-3
    networks:
      - websocket-net

  # WebSocket网关集群
  gateway-1:
    build: .
    environment:
      - NODE_ID=gateway-1
      - REDIS_URL=redis://redis:6379
      - MONGODB_URL=mongodb://mongodb:27017
      - KAFKA_BROKERS=kafka:9092
    depends_on:
      - redis
      - mongodb
      - kafka
    networks:
      - websocket-net
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '0.5'

  gateway-2:
    build: .
    environment:
      - NODE_ID=gateway-2
      - REDIS_URL=redis://redis:6379
      - MONGODB_URL=mongodb://mongodb:27017
      - KAFKA_BROKERS=kafka:9092
    depends_on:
      - redis
      - mongodb
      - kafka
    networks:
      - websocket-net
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '0.5'

  gateway-3:
    build: .
    environment:
      - NODE_ID=gateway-3
      - REDIS_URL=redis://redis:6379
      - MONGODB_URL=mongodb://mongodb:27017
      - KAFKA_BROKERS=kafka:9092
    depends_on:
      - redis
      - mongodb
      - kafka
    networks:
      - websocket-net
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '0.5'

  # Redis集群
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis-data:/data
    networks:
      - websocket-net

  # MongoDB
  mongodb:
    image: mongo:6
    environment:
      - MONGO_INITDB_ROOT_USERNAME=admin
      - MONGO_INITDB_ROOT_PASSWORD=password
    volumes:
      - mongodb-data:/data/db
    networks:
      - websocket-net

  # Kafka
  zookeeper:
    image: confluentinc/cp-zookeeper:latest
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
      ZOOKEEPER_TICK_TIME: 2000
    networks:
      - websocket-net

  kafka:
    image: confluentinc/cp-kafka:latest
    depends_on:
      - zookeeper
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
    networks:
      - websocket-net

  # 监控组件
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus-data:/prometheus
    networks:
      - websocket-net

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana-data:/var/lib/grafana
      - ./grafana/dashboards:/etc/grafana/provisioning/dashboards
      - ./grafana/datasources:/etc/grafana/provisioning/datasources
    networks:
      - websocket-net

volumes:
  redis-data:
  mongodb-data:
  prometheus-data:
  grafana-data:

networks:
  websocket-net:
    driver: bridge
```

### 7.2 Kubernetes部署

#### 部署配置
```yaml
# k8s-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: websocket-gateway
  labels:
    app: websocket-gateway
spec:
  replicas: 3
  selector:
    matchLabels:
      app: websocket-gateway
  template:
    metadata:
      labels:
        app: websocket-gateway
    spec:
      containers:
      - name: gateway
        image: websocket-gateway:latest
        ports:
        - containerPort: 8080
        env:
        - name: NODE_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: REDIS_URL
          value: "redis://redis-service:6379"
        - name: MONGODB_URL
          value: "mongodb://mongodb-service:27017"
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: websocket-gateway-service
spec:
  selector:
    app: websocket-gateway
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8080
  type: LoadBalancer
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: websocket-gateway-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: websocket-gateway
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

---

## 8. 性能测试

### 8.1 压力测试工具

#### WebSocket压测工具
```go
package main

import (
    "context"
    "flag"
    "fmt"
    "log"
    "sync"
    "sync/atomic"
    "time"
    
    "github.com/gorilla/websocket"
)

// 测试配置
type TestConfig struct {
    URL             string
    Connections     int
    Duration        time.Duration
    MessageInterval time.Duration
    MessageSize     int
}

// 测试统计
type TestStats struct {
    ConnectedCount    int64
    DisconnectedCount int64
    MessagesSent      int64
    MessagesReceived  int64
    ErrorCount        int64
    TotalLatency      int64
    MinLatency        int64
    MaxLatency        int64
}

// 压力测试器
type LoadTester struct {
    config *TestConfig
    stats  *TestStats
    ctx    context.Context
    cancel context.CancelFunc
}

// 创建压力测试器
func NewLoadTester(config *TestConfig) *LoadTester {
    ctx, cancel := context.WithTimeout(context.Background(), config.Duration)
    
    return &LoadTester{
        config: config,
        stats:  &TestStats{MinLatency: int64(^uint64(0) >> 1)},
        ctx:    ctx,
        cancel: cancel,
    }
}

// 运行测试
func (lt *LoadTester) Run() {
    var wg sync.WaitGroup
    
    // 启动统计协程
    go lt.printStats()
    
    // 创建连接
    for i := 0; i < lt.config.Connections; i++ {
        wg.Add(1)
        go func(id int) {
            defer wg.Done()
            lt.runConnection(id)
        }(i)
        
        // 控制连接建立速度
        time.Sleep(10 * time.Millisecond)
    }
    
    wg.Wait()
    lt.printFinalStats()
}

// 运行单个连接
func (lt *LoadTester) runConnection(id int) {
    conn, _, err := websocket.DefaultDialer.Dial(lt.config.URL, nil)
    if err != nil {
        atomic.AddInt64(&lt.stats.ErrorCount, 1)
        return
    }
    defer conn.Close()
    
    atomic.AddInt64(&lt.stats.ConnectedCount, 1)
    defer atomic.AddInt64(&lt.stats.DisconnectedCount, 1)
    
    // 启动读协程
    go lt.readMessages(conn)
    
    // 发送消息
    ticker := time.NewTicker(lt.config.MessageInterval)
    defer ticker.Stop()
    
    message := make([]byte, lt.config.MessageSize)
    for i := range message {
        message[i] = byte('A' + (i % 26))
    }
    
    for {
        select {
        case <-lt.ctx.Done():
            return
        case <-ticker.C:
            start := time.Now()
            
            if err := conn.WriteMessage(websocket.TextMessage, message); err != nil {
                atomic.AddInt64(&lt.stats.ErrorCount, 1)
                return
            }
            
            latency := time.Since(start).Nanoseconds()
            atomic.AddInt64(&lt.stats.MessagesSent, 1)
            atomic.AddInt64(&lt.stats.TotalLatency, latency)
            
            // 更新最小最大延迟
            for {
                min := atomic.LoadInt64(&lt.stats.MinLatency)
                if latency >= min || atomic.CompareAndSwapInt64(&lt.stats.MinLatency, min, latency) {
                    break
                }
            }
            
            for {
                max := atomic.LoadInt64(&lt.stats.MaxLatency)
                if latency <= max || atomic.CompareAndSwapInt64(&lt.stats.MaxLatency, max, latency) {
                    break
                }
            }
        }
    }
}

// 读取消息
func (lt *LoadTester) readMessages(conn *websocket.Conn) {
    for {
        select {
        case <-lt.ctx.Done():
            return
        default:
            _, _, err := conn.ReadMessage()
            if err != nil {
                atomic.AddInt64(&lt.stats.ErrorCount, 1)
                return
            }
            atomic.AddInt64(&lt.stats.MessagesReceived, 1)
        }
    }
}

// 打印统计信息
func (lt *LoadTester) printStats() {
    ticker := time.NewTicker(5 * time.Second)
    defer ticker.Stop()
    
    for {
        select {
        case <-lt.ctx.Done():
            return
        case <-ticker.C:
            connected := atomic.LoadInt64(&lt.stats.ConnectedCount)
            disconnected := atomic.LoadInt64(&lt.stats.DisconnectedCount)
            sent := atomic.LoadInt64(&lt.stats.MessagesSent)
            received := atomic.LoadInt64(&lt.stats.MessagesReceived)
            errors := atomic.LoadInt64(&lt.stats.ErrorCount)
            
            fmt.Printf("[%s] 连接: %d, 断开: %d, 发送: %d, 接收: %d, 错误: %d\n",
                time.Now().Format("15:04:05"),
                connected, disconnected, sent, received, errors)
        }
    }
}

// 打印最终统计
func (lt *LoadTester) printFinalStats() {
    connected := atomic.LoadInt64(&lt.stats.ConnectedCount)
    sent := atomic.LoadInt64(&lt.stats.MessagesSent)
    received := atomic.LoadInt64(&lt.stats.MessagesReceived)
    errors := atomic.LoadInt64(&lt.stats.ErrorCount)
    totalLatency := atomic.LoadInt64(&lt.stats.TotalLatency)
    minLatency := atomic.LoadInt64(&lt.stats.MinLatency)
    maxLatency := atomic.LoadInt64(&lt.stats.MaxLatency)
    
    avgLatency := float64(0)
    if sent > 0 {
        avgLatency = float64(totalLatency) / float64(sent) / 1e6 // 转换为毫秒
    }
    
    fmt.Printf("\n=== 测试结果 ===\n")
    fmt.Printf("总连接数: %d\n", connected)
    fmt.Printf("发送消息: %d\n", sent)
    fmt.Printf("接收消息: %d\n", received)
    fmt.Printf("错误数量: %d\n", errors)
    fmt.Printf("平均延迟: %.2f ms\n", avgLatency)
    fmt.Printf("最小延迟: %.2f ms\n", float64(minLatency)/1e6)
    fmt.Printf("最大延迟: %.2f ms\n", float64(maxLatency)/1e6)
    fmt.Printf("消息吞吐: %.2f msg/s\n", float64(sent)/lt.config.Duration.Seconds())
}

func main() {
    var (
        url         = flag.String("url", "ws://localhost:8080/ws", "WebSocket URL")
        connections = flag.Int("connections", 1000, "并发连接数")
        duration    = flag.Duration("duration", 60*time.Second, "测试持续时间")
        interval    = flag.Duration("interval", time.Second, "消息发送间隔")
        size        = flag.Int("size", 1024, "消息大小(字节)")
    )
    flag.Parse()
    
    config := &TestConfig{
        URL:             *url,
        Connections:     *connections,
        Duration:        *duration,
        MessageInterval: *interval,
        MessageSize:     *size,
    }
    
    fmt.Printf("开始压力测试...\n")
    fmt.Printf("URL: %s\n", config.URL)
    fmt.Printf("连接数: %d\n", config.Connections)
    fmt.Printf("持续时间: %v\n", config.Duration)
    fmt.Printf("消息间隔: %v\n", config.MessageInterval)
    fmt.Printf("消息大小: %d bytes\n", config.MessageSize)
    fmt.Printf("\n")
    
    tester := NewLoadTester(config)
    tester.Run()
}
```

---

## 9. 总结

### 9.1 架构优势

1. **高性能**
   - 支持百万级并发连接
   - 消息延迟 < 100ms
   - 吞吐量 > 100万条/秒

2. **高可用**
   - 多节点部署，无单点故障
   - 自动故障检测和恢复
   - 99.99% 可用性保证

3. **可扩展**
   - 水平扩展支持
   - 动态负载均衡
   - 弹性伸缩

4. **可靠性**
   - 消息确认机制
   - 离线消息存储
   - 数据持久化

### 9.2 关键技术

1. **WebSocket长连接管理**
   - 连接池优化
   - 心跳检测
   - 优雅断线重连

2. **消息路由**
   - 一致性哈希
   - 跨节点通信
   - 智能负载均衡

3. **可靠性保证**
   - 消息确认和重试
   - 离线消息处理
   - 数据一致性

4. **监控运维**
   - 全方位监控指标
   - 智能告警系统
   - 自动化运维

### 9.3 性能指标

- **并发连接**: 100万+
- **消息吞吐**: 100万条/秒
- **消息延迟**: P99 < 100ms
- **可用性**: 99.99%
- **扩展性**: 支持1000+节点
- **数据丢失率**: < 0.01%

### 9.4 适用场景

1. **即时通讯**: 聊天应用、社交平台
2. **实时推送**: 消息通知、状态更新
3. **直播互动**: 弹幕、礼物、连麦
4. **在线游戏**: 实时对战、状态同步
5. **协同办公**: 文档协作、视频会议
6. **IoT物联网**: 设备状态、数据采集

通过本架构设计，可以构建一个高性能、高可用、可扩展的实时通信系统，满足大规模用户的实时消息推送需求。