### Redis数据类型深度剖析与企业级应用

#### 1. String（字符串）- 高性能计数与缓存

##### 1.1 底层实现原理
**SDS结构优势**：
- **动态扩容**：预分配策略减少内存重分配次数
- **二进制安全**：支持存储图片、序列化对象等二进制数据
- **O(1)长度获取**：SDS头部记录长度，避免遍历计算

**编码优化策略**：
```go
// Redis String编码选择逻辑模拟
type StringEncoding int

const (
    INT_ENCODING    StringEncoding = iota  // 整数编码
    EMBSTR_ENCODING                        // 嵌入式字符串（≤44字节）
    RAW_ENCODING                           // 原始字符串（>44字节）
)

func selectStringEncoding(value string) StringEncoding {
    // 尝试解析为整数
    if isInteger(value) {
        return INT_ENCODING
    }
    
    // 短字符串使用embstr，减少内存碎片
    if len(value) <= 44 {
        return EMBSTR_ENCODING
    }
    
    return RAW_ENCODING
}

// 高性能计数器实现
type RedisCounter struct {
    client *redis.Client
    key    string
}

func (c *RedisCounter) Increment(delta int64) (int64, error) {
    return c.client.IncrBy(context.Background(), c.key, delta).Result()
}

func (c *RedisCounter) GetAndReset() (int64, error) {
    pipe := c.client.Pipeline()
    getCmd := pipe.Get(context.Background(), c.key)
    pipe.Del(context.Background(), c.key)
    
    _, err := pipe.Exec(context.Background())
    if err != nil {
        return 0, err
    }
    
    return getCmd.Int64()
}
```

##### 1.2 企业级应用场景

**分布式限流器**：
```go
type DistributedRateLimiter struct {
    client   *redis.Client
    keyPrefix string
    limit     int64
    window    time.Duration
}

func (rl *DistributedRateLimiter) IsAllowed(userID string) (bool, error) {
    key := fmt.Sprintf("%s:%s:%d", rl.keyPrefix, userID, time.Now().Unix()/int64(rl.window.Seconds()))
    
    // 使用Lua脚本保证原子性
    script := `
        local current = redis.call('GET', KEYS[1])
        if current == false then
            redis.call('SET', KEYS[1], 1)
            redis.call('EXPIRE', KEYS[1], ARGV[2])
            return 1
        end
        
        current = tonumber(current)
        if current < tonumber(ARGV[1]) then
            return redis.call('INCR', KEYS[1])
        else
            return 0
        end
    `
    
    result, err := rl.client.Eval(context.Background(), script, []string{key}, rl.limit, int(rl.window.Seconds())).Result()
    if err != nil {
        return false, err
    }
    
    return result.(int64) > 0, nil
}
```

**分布式ID生成器**：
```go
type DistributedIDGenerator struct {
    client    *redis.Client
    keyPrefix string
    step      int64
}

func (gen *DistributedIDGenerator) NextID(bizType string) (int64, error) {
    key := fmt.Sprintf("%s:%s", gen.keyPrefix, bizType)
    return gen.client.IncrBy(context.Background(), key, gen.step).Result()
}

// 批量获取ID，减少网络开销
func (gen *DistributedIDGenerator) NextIDBatch(bizType string, count int) ([]int64, error) {
    key := fmt.Sprintf("%s:%s", gen.keyPrefix, bizType)
    
    // 一次性获取count个ID
    maxID, err := gen.client.IncrBy(context.Background(), key, int64(count)*gen.step).Result()
    if err != nil {
        return nil, err
    }
    
    ids := make([]int64, count)
    for i := 0; i < count; i++ {
        ids[i] = maxID - int64(count-1-i)*gen.step
    }
    
    return ids, nil
}
```

#### 2. Hash（哈希表）- 对象存储与缓存优化

