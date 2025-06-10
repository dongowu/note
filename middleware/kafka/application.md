# Kafka 高级应用场景总结

## 一、消息过期时间（消息保留策略）

### 1. 概念
消息过期时间指Kafka对Topic中消息的自动清理机制，通过设置保留时长或大小，避免存储无限增长。

### 2. 背景
Kafka作为高吞吐消息系统，若消息无限制存储会导致磁盘溢出，需通过过期策略平衡存储成本与数据可用性。

### 3. 核心原理
Kafka通过日志段（Segment）管理消息，定期扫描旧日志段，根据`log.retention.ms`（时间）或`log.retention.bytes`（大小）策略删除过期消息。

### 4. 技术实现细节
- **参数配置**：  
  - `log.retention.ms`：消息保留时间（默认7天）；  
  - `log.retention.bytes`：分区最大存储量（默认-1，不限制）；  
  - `log.cleanup.policy`：清理策略（`delete`删除过期段，`compact`保留每个Key的最新Value）。  
- **清理触发**：Broker后台线程`LogCleaner`定期检查（间隔由`log.cleaner.backoff.ms`控制，默认15000ms）。

### 5. 解决的问题
- 存储资源浪费：避免无效历史消息占用磁盘；  
- 运维复杂度：减少人工清理日志的成本。

### 6. 实现方案
- **时间驱动**：适用于日志类场景（如用户行为日志），设置`log.retention.ms=604800000`（7天）；  
- **大小驱动**：适用于高频写入场景（如实时指标），设置`log.retention.bytes=1073741824`（1GB）；  
- **混合策略**：同时启用时间和大小限制，取两者中更严格的条件。

### 7. 使用场景
- 日志收集系统（如ELK）：保留7天日志用于分析；  
- 实时监控指标：保留24小时数据用于趋势计算。

### 8. 注意事项
- 大消息影响：单条消息超过`log.segment.bytes`（默认1GB）会导致无法清理；  
- 压缩策略冲突：`compact`与`delete`策略不可同时启用（需通过`log.cleanup.policy=delete,compact`指定多策略）；  
- 监控验证：通过`kafka-log-dirs.sh --describe`命令检查日志段大小和保留时间。

---

## 二、延时队列

### 1. 概念
延时队列指消息发送后不立即被消费，而是在指定延迟时间后才被处理的队列模式。

### 2. 背景
业务中常需延迟任务（如订单30分钟未支付自动取消、短信5分钟后重试），传统定时任务效率低，需基于消息系统实现。

### 3. 核心原理
通过“分层Topic”或“时间戳标记”控制消费时机：  
- **分层Topic**：按延迟时间划分多个Topic（如`delay_5m`、`delay_30m`），生产者根据延迟时间发送到对应Topic，消费者定时轮询；  
- **时间戳标记**：消息携带`timestamp`字段，消费者拉取后检查时间戳，未到延迟时间则暂存或重新入队。

### 4. 技术实现细节
- **方案1：分层Topic（推荐）**  
  ```go
  // 生产者根据延迟时间选择Topic
  func SendDelayedMessage(msg string, delay time.Duration) {
      topic := fmt.Sprintf("delay_%dm", int(delay.Minutes()))
      producer.SendMessage(topic, msg)
  }

  // 消费者定时消费（每5分钟扫描一次delay_5m Topic）
  func ConsumeDelayedTopic(topic string) {
      ticker := time.NewTicker(5 * time.Minute)
      for range ticker.C {
          messages := consumer.Poll(topic)
          processMessages(messages)
      }
  }
  ```
- **方案2：时间戳+重试入队**  
  消费者拉取消息后，若`now < message.Timestamp + delay`，则将消息重新发送到原Topic（设置`linger.ms`延迟发送）。

### 5. 解决的问题
- 定时任务资源浪费：避免为每个延迟任务启动独立定时器；  
- 任务超时精度：通过消息系统保证延迟时间的准确性（误差≤1s）。

### 6. 实现方案
- 轻量级场景：使用分层Topic（适合延迟时间固定且种类少，如5/30/60分钟）；  
- 动态延迟场景：结合Kafka Streams，通过`window`操作按时间窗口聚合消息（如`TimeWindows.of(Duration.ofMinutes(5))`）。

### 7. 使用场景
- 电商订单超时取消（30分钟延迟）；  
- 短信/邮件延迟发送（失败后5分钟重试）。

### 8. 注意事项
-  Topic数量控制：分层Topic需避免过多（如按1分钟划分会导致数百个Topic）；  
- 消息重复问题：重新入队时需保证幂等（通过消息ID去重）；  
- 消费延迟监控：监控`Consumer Lag`，避免因消费者处理慢导致实际延迟超预期。

---

## 三、死信队列（Dead Letter Queue, DLQ）与重试队列

### 1. 概念
- **重试队列**：消费失败的消息重新入队，供消费者重试处理；  
- **死信队列**：重试多次仍失败的消息最终存放的Topic，用于人工排查。

### 2. 背景
消费过程中可能因网络抖动、业务逻辑异常导致失败，需通过重试提升成功率，无法解决的异常消息需隔离存储。

### 3. 核心原理
消费者捕获异常后，将消息发送到重试队列（按重试次数区分，如`retry_1`、`retry_2`）；若达到最大重试次数（如3次），则转发到DLQ。

### 4. 技术实现细节
- **消费者异常处理流程**：  
  ```go
  func ConsumeWithRetry(msg Message) {
      maxRetries := 3
      for retry := 0; retry < maxRetries; retry++ {
          if err := processMessage(msg); err == nil {
              return // 处理成功
          }
          // 重试次数未达上限，发送到重试队列
          retryTopic := fmt.Sprintf("retry_%d", retry+1)
          producer.Send(retryTopic, msg)
          time.Sleep(1 * time.Second) // 指数退避（可优化为2^retry秒）
      }
      // 重试失败，发送到DLQ
      producer.Send("dead_letter_queue", msg)
  }
  ```
- **DLQ配置**：需单独创建Topic（推荐`replication.factor=3`，`retention.ms=30*24*3600*1000`保留30天）。

### 5. 解决的问题
- 消息丢失：避免因单次失败直接丢弃消息；  
- 故障隔离：DLQ集中存储异常消息，减少对正常消费的影响。