##### 2.1 内存优化策略
**ziplist vs dict性能对比**：
```go
// Hash编码切换监控
type HashEncodingMonitor struct {
    client *redis.Client
}

func (m *HashEncodingMonitor) AnalyzeHashEncoding(key string) (*HashInfo, error) {
    info := &HashInfo{Key: key}
    
    // 获取Hash大小
    size, err := m.client.HLen(context.Background(), key).Result()
    if err != nil {
        return nil, err
    }
    info.FieldCount = size
    
    // 获取内存使用
    memUsage, err := m.client.MemoryUsage(context.Background(), key).Result()
    if err != nil {
        return nil, err
    }
    info.MemoryUsage = memUsage
    
    // 估算编码类型
    if size <= 512 {  // hash-max-ziplist-entries默认值
        info.EstimatedEncoding = "ziplist"
    } else {
        info.EstimatedEncoding = "hashtable"
    }
    
    return info, nil
}

type HashInfo struct {
    Key               string
    FieldCount        int64
    MemoryUsage       int64
    EstimatedEncoding string
}
```

##### 2.2 企业级应用场景

**用户会话管理**：
```go
type UserSessionManager struct {
    client     *redis.Client
    keyPrefix  string
    expiration time.Duration
}

func (sm *UserSessionManager) CreateSession(userID int64, sessionData map[string]interface{}) (string, error) {
    sessionID := generateSessionID()
    key := fmt.Sprintf("%s:%s", sm.keyPrefix, sessionID)
    
    // 添加元数据
    sessionData["user_id"] = userID
    sessionData["created_at"] = time.Now().Unix()
    sessionData["last_access"] = time.Now().Unix()
    
    pipe := sm.client.Pipeline()
    for field, value := range sessionData {
        pipe.HSet(context.Background(), key, field, value)
    }
    pipe.Expire(context.Background(), key, sm.expiration)
    
    _, err := pipe.Exec(context.Background())
    return sessionID, err
}

func (sm *UserSessionManager) UpdateLastAccess(sessionID string) error {
    key := fmt.Sprintf("%s:%s", sm.keyPrefix, sessionID)
    
    pipe := sm.client.Pipeline()
    pipe.HSet(context.Background(), key, "last_access", time.Now().Unix())
    pipe.Expire(context.Background(), key, sm.expiration)  // 刷新过期时间
    
    _, err := pipe.Exec(context.Background())
    return err
}

// 批量获取用户会话信息
func (sm *UserSessionManager) GetUserSessions(userID int64) ([]map[string]string, error) {
    pattern := fmt.Sprintf("%s:*", sm.keyPrefix)
    
    var sessions []map[string]string
    iter := sm.client.Scan(context.Background(), 0, pattern, 100).Iterator()
    
    for iter.Next(context.Background()) {
        key := iter.Val()
        sessionData, err := sm.client.HGetAll(context.Background(), key).Result()
        if err != nil {
            continue
        }
        
        if sessionData["user_id"] == fmt.Sprintf("%d", userID) {
            sessions = append(sessions, sessionData)
        }
    }
    
    return sessions, iter.Err()
}
```

**商品库存管理**：
```go
type ProductInventoryManager struct {
    client    *redis.Client
    keyPrefix string
}

func (pim *ProductInventoryManager) UpdateInventory(productID int64, warehouseID int64, quantity int64) error {
    key := fmt.Sprintf("%s:%d", pim.keyPrefix, productID)
    field := fmt.Sprintf("warehouse_%d", warehouseID)
    
    // 使用Lua脚本保证原子性
    script := `
        local current = redis.call('HGET', KEYS[1], ARGV[1])
        if current == false then
            current = 0
        else
            current = tonumber(current)
        end
        
        local new_quantity = current + tonumber(ARGV[2])
        if new_quantity < 0 then
            return {"error", "insufficient_inventory"}
        end
        
        redis.call('HSET', KEYS[1], ARGV[1], new_quantity)
        return {"ok", new_quantity}
    `
    
    result, err := pim.client.Eval(context.Background(), script, []string{key}, field, quantity).Result()
    if err != nil {
        return err
    }
    
    if resultSlice, ok := result.([]interface{}); ok {
        if len(resultSlice) > 0 && resultSlice[0].(string) == "error" {
            return fmt.Errorf("inventory update failed: %s", resultSlice[1].(string))
        }
    }
    
    return nil
}

func (pim *ProductInventoryManager) GetTotalInventory(productID int64) (int64, error) {
    key := fmt.Sprintf("%s:%d", pim.keyPrefix, productID)
    
    inventoryMap, err := pim.client.HGetAll(context.Background(), key).Result()
    if err != nil {
        return 0, err
    }
    
    var total int64
    for _, quantityStr := range inventoryMap {
        quantity, err := strconv.ParseInt(quantityStr, 10, 64)
        if err == nil {
            total += quantity
        }
    }
    
    return total, nil
}
```