### 6. 实现方案
- 简单重试：消费者内部实现重试逻辑（适合轻量级场景）；  
- 框架集成：使用Spring Kafka的`SeekToCurrentErrorHandler`或Confluent的`DeadLetterPublishingRecoverer`（自动转发到DLQ）。

### 7. 使用场景
- 支付结果通知（网络抖动导致调用支付接口失败）；  
- 库存扣减（数据库锁冲突导致失败）。

### 8. 注意事项
- 重试间隔：避免固定间隔（如1s）导致“洪峰”，建议指数退避（如1s→2s→4s）；  
- DLQ监控：通过`kafka-consumer-groups.sh`监控DLQ的`LAG`，及时人工处理；  
- 消息上下文：DLQ消息需携带原始错误信息（如`error_msg`字段），方便排查。

---

## 四、消息路由（Message Routing）

### 1. 概念
消息路由指根据消息内容（如Key、Header、Body）动态分发到不同Topic的机制。

### 2. 背景
微服务架构中，不同业务模块需消费不同类型的消息（如订单消息需分发给物流、库存、财务系统），需动态路由。

### 3. 核心原理
通过自定义分区器（Partitioner）或拦截器（Interceptor），在消息发送前根据规则路由到目标Topic。

### 4. 技术实现细节
- **自定义分区器（推荐）**：  
  ```java
  public class RoutingPartitioner implements Partitioner {
      @Override
      public int partition(String topic, Object key, byte[] keyBytes, Object value, byte[] valueBytes, Cluster cluster) {
          // 从消息头获取目标Topic
          String targetTopic = ((ProducerRecord<?, ?>) value).headers().lastHeader("target_topic").value().toString();
          // 返回目标Topic的分区数（需提前创建Topic）
          return cluster.partitionsForTopic(targetTopic).size() - 1;
      }
  }
  ```
- **拦截器实现**：在`onSend`方法中修改`ProducerRecord`的Topic字段。

### 5. 解决的问题
- 生产者解耦：避免生产者直接感知多个消费者的Topic；  
- 动态扩展：新增消费场景时只需创建新Topic，无需修改生产者代码。

### 6. 实现方案
- 基于Header路由：消息头携带`target_topic`字段（适合轻量级规则）；  
- 基于Body内容路由：通过JSON解析消息体的`type`字段（如`{"type":"order","data":...}`）。

### 7. 使用场景
- 多租户系统：根据消息的`tenant_id`路由到租户专属Topic；  
- 事件分类：将`user_event`消息按类型（`login`/`register`）路由到`user_login`/`user_register` Topic。

### 8. 注意事项
- 目标Topic预创建：路由前需确保目标Topic存在（可通过AdminClient自动创建）；  
- 性能影响：JSON解析或正则匹配会增加延迟（高吞吐场景需优化）；  
- 失败处理：路由失败的消息需发送到`invalid_routing` Topic（避免丢失）。

---

## 五、消息轨迹（Message Tracing）

### 1. 概念
消息轨迹指记录消息从生产到消费的全链路路径（如生产者ID、时间戳、消费节点、处理状态）。

### 2. 背景
分布式系统中，消息可能经过多个服务处理，需追踪链路以排查消息丢失、延迟等问题。

### 3. 核心原理
通过在消息头中添加追踪ID（如OpenTelemetry的`trace_id`），并在每个处理节点记录日志，最终聚合形成完整轨迹。

### 4. 技术实现细节
- **消息头注入**（生产者）：  
  ```go
  func SendWithTrace(msg string, traceID string) {
      headers := []kafka.Header{{Key: "trace_id", Value: []byte(traceID)}}
      producer.SendMessage("topic", msg, headers)
  }
  ```
- **消费端记录**（消费者）：  
  ```go
  func ConsumeAndLog(msg kafka.Message) {
      traceID := string(msg.Headers[0].Value)
      log.Printf("Consumed message, trace_id=%s, offset=%d", traceID, msg.Offset)
  }
  ```
- **轨迹存储**：通过Kafka Connect将轨迹日志写入Elasticsearch或HBase，使用Kibana可视化。

### 5. 解决的问题
- 问题定位困难：快速定位消息在哪个环节丢失或延迟；  
- 性能瓶颈分析：统计各节点处理耗时，优化链路。

### 6. 实现方案
- 轻量级追踪：仅记录`trace_id`和时间戳（适合内部系统）；  
- 全链路追踪：集成OpenTelemetry，关联消息轨迹与服务调用链（如通过`span_id`关联）。

### 7. 使用场景
- 电商大促期间消息链路排查（如订单消息未到达物流系统）；  
- 金融交易系统审计（需记录消息的完整处理路径）。

### 8. 注意事项
- 追踪ID全局唯一：使用UUID或雪花算法生成（避免冲突）；  
- 存储成本：轨迹数据量大，需设置合理的保留时间（如7天）；  
- 性能损耗：消息头增加会略微增大网络传输量（可压缩处理）。

---

## 六、消息代理（Message Broker）

### 1. 概念
消息代理指Kafka作为中间媒介，解耦生产者与消费者，支持多生产者发布、多消费者订阅的模式。

### 2. 背景
传统点对点通信（如RPC）耦合性高，需通过消息代理实现系统间松耦合、异步通信。

### 3. 核心原理
Kafka通过Topic实现发布-订阅模型：生产者向Topic发送消息，消费者从Topic订阅消息，无需感知彼此存在。

### 4. 技术实现细节
- **多生产者支持**：任意服务（Go/Java/PHP）通过Kafka客户端发送消息到同一Topic；  
- **多消费者支持**：消费者组（Consumer Group）内的多个消费者并行消费Topic的不同分区。

### 5. 解决的问题
- 系统耦合：生产者与消费者无需知道对方地址或接口；  
- 流量削峰：通过消息队列缓冲突发流量（如大促期间订单洪峰）。

### 6. 实现方案
- 事件驱动架构（EDA）：系统通过消息代理传递事件（如`OrderCreatedEvent`触发库存扣减、物流下单）；  
- 异步通信：替代同步RPC调用，降低服务间依赖（如用户注册后异步发送欢迎邮件）。

### 7. 使用场景
- 微服务间通信（如用户服务→订单服务→支付服务）；  
- 日志收集（多应用发送日志到`app_logs` Topic，统一由ELK消费）。

### 8. 注意事项
- 消息顺序性：需保证顺序的场景（如订单状态变更）需将消息路由到同一分区；  
- 幂等性设计：消费者需处理重复消息（通过消息ID去重）；  
- 服务降级：消息积压时需设置`max.poll.records`限制单次拉取量，避免内存溢出。

## 补充


## 生产者消息发送全流程与风险控制

### 1. 消息发送全流程解析
Kafka生产者发送消息的完整流程可分为7个关键步骤（以Go客户端为例）：

#### 1.1 消息构造与序列化
- **输入**：用户调用`producer.SendMessage(&kafka.Message{Key: []byte("key"), Value: []byte("value")})`构造消息。
- **序列化**：使用`google.golang.org/protobuf`库将消息体（如Protobuf对象）序列化为字节数组（示例：`user.MarshalTo(dAtA)`）。
- **元数据补充**：自动添加`timestamp`（消息时间戳，默认取客户端时间）、`headers`（自定义扩展头）等元数据。

#### 1.2 分区路由（Partition Selection）
- **默认策略**：若消息指定`Key`，通过`murmur2`哈希算法对Key取模（`partition = hash(key) % numPartitions`）；若未指定Key，使用轮询（RoundRobin）分配分区。
- **自定义分区**：通过实现`kafka.Partitioner`接口动态路由（示例：根据消息中的`tenant_id`字段路由到租户专属分区）：
  ```go
  type TenantPartitioner struct{}
  func (p *TenantPartitioner) Partition(msg *kafka.Message, numPartitions int) int {
      tenantID := string(msg.Headers[0].Value) // 从Header获取租户ID
      return int(murmur2([]byte(tenantID))) % numPartitions
  }
  ```

#### 1.3 批量缓冲与延迟发送
- **批量聚合**：消息先存入`send buffer`（大小由`buffer.memory`控制，默认33554432字节），达到`batch.size`（默认16384字节）或`linger.ms`（默认0ms）时触发发送。
- **Go实现示例**：客户端通过`sync.WaitGroup`管理批量任务，使用`time.Ticker`触发超时发送：
  ```go
  ticker := time.NewTicker(producer.Config().LingerMs * time.Millisecond)
  for {
      select {
      case msg := <-producer.incomingMessages:
          producer.batchBuffer = append(producer.batchBuffer, msg)
          if len(producer.batchBuffer)*msg.Size() >= producer.Config().BatchSize {
              producer.flushBatch()
          }
      case <-ticker.C:
          if len(producer.batchBuffer) > 0 {
              producer.flushBatch()
          }
      }
  }
  ```

#### 1.4 网络传输与ACK确认
- **请求封装**：将批量消息封装为`ProduceRequest`（包含Topic、分区、消息集），通过`TCP`发送至Broker的`SocketServer`。
- **ACK机制**：根据`acks`配置决定确认策略：
  - `acks=0`：无需确认（可能丢消息）；
  - `acks=1`：Leader确认（主副本丢失时可能丢消息）；
  - `acks=all`（默认）：ISR所有副本确认（强一致性）。

#### 1.5 失败重试与幂等性保障
- **重试触发**：遇到可重试错误（如`NetworkException`、`LeaderNotAvailableException`）时，根据`retries`（默认2147483647）和`retry.backoff.ms`（默认100ms）进行指数退避重试。
- **幂等性保障**：启用`enable.idempotence=true`时，Broker通过`PID+序列号`去重（示例：`PID=12345`，序列号从0递增，重复序列号消息直接丢弃）。

### 2. 关键风险点与规避措施
| 风险点                | 触发原因                                                                 | 规避方案                                                                 |
|-----------------------|--------------------------------------------------------------------------|--------------------------------------------------------------------------|
| **消息丢失**          | `acks=0`/`acks=1`且Leader宕机；缓冲区满时`buffer.memory`不足触发阻塞或抛异常 | 1. 生产环境强制`acks=all`；<br>2. 设置`buffer.memory=67108864`（64MB）；<br>3. 监控`record-error-rate`指标（Prometheus） |
| **消息重复**          | 重试导致相同消息被多次发送；未正确使用幂等性/事务                        | 1. 启用`enable.idempotence=true`（单会话幂等）；<br>2. 跨会话/Topic使用事务（`transactional.id`）；<br>3. 消费者端幂等（消息ID去重） |
| **发送延迟高**        | `batch.size`过小/`linger.ms`过长；网络带宽不足；Broker负载过高            | 1. 调大`batch.size=32768`（32KB）；<br>2. 设置`linger.ms=20`（平衡延迟与吞吐量）；<br>3. 监控Broker的`NetworkProcessorAvgIdlePercent`（应>30%） |
| **缓冲区溢出**        | 生产者发送速率超过Broker处理能力，`buffer.memory`耗尽                    | 1. 启用`max.block.ms=60000`（阻塞60秒后抛异常）；<br>2. 结合Kafka Exporter监控`kafka.producer.buffer-available-bytes`指标 |

---

## Kafka LogManager核心功能解析

### 1. 核心功能概述
LogManager是Kafka Broker的日志管理核心组件，负责**日志段（Segment）的生命周期管理**，核心功能包括：

#### 1.1 日志段创建与滚动（Log Segment Creation & Rolling）
- **创建条件**：新分区初始化或当前日志段大小超过`log.segment.bytes`（默认1GB），或距离上次滚动时间超过`log.roll.ms`（默认7天）。
- **Go模拟实现**（伪代码）：
  ```go
  func (lm *LogManager) checkRoll(partition *Partition) {
      currentSegment := partition.currentSegment()
      if currentSegment.size() > lm.config.SegmentSize || 
         time.Since(currentSegment.createdAt) > lm.config.RollInterval {
          partition.rollNewSegment() // 创建新日志段（.log/.index/.timeindex文件）
      }
  }
  ```