#### 3. List（列表）- 消息队列与时间线

##### 3.1 QuickList结构优化
**内存与性能平衡**：
```go
// QuickList配置优化
type QuickListConfig struct {
    CompressFactor int  // 压缩因子，影响内存使用
    FillFactor     int  // 填充因子，影响性能
}

// 模拟QuickList节点
type QuickListNode struct {
    ZipList   []byte  // 压缩列表数据
    Prev      *QuickListNode
    Next      *QuickListNode
    Compressed bool   // 是否压缩
}

// 高性能消息队列实现
type RedisMessageQueue struct {
    client      *redis.Client
    queueName   string
    maxLength   int64
    blockTimeout time.Duration
}

func (mq *RedisMessageQueue) Publish(message string) error {
    pipe := mq.client.Pipeline()
    
    // 添加消息到队列头部
    pipe.LPush(context.Background(), mq.queueName, message)
    
    // 限制队列长度，防止内存溢出
    if mq.maxLength > 0 {
        pipe.LTrim(context.Background(), mq.queueName, 0, mq.maxLength-1)
    }
    
    _, err := pipe.Exec(context.Background())
    return err
}

func (mq *RedisMessageQueue) Consume() (string, error) {
    result, err := mq.client.BRPop(context.Background(), mq.blockTimeout, mq.queueName).Result()
    if err != nil {
        return "", err
    }
    
    if len(result) > 1 {
        return result[1], nil
    }
    
    return "", fmt.Errorf("no message received")
}

// 可靠消息队列（带确认机制）
func (mq *RedisMessageQueue) ReliableConsume(consumerID string) (string, error) {
    processingQueue := mq.queueName + ":processing:" + consumerID
    
    // 使用Lua脚本原子性地移动消息
    script := `
        local message = redis.call('RPOP', KEYS[1])
        if message then
            redis.call('LPUSH', KEYS[2], message)
            redis.call('EXPIRE', KEYS[2], 300)  -- 5分钟超时
            return message
        end
        return nil
    `
    
    result, err := mq.client.Eval(context.Background(), script, []string{mq.queueName, processingQueue}).Result()
    if err != nil {
        return "", err
    }
    
    if result == nil {
        return "", fmt.Errorf("no message available")
    }
    
    return result.(string), nil
}

func (mq *RedisMessageQueue) AckMessage(consumerID, message string) error {
    processingQueue := mq.queueName + ":processing:" + consumerID
    return mq.client.LRem(context.Background(), processingQueue, 1, message).Err()
}
```

##### 3.2 时间线与活动流
**社交媒体时间线实现**：
```go
type SocialTimeline struct {
    client       *redis.Client
    keyPrefix    string
    maxTimelineSize int64
}

func (st *SocialTimeline) AddPost(userID int64, postID int64, timestamp int64) error {
    // 获取用户的关注者列表
    followers, err := st.getFollowers(userID)
    if err != nil {
        return err
    }
    
    // 构造时间线条目
    timelineEntry := fmt.Sprintf("%d:%d:%d", timestamp, userID, postID)
    
    pipe := st.client.Pipeline()
    
    // 推送到所有关注者的时间线
    for _, followerID := range followers {
        timelineKey := fmt.Sprintf("%s:timeline:%d", st.keyPrefix, followerID)
        
        // 按时间戳排序插入
        pipe.LPush(context.Background(), timelineKey, timelineEntry)
        
        // 限制时间线长度
        pipe.LTrim(context.Background(), timelineKey, 0, st.maxTimelineSize-1)
    }
    
    _, err = pipe.Exec(context.Background())
    return err
}

func (st *SocialTimeline) GetTimeline(userID int64, offset, limit int64) ([]TimelinePost, error) {
    timelineKey := fmt.Sprintf("%s:timeline:%d", st.keyPrefix, userID)
    
    entries, err := st.client.LRange(context.Background(), timelineKey, offset, offset+limit-1).Result()
    if err != nil {
        return nil, err
    }
    
    var posts []TimelinePost
    for _, entry := range entries {
        post, err := st.parseTimelineEntry(entry)
        if err == nil {
            posts = append(posts, post)
        }
    }
    
    return posts, nil
}

type TimelinePost struct {
    Timestamp int64
    UserID    int64
    PostID    int64
}

func (st *SocialTimeline) parseTimelineEntry(entry string) (TimelinePost, error) {
    parts := strings.Split(entry, ":")
    if len(parts) != 3 {
        return TimelinePost{}, fmt.Errorf("invalid timeline entry format")
    }
    
    timestamp, _ := strconv.ParseInt(parts[0], 10, 64)
    userID, _ := strconv.ParseInt(parts[1], 10, 64)
    postID, _ := strconv.ParseInt(parts[2], 10, 64)
    
    return TimelinePost{
        Timestamp: timestamp,
        UserID:    userID,
        PostID:    postID,
    }, nil
}
```  