#### 1.2 日志清理（Log Cleanup）
- **触发条件**：日志总大小超过`log.retention.bytes`或最旧消息超过`log.retention.ms`；定时任务由`LogCleaner`线程每`log.cleaner.backoff.ms`（默认15秒）执行。
- **核心接口**：`LogCleaner.clean()`方法，支持`delete`（删除过期段）和`compact`（保留每个Key的最新Value）两种策略。

#### 1.3 日志恢复（Log Recovery）
- **Broker启动时**：扫描所有日志段，通过`log.end.offset`（LEO）和`log.flush.offset`（FEO）确定未持久化的消息，截断无效日志（如`log.segment`末尾不完整的消息）。
- **幂等性保障**：通过`TransactionStateManager`恢复未提交的事务（从`__transaction_state`主题读取事务元数据）。

#### 1.4 日志索引管理（Index Management）
- **偏移量索引（.index）**：记录消息在日志段中的物理偏移（Offset→Position映射），支持二分查找；
- **时间戳索引（.timeindex）**：记录时间戳→偏移量映射，用于按时间范围查询（如`kafka-consumer-groups.sh --time 1622505600000`）。

---

## 消费者消息丢失原因与防护

### 1. 消息丢失核心场景与根因
| 场景                  | 具体原因                                                                 | 丢失类型          |
|-----------------------|--------------------------------------------------------------------------|-------------------|
| **自动提交Offset**     | `enable.auto.commit=true`时，Offset在消息处理前提交（如处理失败但Offset已提交） | 至多一次（At Most Once） |
| **Rebalance未及时提交** | 消费者组Rebalance时，未提交的Offset被其他消费者跳过（如当前消费者处理中但未提交） | 部分丢失          |
| **消费者崩溃**         | 手动提交前进程崩溃（如`commitSync()`调用前发生OOM）                        | 中间消息丢失      |
| **事务消息未消费**     | 生产者事务未提交时，消费者配置`isolation.level=read_committed`跳过未提交消息 | 预期外丢失（正常行为） |

### 2. 全链路防护方案
#### 2.1 消费语义升级（At Least Once → Exactly Once）
- **手动提交Offset**：关闭自动提交（`enable.auto.commit=false`），处理成功后调用`CommitMessages()`：
  ```go
  for {
      msg, err := consumer.ReadMessage(ctx)
      if err != nil { break }
      if err := process(msg); err == nil {
          consumer.CommitMessages(ctx, msg) // 仅处理成功时提交
      }
  }
  ```
- **事务消费者**（Kafka 0.11+）：结合生产者事务，通过`Consumer.beginTransaction()`→`consume()`→`produce()`→`commitTransaction()`保证原子性。

#### 2.2 Rebalance防护
- **注册Rebalance监听器**：在`ConsumerRebalanceListener`的`onPartitionsRevoked`回调中提交当前Offset：
  ```java
  consumer.subscribe(topics, new ConsumerRebalanceListener() {
      @Override
      public void onPartitionsRevoked(Collection<TopicPartition> partitions) {
          consumer.commitSync(Collections.singletonMap(partitions.iterator().next(), new OffsetAndMetadata(currentOffset)));
      }
  });
  ```

#### 2.3 崩溃恢复保障
- **持久化Offset**：使用`__consumer_offsets`主题（默认保留7天）存储Offset，避免内存数据丢失；
- **增量提交**：批量处理消息后提交（如每100条提交一次），平衡性能与可靠性。

---

##  LogManager日志清理策略详解

### 1. 主流清理策略对比
| 策略类型       | 核心逻辑                                                                 | 适用场景                                                                 | 关键参数                                                                 |
|----------------|--------------------------------------------------------------------------|--------------------------------------------------------------------------|--------------------------------------------------------------------------|
| **Delete（删除）** | 删除超过保留时间（`log.retention.ms`）或大小（`log.retention.bytes`）的日志段 | 日志类、监控指标等无需保留历史数据的场景（如用户行为日志）                | `log.retention.ms=604800000`（7天）<br>`log.retention.bytes=1073741824`（1GB） |
| **Compact（压缩）** | 保留每个Key的最新Value，删除旧Value（通过`log.cleaner.min.compaction.lag.ms`控制最小保留时间） | 需保留最新状态的场景（如设备状态、用户配置）                              | `log.cleanup.policy=compact`<br>`log.cleaner.min.dirty.ratio=0.5`（日志段中需压缩的比例阈值） |
| **混合策略**     | 同时启用Delete和Compact（通过`log.cleanup.policy=delete,compact`配置）      | 既需保留最新状态，又需限制总存储的场景（如订单状态，保留30天内的最新状态） | `log.retention.ms=2592000000`（30天）<br>`log.cleaner.min.compaction.lag.ms=86400000`（1天） |

### 2. Compact策略实现细节
- **清理线程（LogCleaner）**：通过`CleanerThread`从`log.cleaner.threads`（默认1）个线程中选取，对日志段进行“复制-删除”操作：
  1. 读取日志段的所有消息，按Key分组，保留最大Offset的消息；
  2. 将清理后的消息写入新日志段（`cleaned-<baseOffset>.log`）；
  3. 替换原日志段，删除旧文件。
- **Key匹配规则**：消息Key需为非null（`null` Key的消息不会被压缩，直接保留），适用于`key=userId`、`key=deviceId`等业务场景。

### 3. 清理策略验证方法
- **手动触发清理**：通过`kafka-log-dirs.sh --bootstrap-server localhost:9092 --topic-list my-topic --force-clean`命令强制清理；
- **监控指标**：Prometheus的`kafka.logs.cleaned-bytes-total`（已清理字节数）、`kafka.logs.dirty-ratios`（待清理比例）；
- **日志段检查**：使用`kafka-dump-log.sh --files /path/to/logs/*.log`查看压缩前后的消息分布。

---

## 企业级应用架构模式

### 1. 事件驱动架构（Event-Driven Architecture, EDA）

#### 1.1 架构设计原则
事件驱动架构通过事件的发布和订阅实现系统间的松耦合通信，核心原则包括：
- **事件优先**：业务操作产生事件，而非直接调用下游服务
- **异步处理**：通过消息队列解耦时间依赖
- **最终一致性**：接受短期数据不一致，通过事件传播达到最终一致

#### 1.2 Go实现示例
```go
// 事件定义
type OrderEvent struct {
    EventID   string    `json:"event_id"`
    EventType string    `json:"event_type"` // OrderCreated, OrderPaid, OrderShipped
    OrderID   string    `json:"order_id"`
    UserID    string    `json:"user_id"`
    Amount    float64   `json:"amount"`
    Timestamp time.Time `json:"timestamp"`
}

// 事件发布器
type EventPublisher struct {
    producer *kafka.Writer
}

func (ep *EventPublisher) PublishOrderEvent(event OrderEvent) error {
    eventData, _ := json.Marshal(event)
    return ep.producer.WriteMessages(context.Background(), kafka.Message{
        Topic: "order-events",
        Key:   []byte(event.OrderID), // 保证同一订单事件顺序
        Value: eventData,
        Headers: []kafka.Header{
            {Key: "event-type", Value: []byte(event.EventType)},
            {Key: "source", Value: []byte("order-service")},
        },
    })
}

// 事件处理器
type InventoryEventHandler struct {
    consumer *kafka.Reader
    db       *sql.DB
}

func (ieh *InventoryEventHandler) HandleOrderEvents() {
    for {
        msg, err := ieh.consumer.ReadMessage(context.Background())
        if err != nil {
            log.Printf("Error reading message: %v", err)
            continue
        }
        
        var event OrderEvent
        if err := json.Unmarshal(msg.Value, &event); err != nil {
            log.Printf("Error unmarshaling event: %v", err)
            continue
        }
        
        switch event.EventType {
        case "OrderCreated":
            ieh.reserveInventory(event.OrderID, event.UserID)
        case "OrderCancelled":
            ieh.releaseInventory(event.OrderID)
        }
    }
}

func (ieh *InventoryEventHandler) reserveInventory(orderID, userID string) {
    // 库存预留逻辑
    tx, _ := ieh.db.Begin()
    defer tx.Rollback()
    
    _, err := tx.Exec("UPDATE inventory SET reserved = reserved + 1 WHERE product_id = ?", orderID)
    if err != nil {
        // 发布库存不足事件
        ieh.publishInventoryEvent("InventoryInsufficient", orderID)
        return
    }
    
    tx.Commit()
    ieh.publishInventoryEvent("InventoryReserved", orderID)
}
```

### 2. Saga分布式事务模式

#### 2.1 Saga模式原理
Saga模式通过一系列本地事务和补偿操作实现分布式事务，分为：
- **编排式Saga（Orchestration）**：中央协调器管理事务流程
- **编舞式Saga（Choreography）**：服务间通过事件自主协调

#### 2.2 编排式Saga实现
```go
// Saga协调器
type OrderSagaOrchestrator struct {
    producer     *kafka.Writer
    consumer     *kafka.Reader
    sagaStore    map[string]*SagaInstance // 内存存储，生产环境建议用Redis
}

type SagaInstance struct {
    SagaID       string
    OrderID      string
    CurrentStep  int
    Steps        []SagaStep
    Status       string // RUNNING, COMPLETED, COMPENSATING, FAILED
    CompletedSteps []string
}

type SagaStep struct {
    StepName     string
    Service      string
    Action       string
    Compensation string
}

func (oso *OrderSagaOrchestrator) StartOrderSaga(orderID string) {
    sagaID := uuid.New().String()
    saga := &SagaInstance{
        SagaID:  sagaID,
        OrderID: orderID,
        Status:  "RUNNING",
        Steps: []SagaStep{
            {StepName: "payment", Service: "payment-service", Action: "ProcessPayment", Compensation: "RefundPayment"},
            {StepName: "inventory", Service: "inventory-service", Action: "ReserveInventory", Compensation: "ReleaseInventory"},
            {StepName: "shipping", Service: "shipping-service", Action: "CreateShipment", Compensation: "CancelShipment"},
        },
    }
    
    oso.sagaStore[sagaID] = saga
    oso.executeNextStep(saga)
}

func (oso *OrderSagaOrchestrator) executeNextStep(saga *SagaInstance) {
    if saga.CurrentStep >= len(saga.Steps) {
        saga.Status = "COMPLETED"
        oso.publishSagaEvent("SagaCompleted", saga.SagaID, saga.OrderID)
        return
    }
    
    step := saga.Steps[saga.CurrentStep]
    command := SagaCommand{
        SagaID:    saga.SagaID,
        OrderID:   saga.OrderID,
        StepName:  step.StepName,
        Action:    step.Action,
        Service:   step.Service,
    }
    
    commandData, _ := json.Marshal(command)
    oso.producer.WriteMessages(context.Background(), kafka.Message{
        Topic: fmt.Sprintf("%s-commands", step.Service),
        Key:   []byte(saga.OrderID),
        Value: commandData,
    })
}

func (oso *OrderSagaOrchestrator) HandleSagaReply() {
    for {
        msg, err := oso.consumer.ReadMessage(context.Background())
        if err != nil {
            continue
        }
        
        var reply SagaReply
        json.Unmarshal(msg.Value, &reply)
        
        saga := oso.sagaStore[reply.SagaID]
        if reply.Status == "SUCCESS" {
            saga.CompletedSteps = append(saga.CompletedSteps, reply.StepName)
            saga.CurrentStep++
            oso.executeNextStep(saga)
        } else {
            // 开始补偿
            saga.Status = "COMPENSATING"
            oso.startCompensation(saga)
        }
    }
}

func (oso *OrderSagaOrchestrator) startCompensation(saga *SagaInstance) {
    // 逆序执行补偿操作
    for i := len(saga.CompletedSteps) - 1; i >= 0; i-- {
        stepName := saga.CompletedSteps[i]
        for _, step := range saga.Steps {
            if step.StepName == stepName {
                compensation := SagaCommand{
                    SagaID:   saga.SagaID,
                    OrderID:  saga.OrderID,
                    StepName: step.StepName,
                    Action:   step.Compensation,
                    Service:  step.Service,
                }
                
                compensationData, _ := json.Marshal(compensation)
                oso.producer.WriteMessages(context.Background(), kafka.Message{
                    Topic: fmt.Sprintf("%s-commands", step.Service),
                    Key:   []byte(saga.OrderID),
                    Value: compensationData,
                })
                break
            }
        }
    }
}
```