## 四、Set（集合）
### 核心原理  
底层用**整数集合（intset）**或**哈希表（dict）**。整数集合存储纯整数（支持int16/int32/int64，插入更大整数时触发全量升级，如int16→int32），内存连续无冗余；哈希表存储非整数元素，key为member、value为`NULL`（仅作去重标记），节点分散导致内存碎片化。编码切换条件：元素含非整数或数量超512时，intset转为dict且无法回退。  

### 技术组成  
- 编码切换：`intset`（元素全为整数且数量≤512）→`dict`（含非整数或超数量）。  
- 操作特性：`SADD/SREM`保证唯一性，`SINTER/SUNION`等集合运算时间复杂度为O(n)，大集合运算需异步处理。  

### 注意事项  
- 集合运算性能：千万级大集合求交/并会阻塞主线程，建议拆分小集合或用Redis Cluster分片。  
- 去重场景：用户标签系统（每个用户标签存为Set），`SADD`自动去重，`SMEMBERS`谨慎用于大集合（O(n)时间）。  

### 使用场景  
- 标签系统（用户兴趣标签）：`SADD user:tags:1001 movie music`，`SINTER`找共同兴趣用户。  
- 抽奖系统：`SADD`参与用户ID，`SRANDMEMBER`随机抽取中奖者。  


## 五、Sorted Set（有序集合）
### 核心原理  
底层用**压缩列表**或**跳表（skiplist）+ 字典（dict）**。压缩列表要求元素数≤128且单元素≤64字节，结构同Hash/List的ziplist；跳表+字典中，跳表按score排序（节点含多层级，层级由概率1/2的随机函数生成，平均层级为2），字典存member→score映射保证O(1)查询。编码切换后（如元素数超128），ziplist转为skiplist+dict且无法回退，score为双精度浮点数需注意精度丢失场景。  

### 技术组成  
- 编码切换：`ziplist`（元素数≤128且每个元素≤64字节）→`skiplist`（超阈值切换）。  
- 操作特性：`ZADD`带score插入，`ZRANGEBYSCORE`按分数范围查询，`ZREVRANK`查倒序排名；跳表层级随机生成（平均O(log n)复杂度）。  

### 注意事项  
- 分数精度：score为双精度浮点数，极端场景（如金融计算）需避免精度丢失，改用整数放大（如分转元×100）。  
- 内存优化：排行榜场景若只需Top N，用`ZREVRANGE`代替全量存储，减少内存占用。  

### 使用场景  
- 实时排行榜（游戏段位、销售榜单）：`ZADD rank:game:1001 userA 100 userB 95`，`ZREVRANGE rank:game:1001 0 9`取Top10。  
- 延迟任务：score设为任务执行时间戳，`ZRANGEBYSCORE`轮询获取到期任务。  


## 六、Stream（流）
### 核心原理
Redis 5.0新增的Stream是专为消息队列设计的类型，底层结合**基数树（radix tree）**与**列表打包（listpack）**存储。基数树按消息ID（形如`时间戳-序列号`，如`1699999999999-0`）前缀分层索引，支持高效范围查询；listpack存储消息体（含field-value对），保证内存连续性。消息ID全局唯一且单调递增，由服务端生成（避免客户端时间回拨冲突）。

### 底层结构
- 消费者组（Consumer Group）：每个组维护`last_delivered_id`（已投递给消费者的最大ID）和待确认（Pending Entries List, PEL）队列，PEL记录已投递但未ACK的消息，确保消费幂等性。
- 持久化：Stream消息默认落盘（AOF/RDB），支持断点续传；消息删除需显式调用`XDEL`，旧消息可通过`MAXLEN`策略（如`~`近似修剪）自动淘汰。

### 使用场景
- 分布式消息队列：多消费者组（如订单系统拆分为库存、物流组）并行消费，`XADD`生产消息，`XREADGROUP GROUP g1 c1 COUNT 10 BLOCK 5000 STREAMS s1 >`阻塞拉取未消费消息。
- 事件溯源：按时间线存储系统事件（如用户操作日志），`XRANGE s1 - +`全量回溯历史事件。

## 七、Vector Set（矢量集合，Redis Stack扩展）
### 核心原理
基于**矢量相似度搜索（Vector Similarity Search）**实现，底层用**分层导航小世界（HNSW）**算法构建索引，支持欧氏距离、余弦相似度等度量。矢量元素以二进制数组存储，结合Redis的内存管理机制实现高效检索。

### 底层结构
- 索引构建：HNSW通过多层跳跃图加速近邻查找，每层节点数按概率递减（类似跳表），插入新矢量时动态扩展层级；元数据存储矢量维度、距离 metric 等配置。
- 混合查询：支持矢量相似度与传统Redis数据类型（如Hash属性过滤）的联合查询，如`FT.SEARCH idx 

## 八、Bitmaps（位映射）
### 核心原理  
Redis Bitmaps本质是**String类型**的位操作扩展，底层复用SDS存储二进制位序列，每个bit对应一个布尔状态（0/1）。位操作基于`offset`（位偏移）实现原子读写：`SETBIT key offset value`设置指定偏移位的值，`GETBIT key offset`读取位值，`BITCOUNT key [start end]`统计指定区间内的置位数量。内存占用与最大offset正相关（每8位占1字节），若仅操作小范围offset（如≤1000），内存开销极低（1000位≈125字节）。  

### 底层结构  
完全复用String的SDS编码（`int`/`embstr`/`raw`），位操作通过对字节数组的位运算实现。例如，offset=10对应第2个字节（索引从0开始）的第2位（10 = 1*8 + 2），修改该位时直接操作字节数组，保证原子性（Redis单线程模型）。  

### 注意事项  
- 偏移溢出：`SETBIT`的offset无上限，但超大offset（如1e9）会导致String膨胀至GB级，需严格控制offset范围。  
- 批量操作：`BITOP`（AND/OR/XOR/NOT）支持多Key位运算，但参与运算的Key需同长度，否则自动补0可能导致内存浪费。  

### 使用场景  
- 日活统计：为每个用户设置`user:login:20241001`的Bitmaps，`SETBIT`记录登录（offset=用户ID），`BITCOUNT`统计当日活跃用户数。  
- 签到系统：用户每月签到存为`user:sign:1001:202410`，`SETBIT offset=日期 value=1`，`BITCOUNT`查全月签到天数，`BITOP`对比多月签到模式。  


## 九、HyperLogLog（基数统计）
### 核心原理  
基于**概率基数算法**实现近似去重计数，仅需12KB内存即可统计≤2⁶⁴个不同元素，标准误差约0.81%。底层采用**稀疏矩阵→稠密矩阵**的动态存储优化：小基数时用稀疏结构（仅记录非零桶）节省空间，基数超过阈值（约12k元素）时转为稠密矩阵（固定12KB）。算法通过“伯努利试验”统计最长连续0的位数（桶的寄存器值），结合调和平均估算基数。  

### 底层结构  
由多个“桶（bucket）”组成，每个桶对应一个寄存器存储最大连续0的位数。Redis对HyperLogLog的实现做了优化：稀疏模式下用哈希表记录非零桶的位置与值，稠密模式下用字节数组存储所有桶的寄存器（每个寄存器占6位，共2048个桶）。  

### 注意事项  
- 精度 trade-off：统计结果为近似值，金融级精确计数需用Set；但大基数场景（如千万级UV）HyperLogLog的内存优势碾压Set。  
- 合并操作：`PFMERGE`合并多个HyperLogLog时，时间复杂度为O(n)（n为桶数量），大数量合并需异步处理。  

### 使用场景  
- 页面UV统计：每个页面一个HyperLogLog（如`page:uv:home`），`PFADD`记录访问用户ID，`PFCOUNT`统计独立访客数；多页面合并用`PFMERGE`。  
- 行为去重统计：统计用户不同渠道的行为（如APP、H5、小程序），每个渠道一个HyperLogLog，合并后分析全渠道触达用户数。  
`