### 3. CQRS（命令查询责任分离）模式

#### 3.1 CQRS架构设计
CQRS将读操作（Query）和写操作（Command）分离，通过事件溯源实现数据同步：
- **命令端**：处理业务写操作，产生事件
- **查询端**：基于事件构建读模型，优化查询性能

#### 3.2 Go实现示例
```go
// 命令处理器
type OrderCommandHandler struct {
    eventStore EventStore
    producer   *kafka.Writer
}

type CreateOrderCommand struct {
    OrderID   string
    UserID    string
    ProductID string
    Quantity  int
    Amount    float64
}

func (och *OrderCommandHandler) HandleCreateOrder(cmd CreateOrderCommand) error {
    // 业务验证
    if cmd.Amount <= 0 {
        return errors.New("invalid amount")
    }
    
    // 创建事件
    event := OrderCreatedEvent{
        EventID:   uuid.New().String(),
        OrderID:   cmd.OrderID,
        UserID:    cmd.UserID,
        ProductID: cmd.ProductID,
        Quantity:  cmd.Quantity,
        Amount:    cmd.Amount,
        Timestamp: time.Now(),
    }
    
    // 持久化事件
    if err := och.eventStore.SaveEvent(event); err != nil {
        return err
    }
    
    // 发布事件
    eventData, _ := json.Marshal(event)
    return och.producer.WriteMessages(context.Background(), kafka.Message{
        Topic: "order-events",
        Key:   []byte(cmd.OrderID),
        Value: eventData,
    })
}

// 查询端投影器
type OrderProjectionHandler struct {
    consumer *kafka.Reader
    readDB   *sql.DB
}

func (oph *OrderProjectionHandler) BuildOrderProjections() {
    for {
        msg, err := oph.consumer.ReadMessage(context.Background())
        if err != nil {
            continue
        }
        
        var event OrderCreatedEvent
        if err := json.Unmarshal(msg.Value, &event); err != nil {
            continue
        }
        
        // 更新读模型
        oph.updateOrderView(event)
        oph.updateUserOrderSummary(event)
        oph.updateProductSalesStats(event)
    }
}

func (oph *OrderProjectionHandler) updateOrderView(event OrderCreatedEvent) {
    query := `
        INSERT INTO order_view (order_id, user_id, product_id, quantity, amount, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'CREATED', ?)
    `
    oph.readDB.Exec(query, event.OrderID, event.UserID, event.ProductID, 
                   event.Quantity, event.Amount, event.Timestamp)
}

func (oph *OrderProjectionHandler) updateUserOrderSummary(event OrderCreatedEvent) {
    query := `
        INSERT INTO user_order_summary (user_id, total_orders, total_amount)
        VALUES (?, 1, ?)
        ON DUPLICATE KEY UPDATE 
        total_orders = total_orders + 1,
        total_amount = total_amount + VALUES(total_amount)
    `
    oph.readDB.Exec(query, event.UserID, event.Amount)
}
```

### 4. 微服务通信模式

#### 4.1 异步消息通信
```go
// 服务间异步通信管理器
type ServiceCommunicationManager struct {
    producer *kafka.Writer
    consumer *kafka.Reader
    handlers map[string]MessageHandler
}

type MessageHandler interface {
    Handle(message []byte) error
}

// 用户服务
type UserService struct {
    db       *sql.DB
    commMgr  *ServiceCommunicationManager
}

func (us *UserService) CreateUser(user User) error {
    // 本地事务
    tx, _ := us.db.Begin()
    defer tx.Rollback()
    
    _, err := tx.Exec("INSERT INTO users (id, name, email) VALUES (?, ?, ?)", 
                     user.ID, user.Name, user.Email)
    if err != nil {
        return err
    }
    
    tx.Commit()
    
    // 发布用户创建事件
    event := UserCreatedEvent{
        UserID:    user.ID,
        Name:      user.Name,
        Email:     user.Email,
        Timestamp: time.Now(),
    }
    
    return us.commMgr.PublishEvent("user-events", event)
}

// 通知服务处理用户事件
type NotificationService struct {
    emailSender EmailSender
}

func (ns *NotificationService) Handle(message []byte) error {
    var event UserCreatedEvent
    if err := json.Unmarshal(message, &event); err != nil {
        return err
    }
    
    // 发送欢迎邮件
    return ns.emailSender.SendWelcomeEmail(event.Email, event.Name)
}

// 服务发现与负载均衡
type ServiceRegistry struct {
    services map[string][]ServiceInstance
    mu       sync.RWMutex
}

type ServiceInstance struct {
    ID       string
    Address  string
    Port     int
    Health   string
    LastSeen time.Time
}

func (sr *ServiceRegistry) RegisterService(serviceName string, instance ServiceInstance) {
    sr.mu.Lock()
    defer sr.mu.Unlock()
    
    if sr.services[serviceName] == nil {
        sr.services[serviceName] = make([]ServiceInstance, 0)
    }
    
    sr.services[serviceName] = append(sr.services[serviceName], instance)
}

func (sr *ServiceRegistry) GetHealthyInstances(serviceName string) []ServiceInstance {
    sr.mu.RLock()
    defer sr.mu.RUnlock()
    
    instances := sr.services[serviceName]
    healthy := make([]ServiceInstance, 0)
    
    for _, instance := range instances {
        if instance.Health == "UP" && time.Since(instance.LastSeen) < 30*time.Second {
            healthy = append(healthy, instance)
        }
    }
    
    return healthy
}
```

### 5. 实时流处理架构

#### 5.1 Kafka Streams实现
```go
// 实时数据处理管道
type StreamProcessor struct {
    consumer *kafka.Reader
    producer *kafka.Writer
    windows  map[string]*TimeWindow
    mu       sync.RWMutex
}

type TimeWindow struct {
    StartTime time.Time
    EndTime   time.Time
    Data      map[string]interface{}
}

// 实时用户行为分析
func (sp *StreamProcessor) ProcessUserBehavior() {
    for {
        msg, err := sp.consumer.ReadMessage(context.Background())
        if err != nil {
            continue
        }
        
        var event UserBehaviorEvent
        if err := json.Unmarshal(msg.Value, &event); err != nil {
            continue
        }
        
        // 滑动窗口聚合
        sp.aggregateInWindow(event)
        
        // 实时异常检测
        if sp.detectAnomaly(event) {
            sp.publishAlert(event)
        }
    }
}

func (sp *StreamProcessor) aggregateInWindow(event UserBehaviorEvent) {
    windowKey := fmt.Sprintf("%s_%d", event.UserID, event.Timestamp.Unix()/300) // 5分钟窗口
    
    sp.mu.Lock()
    defer sp.mu.Unlock()
    
    window, exists := sp.windows[windowKey]
    if !exists {
        window = &TimeWindow{
            StartTime: time.Unix(event.Timestamp.Unix()/300*300, 0),
            EndTime:   time.Unix(event.Timestamp.Unix()/300*300+300, 0),
            Data:      make(map[string]interface{}),
        }
        sp.windows[windowKey] = window
    }
    
    // 聚合计算
    if count, ok := window.Data["click_count"].(int); ok {
        window.Data["click_count"] = count + 1
    } else {
        window.Data["click_count"] = 1
    }
    
    // 窗口关闭时输出结果
    if time.Now().After(window.EndTime) {
        sp.outputWindowResult(windowKey, window)
        delete(sp.windows, windowKey)
    }
}

func (sp *StreamProcessor) detectAnomaly(event UserBehaviorEvent) bool {
    // 简单异常检测：5分钟内点击超过100次
    windowKey := fmt.Sprintf("%s_%d", event.UserID, event.Timestamp.Unix()/300)
    
    sp.mu.RLock()
    window, exists := sp.windows[windowKey]
    sp.mu.RUnlock()
    
    if exists {
        if count, ok := window.Data["click_count"].(int); ok && count > 100 {
            return true
        }
    }
    
    return false
}
```

---

## 生产环境最佳实践

### 1. 配置模板

#### 1.1 高吞吐量场景配置
```yaml
# producer.yml - 高吞吐量生产者配置
kafka:
  producer:
    bootstrap.servers: "kafka-cluster:9092"
    acks: "1"                    # 平衡可靠性与性能
    retries: 3
    batch.size: 65536            # 64KB批次大小
    linger.ms: 20                # 20ms延迟发送
    buffer.memory: 134217728     # 128MB缓冲区
    compression.type: "lz4"      # LZ4压缩，CPU开销小
    max.in.flight.requests.per.connection: 5
    enable.idempotence: true
    
  consumer:
    bootstrap.servers: "kafka-cluster:9092"
    group.id: "high-throughput-group"
    auto.offset.reset: "latest"
    enable.auto.commit: false    # 手动提交提升性能
    max.poll.records: 1000       # 单次拉取1000条消息
    fetch.min.bytes: 50000       # 最小拉取50KB
    fetch.max.wait.ms: 500       # 最大等待500ms
    session.timeout.ms: 30000
    heartbeat.interval.ms: 10000
```

#### 1.2 低延迟场景配置
```yaml
# producer.yml - 低延迟生产者配置
kafka:
  producer:
    bootstrap.servers: "kafka-cluster:9092"
    acks: "1"
    retries: 0                   # 禁用重试减少延迟
    batch.size: 1024             # 小批次
    linger.ms: 0                 # 立即发送
    buffer.memory: 33554432      # 32MB缓冲区
    compression.type: "none"     # 无压缩
    max.in.flight.requests.per.connection: 1
    
  consumer:
    bootstrap.servers: "kafka-cluster:9092"
    group.id: "low-latency-group"
    auto.offset.reset: "latest"
    enable.auto.commit: true
    auto.commit.interval.ms: 1000
    max.poll.records: 100        # 小批次消费
    fetch.min.bytes: 1           # 立即返回
    fetch.max.wait.ms: 10        # 最大等待10ms
    session.timeout.ms: 10000
    heartbeat.interval.ms: 3000
```

#### 1.3 高可靠性场景配置
```yaml
# producer.yml - 高可靠性生产者配置
kafka:
  producer:
    bootstrap.servers: "kafka-cluster:9092"
    acks: "all"                  # 等待所有副本确认
    retries: 2147483647          # 最大重试次数
    retry.backoff.ms: 1000
    batch.size: 16384
    linger.ms: 100
    buffer.memory: 67108864      # 64MB缓冲区
    compression.type: "gzip"     # GZIP压缩节省存储
    max.in.flight.requests.per.connection: 1  # 保证顺序
    enable.idempotence: true
    transactional.id: "tx-producer-1"  # 事务支持
    
  consumer:
    bootstrap.servers: "kafka-cluster:9092"
    group.id: "reliable-group"
    auto.offset.reset: "earliest"
    enable.auto.commit: false    # 手动提交保证可靠性
    isolation.level: "read_committed"  # 只读已提交事务
    max.poll.records: 100
    session.timeout.ms: 45000
    heartbeat.interval.ms: 15000
    request.timeout.ms: 60000
```

### 2. 监控指标配置

#### 2.1 Prometheus监控规则
```yaml
# kafka-alerts.yml
groups:
- name: kafka.application.rules
  rules:
  # 消息积压告警
  - alert: KafkaConsumerLag
    expr: kafka_consumer_lag_sum > 10000
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Kafka consumer lag is high"
      description: "Consumer group {{ $labels.group }} has lag {{ $value }} on topic {{ $labels.topic }}"
      
  # 生产者错误率告警
  - alert: KafkaProducerErrorRate
    expr: rate(kafka_producer_record_error_total[5m]) > 0.01
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "Kafka producer error rate is high"
      description: "Producer error rate is {{ $value }} errors/sec"
      
  # 消费者重平衡频繁告警
  - alert: KafkaFrequentRebalance
    expr: rate(kafka_consumer_rebalance_total[10m]) > 0.1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Kafka consumer rebalancing frequently"
      description: "Consumer group {{ $labels.group }} is rebalancing {{ $value }} times per minute"
      
  # 事务失败告警
  - alert: KafkaTransactionFailure
    expr: rate(kafka_producer_transaction_aborted_total[5m]) > 0.05
    for: 3m
    labels:
      severity: critical
    annotations:
      summary: "Kafka transaction failure rate is high"
      description: "Transaction abort rate is {{ $value }} per second"
      
  # 连接数告警
  - alert: KafkaConnectionCount
    expr: kafka_server_socket_server_metrics_connection_count > 1000
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Kafka connection count is high"
      description: "Broker has {{ $value }} active connections"
```

#### 2.2 应用层监控指标
```go
// 应用监控指标收集器
type ApplicationMetrics struct {
    // 业务指标
    OrderProcessedTotal   prometheus.Counter
    OrderProcessingTime   prometheus.Histogram
    PaymentSuccessRate    prometheus.Gauge
    InventoryUpdateLag    prometheus.Gauge
    
    // 技术指标
    MessageProcessingTime prometheus.Histogram
    DeadLetterQueueSize   prometheus.Gauge
    CircuitBreakerState   prometheus.Gauge
    RetryAttempts         prometheus.Counter
}

func NewApplicationMetrics() *ApplicationMetrics {
    return &ApplicationMetrics{
        OrderProcessedTotal: prometheus.NewCounter(prometheus.CounterOpts{
            Name: "orders_processed_total",
            Help: "Total number of orders processed",
        }),
        OrderProcessingTime: prometheus.NewHistogram(prometheus.HistogramOpts{
            Name:    "order_processing_duration_seconds",
            Help:    "Time spent processing orders",
            Buckets: prometheus.DefBuckets,
        }),
        PaymentSuccessRate: prometheus.NewGauge(prometheus.GaugeOpts{
            Name: "payment_success_rate",
            Help: "Payment success rate in last 5 minutes",
        }),
        MessageProcessingTime: prometheus.NewHistogram(prometheus.HistogramOpts{
            Name:    "kafka_message_processing_duration_seconds",
            Help:    "Time spent processing Kafka messages",
            Buckets: []float64{0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0},
        }),
        DeadLetterQueueSize: prometheus.NewGauge(prometheus.GaugeOpts{
            Name: "dead_letter_queue_size",
            Help: "Number of messages in dead letter queue",
        }),
    }
}

// 监控中间件
func (am *ApplicationMetrics) MonitorMessageProcessing(handler MessageHandler) MessageHandler {
    return func(message []byte) error {
        start := time.Now()
        defer func() {
            am.MessageProcessingTime.Observe(time.Since(start).Seconds())
        }()
        
        err := handler(message)
        if err != nil {
            am.RetryAttempts.Inc()
        }
        
        return err
    }
}
```

### 3. 部署与运维最佳实践

#### 3.1 容器化部署配置
```yaml
# docker-compose.yml
version: '3.8'
services:
  order-service:
    image: order-service:latest
    environment:
      - KAFKA_BROKERS=kafka-cluster:9092
      - DB_HOST=postgres:5432
      - REDIS_HOST=redis:6379
    deploy:
      replicas: 3
      resources:
        limits:
          memory: 1G
          cpus: '0.5'
        reservations:
          memory: 512M
          cpus: '0.25'
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - kafka-network
      
  inventory-service:
    image: inventory-service:latest
    environment:
      - KAFKA_BROKERS=kafka-cluster:9092
      - DB_HOST=postgres:5432
    deploy:
      replicas: 2
      resources:
        limits:
          memory: 512M
          cpus: '0.3'
    networks:
      - kafka-network
      
networks:
  kafka-network:
    driver: overlay
    attachable: true
```

#### 3.2 Kubernetes部署配置
```yaml
# k8s-deployment.yml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: order-service
  labels:
    app: order-service
spec:
  replicas: 3
  selector:
    matchLabels:
      app: order-service
  template:
    metadata:
      labels:
        app: order-service
    spec:
      containers:
      - name: order-service
        image: order-service:v1.2.0
        ports:
        - containerPort: 8080
        env:
        - name: KAFKA_BROKERS
          value: "kafka-cluster:9092"
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: db-secret
              key: password
        resources:
          requests:
            memory: "256Mi"
            cpu: "200m"
          limits:
            memory: "512Mi"
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
  name: order-service
spec:
  selector:
    app: order-service
  ports:
  - port: 80
    targetPort: 8080
  type: ClusterIP
```

#### 3.3 运维脚本
```bash
#!/bin/bash
# kafka-ops.sh - Kafka运维脚本

# 检查消费者组状态
check_consumer_groups() {
    echo "=== Consumer Groups Status ==="
    kafka-consumer-groups.sh --bootstrap-server localhost:9092 --list | while read group; do
        echo "Group: $group"
        kafka-consumer-groups.sh --bootstrap-server localhost:9092 --group $group --describe
        echo "---"
    done
}

# 重置消费者组偏移量
reset_consumer_offset() {
    local group=$1
    local topic=$2
    local offset=$3
    
    echo "Resetting offset for group $group on topic $topic to $offset"
    kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
        --group $group --topic $topic --reset-offsets --to-offset $offset --execute
}

# 监控Topic大小
monitor_topic_size() {
    echo "=== Topic Sizes ==="
    kafka-log-dirs.sh --bootstrap-server localhost:9092 --describe --json | \
    jq -r '.brokers[].logDirs[].partitions[] | "\(.topic)-\(.partition): \(.size) bytes"' | \
    sort
}

# 清理过期日志
cleanup_logs() {
    local retention_days=$1
    echo "Cleaning up logs older than $retention_days days"
    
    find /var/kafka-logs -name "*.log" -mtime +$retention_days -delete
    find /var/kafka-logs -name "*.index" -mtime +$retention_days -delete
    find /var/kafka-logs -name "*.timeindex" -mtime +$retention_days -delete
}

# 主函数
case "$1" in
    "check-groups")
        check_consumer_groups
        ;;
    "reset-offset")
        reset_consumer_offset $2 $3 $4
        ;;
    "monitor-size")
        monitor_topic_size
        ;;
    "cleanup")
        cleanup_logs ${2:-7}
        ;;
    *)
        echo "Usage: $0 {check-groups|reset-offset|monitor-size|cleanup}"
        echo "  check-groups: Check all consumer group status"
        echo "  reset-offset <group> <topic> <offset>: Reset consumer group offset"
        echo "  monitor-size: Monitor topic sizes"
        echo "  cleanup [days]: Cleanup logs older than specified days (default: 7)"
        exit 1
        ;;
esac
```
