# MySQL生产实战 - 深度优化专家指南

## 目录
1. [慢查询优化实战](#1-慢查询优化实战)
2. [主从同步深度配置](#2-主从同步深度配置)
3. [分库分表中间件实现](#3-分库分表中间件实现)
4. [备份恢复自动化运维](#4-备份恢复自动化运维)

---

## 1. 慢查询优化实战

### 1.1 EXPLAIN执行计划深度分析

#### 核心字段解读与优化策略

**id字段分析**：
```sql
-- 复杂查询示例
EXPLAIN SELECT u.name, o.total, p.title 
FROM users u 
JOIN orders o ON u.id = o.user_id 
JOIN order_items oi ON o.id = oi.order_id
JOIN products p ON oi.product_id = p.id
WHERE u.created_at > '2024-01-01' 
AND o.status = 'completed';
```

**执行计划优化对照表**：
| 字段 | 优化目标 | 问题识别 | 解决方案 |
|------|----------|----------|----------|
| `type` | const > eq_ref > ref > range > index > ALL | ALL/index扫描 | 添加合适索引 |
| `key` | 使用预期索引 | NULL或错误索引 | 强制索引或重建索引 |
| `rows` | 扫描行数最小化 | 大量行扫描 | 优化WHERE条件 |
| `Extra` | 避免Using filesort/temporary | 文件排序/临时表 | 调整ORDER BY/GROUP BY |

#### 生产环境慢查询分析工具

**Go语言实现的EXPLAIN分析器**：
```go
package main

import (
    "database/sql"
    "encoding/json"
    "fmt"
    "log"
    "strings"
    "time"
    
    _ "github.com/go-sql-driver/mysql"
)

type ExplainResult struct {
    ID           int     `json:"id"`
    SelectType   string  `json:"select_type"`
    Table        string  `json:"table"`
    Type         string  `json:"type"`
    PossibleKeys *string `json:"possible_keys"`
    Key          *string `json:"key"`
    KeyLen       *string `json:"key_len"`
    Ref          *string `json:"ref"`
    Rows         int     `json:"rows"`
    Extra        *string `json:"extra"`
    Score        int     `json:"performance_score"`
}

type QueryAnalyzer struct {
    db *sql.DB
}

func NewQueryAnalyzer(dsn string) (*QueryAnalyzer, error) {
    db, err := sql.Open("mysql", dsn)
    if err != nil {
        return nil, err
    }
    return &QueryAnalyzer{db: db}, nil
}

// 分析查询性能并给出优化建议
func (qa *QueryAnalyzer) AnalyzeQuery(query string) (*QueryAnalysis, error) {
    // 1. 执行EXPLAIN
    explainSQL := "EXPLAIN FORMAT=JSON " + query
    var jsonResult string
    err := qa.db.QueryRow(explainSQL).Scan(&jsonResult)
    if err != nil {
        return nil, fmt.Errorf("explain failed: %w", err)
    }
    
    // 2. 解析JSON结果
    var explainData map[string]interface{}
    if err := json.Unmarshal([]byte(jsonResult), &explainData); err != nil {
        return nil, err
    }
    
    // 3. 性能评分
    analysis := &QueryAnalysis{
        Query:        query,
        ExplainData:  explainData,
        Timestamp:    time.Now(),
    }
    
    analysis.Score = qa.calculatePerformanceScore(explainData)
    analysis.Suggestions = qa.generateOptimizationSuggestions(explainData)
    
    return analysis, nil
}

type QueryAnalysis struct {
    Query        string                 `json:"query"`
    ExplainData  map[string]interface{} `json:"explain_data"`
    Score        int                    `json:"score"`
    Suggestions  []string               `json:"suggestions"`
    Timestamp    time.Time              `json:"timestamp"`
}

// 性能评分算法（0-100分）
func (qa *QueryAnalyzer) calculatePerformanceScore(explainData map[string]interface{}) int {
    score := 100
    
    queryBlock := explainData["query_block"].(map[string]interface{})
    
    // 检查表扫描类型
    if table, ok := queryBlock["table"]; ok {
        tableInfo := table.(map[string]interface{})
        accessType := tableInfo["access_type"].(string)
        
        switch accessType {
        case "ALL":
            score -= 50 // 全表扫描严重扣分
        case "index":
            score -= 30 // 索引扫描扣分
        case "range":
            score -= 10 // 范围扫描轻微扣分
        case "ref", "eq_ref", "const":
            // 理想的访问类型，不扣分
        }
        
        // 检查扫描行数
        if rows, ok := tableInfo["rows_examined_per_scan"]; ok {
            rowCount := int(rows.(float64))
            if rowCount > 10000 {
                score -= 30
            } else if rowCount > 1000 {
                score -= 15
            }
        }
        
        // 检查是否使用了文件排序
        if usingFilesort := strings.Contains(fmt.Sprintf("%v", tableInfo), "filesort"); usingFilesort {
            score -= 20
        }
        
        // 检查是否使用了临时表
        if usingTempTable := strings.Contains(fmt.Sprintf("%v", tableInfo), "temporary"); usingTempTable {
            score -= 25
        }
    }
    
    if score < 0 {
        score = 0
    }
    
    return score
}

// 生成优化建议
func (qa *QueryAnalyzer) generateOptimizationSuggestions(explainData map[string]interface{}) []string {
    var suggestions []string
    
    queryBlock := explainData["query_block"].(map[string]interface{})
    
    if table, ok := queryBlock["table"]; ok {
        tableInfo := table.(map[string]interface{})
        accessType := tableInfo["access_type"].(string)
        
        switch accessType {
        case "ALL":
            suggestions = append(suggestions, "❌ 发现全表扫描，建议添加WHERE条件对应的索引")
            suggestions = append(suggestions, "💡 分析查询条件，创建复合索引优化查询")
        case "index":
            suggestions = append(suggestions, "⚠️ 使用了索引扫描，考虑优化WHERE条件")
        }
        
        // 检查JOIN优化
        if joinTables, ok := queryBlock["nested_loop"]; ok {
            suggestions = append(suggestions, "🔗 检测到JOIN操作，确保关联字段都有索引")
            suggestions = append(suggestions, "📊 考虑调整JOIN顺序，小表驱动大表")
            
            // 分析JOIN类型
            joinInfo := joinTables.([]interface{})
            for _, join := range joinInfo {
                if joinMap, ok := join.(map[string]interface{}); ok {
                    if table, ok := joinMap["table"]; ok {
                        tableData := table.(map[string]interface{})
                        if accessType, ok := tableData["access_type"]; ok && accessType == "ALL" {
                            tableName := tableData["table_name"].(string)
                            suggestions = append(suggestions, 
                                fmt.Sprintf("🚨 表 %s 在JOIN中使用全表扫描，急需优化", tableName))
                        }
                    }
                }
            }
        }
        
        // 检查排序优化
        if strings.Contains(fmt.Sprintf("%v", tableInfo), "filesort") {
            suggestions = append(suggestions, "📈 使用了文件排序，考虑创建ORDER BY字段的索引")
            suggestions = append(suggestions, "🎯 如果是复合排序，创建多字段复合索引")
        }
        
        // 检查临时表
        if strings.Contains(fmt.Sprintf("%v", tableInfo), "temporary") {
            suggestions = append(suggestions, "💾 使用了临时表，检查GROUP BY和DISTINCT操作")
            suggestions = append(suggestions, "⚡ 考虑重写查询逻辑避免临时表")
        }
    }
    
    return suggestions
}

// 慢查询监控和自动分析
func (qa *QueryAnalyzer) MonitorSlowQueries() {
    ticker := time.NewTicker(30 * time.Second)
    defer ticker.Stop()
    
    for range ticker.C {
        slowQueries, err := qa.getSlowQueries()
        if err != nil {
            log.Printf("获取慢查询失败: %v", err)
            continue
        }
        
        for _, query := range slowQueries {
            if analysis, err := qa.AnalyzeQuery(query.SQL); err == nil {
                if analysis.Score < 60 {
                    qa.alertSlowQuery(query, analysis)
                }
            }
        }
    }
}

type SlowQuery struct {
    SQL           string        `json:"sql"`
    QueryTime     time.Duration `json:"query_time"`
    LockTime      time.Duration `json:"lock_time"`
    RowsSent      int           `json:"rows_sent"`
    RowsExamined  int           `json:"rows_examined"`
    Timestamp     time.Time     `json:"timestamp"`
}

func (qa *QueryAnalyzer) getSlowQueries() ([]SlowQuery, error) {
    // 从performance_schema获取慢查询
    query := `
        SELECT sql_text, timer_wait/1000000000 as query_time_ms,
               lock_time/1000000000 as lock_time_ms,
               rows_sent, rows_examined
        FROM performance_schema.events_statements_history_long 
        WHERE timer_wait > 1000000000  -- 超过1秒的查询
        ORDER BY timer_wait DESC 
        LIMIT 10
    `
    
    rows, err := qa.db.Query(query)
    if err != nil {
        return nil, err
    }
    defer rows.Close()
    
    var slowQueries []SlowQuery
    for rows.Next() {
        var sq SlowQuery
        var queryTimeMs, lockTimeMs float64
        
        err := rows.Scan(&sq.SQL, &queryTimeMs, &lockTimeMs, 
                        &sq.RowsSent, &sq.RowsExamined)
        if err != nil {
            continue
        }
        
        sq.QueryTime = time.Duration(queryTimeMs) * time.Millisecond
        sq.LockTime = time.Duration(lockTimeMs) * time.Millisecond
        sq.Timestamp = time.Now()
        
        slowQueries = append(slowQueries, sq)
    }
    
    return slowQueries, nil
}

func (qa *QueryAnalyzer) alertSlowQuery(query SlowQuery, analysis *QueryAnalysis) {
    alert := map[string]interface{}{
        "type":        "slow_query_alert",
        "query":       query.SQL,
        "query_time":  query.QueryTime.String(),
        "score":       analysis.Score,
        "suggestions": analysis.Suggestions,
        "timestamp":   time.Now(),
    }
    
    // 发送到监控系统（如Prometheus AlertManager）
    alertJSON, _ := json.MarshalIndent(alert, "", "  ")
    log.Printf("🚨 慢查询告警:\n%s", string(alertJSON))
    
    // 这里可以集成钉钉、微信等告警通道
    // qa.sendDingTalkAlert(alert)
}
```

### 1.2 索引设计最佳实践

#### 复合索引设计原则

**最左前缀匹配原则实战**：
```sql
-- 用户订单查询场景
CREATE TABLE orders (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    status TINYINT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    total_amount DECIMAL(10,2) NOT NULL,
    
    -- 复合索引设计（按查询频率和选择性排序）
    INDEX idx_user_status_time (user_id, status, created_at),
    INDEX idx_status_time (status, created_at),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB;

-- 索引使用效果对比
-- ✅ 能使用idx_user_status_time索引
SELECT * FROM orders WHERE user_id = 123 AND status = 1;
SELECT * FROM orders WHERE user_id = 123 AND status = 1 AND created_at > '2024-01-01';

-- ❌ 不能使用idx_user_status_time索引（跳过了user_id）
SELECT * FROM orders WHERE status = 1 AND created_at > '2024-01-01';
-- 这种情况会使用idx_status_time索引
```

#### 索引优化工具实现

**Go语言索引分析器**：
```go
type IndexAnalyzer struct {
    db *sql.DB
}

type IndexUsage struct {
    TableName    string  `json:"table_name"`
    IndexName    string  `json:"index_name"`
    Cardinality  int64   `json:"cardinality"`
    UsageCount   int64   `json:"usage_count"`
    LastUsed     *time.Time `json:"last_used"`
    Selectivity  float64 `json:"selectivity"`
    Redundant    bool    `json:"redundant"`
}

// 分析索引使用情况
func (ia *IndexAnalyzer) AnalyzeIndexUsage(tableName string) ([]IndexUsage, error) {
    query := `
        SELECT 
            s.table_name,
            s.index_name,
            s.cardinality,
            IFNULL(u.count_read, 0) as usage_count,
            u.last_read
        FROM information_schema.statistics s
        LEFT JOIN performance_schema.table_io_waits_summary_by_index_usage u 
            ON s.table_schema = u.object_schema 
            AND s.table_name = u.object_name 
            AND s.index_name = u.index_name
        WHERE s.table_schema = DATABASE()
        AND s.table_name = ?
        AND s.seq_in_index = 1  -- 只看复合索引的第一列
        ORDER BY s.table_name, s.index_name
    `
    
    rows, err := ia.db.Query(query, tableName)
    if err != nil {
        return nil, err
    }
    defer rows.Close()
    
    var indexes []IndexUsage
    for rows.Next() {
        var idx IndexUsage
        var lastUsed sql.NullTime
        
        err := rows.Scan(&idx.TableName, &idx.IndexName, &idx.Cardinality,
                        &idx.UsageCount, &lastUsed)
        if err != nil {
            continue
        }
        
        if lastUsed.Valid {
            idx.LastUsed = &lastUsed.Time
        }
        
        // 计算选择性
        idx.Selectivity = ia.calculateSelectivity(tableName, idx.IndexName)
        
        // 检查是否冗余
        idx.Redundant = ia.isRedundantIndex(tableName, idx.IndexName)
        
        indexes = append(indexes, idx)
    }
    
    return indexes, nil
}

// 计算索引选择性
func (ia *IndexAnalyzer) calculateSelectivity(tableName, indexName string) float64 {
    // 获取表总行数
    var totalRows int64
    ia.db.QueryRow("SELECT COUNT(*) FROM "+tableName).Scan(&totalRows)
    
    if totalRows == 0 {
        return 0
    }
    
    // 获取索引列信息
    columns := ia.getIndexColumns(tableName, indexName)
    if len(columns) == 0 {
        return 0
    }
    
    // 计算第一列的唯一值数量
    var distinctCount int64
    query := fmt.Sprintf("SELECT COUNT(DISTINCT %s) FROM %s", columns[0], tableName)
    ia.db.QueryRow(query).Scan(&distinctCount)
    
    return float64(distinctCount) / float64(totalRows)
}

// 获取索引包含的列
func (ia *IndexAnalyzer) getIndexColumns(tableName, indexName string) []string {
    query := `
        SELECT column_name 
        FROM information_schema.statistics 
        WHERE table_schema = DATABASE() 
        AND table_name = ? 
        AND index_name = ?
        ORDER BY seq_in_index
    `
    
    rows, err := ia.db.Query(query, tableName, indexName)
    if err != nil {
        return nil
    }
    defer rows.Close()
    
    var columns []string
    for rows.Next() {
        var column string
        if rows.Scan(&column) == nil {
            columns = append(columns, column)
        }
    }
    
    return columns
}

// 检查冗余索引
func (ia *IndexAnalyzer) isRedundantIndex(tableName, indexName string) bool {
    currentColumns := ia.getIndexColumns(tableName, indexName)
    if len(currentColumns) == 0 {
        return false
    }
    
    // 获取表上所有索引
    allIndexes := ia.getAllIndexes(tableName)
    
    for _, otherIndex := range allIndexes {
        if otherIndex == indexName {
            continue
        }
        
        otherColumns := ia.getIndexColumns(tableName, otherIndex)
        
        // 检查当前索引是否是其他索引的前缀
        if ia.isPrefix(currentColumns, otherColumns) {
            return true
        }
    }
    
    return false
}

func (ia *IndexAnalyzer) isPrefix(prefix, full []string) bool {
    if len(prefix) >= len(full) {
        return false
    }
    
    for i, col := range prefix {
        if i >= len(full) || col != full[i] {
            return false
        }
    }
    
    return true
}

func (ia *IndexAnalyzer) getAllIndexes(tableName string) []string {
    query := `
        SELECT DISTINCT index_name 
        FROM information_schema.statistics 
        WHERE table_schema = DATABASE() 
        AND table_name = ?
        AND index_name != 'PRIMARY'
    `
    
    rows, err := ia.db.Query(query, tableName)
    if err != nil {
        return nil
    }
    defer rows.Close()
    
    var indexes []string
    for rows.Next() {
        var indexName string
        if rows.Scan(&indexName) == nil {
            indexes = append(indexes, indexName)
        }
    }
    
    return indexes
}

// 生成索引优化建议
func (ia *IndexAnalyzer) GenerateIndexOptimizationReport(tableName string) (*IndexOptimizationReport, error) {
    indexes, err := ia.AnalyzeIndexUsage(tableName)
    if err != nil {
        return nil, err
    }
    
    report := &IndexOptimizationReport{
        TableName: tableName,
        Timestamp: time.Now(),
    }
    
    for _, idx := range indexes {
        if idx.UsageCount == 0 && idx.LastUsed == nil {
            report.UnusedIndexes = append(report.UnusedIndexes, idx.IndexName)
        }
        
        if idx.Redundant {
            report.RedundantIndexes = append(report.RedundantIndexes, idx.IndexName)
        }
        
        if idx.Selectivity < 0.01 { // 选择性低于1%
            report.LowSelectivityIndexes = append(report.LowSelectivityIndexes, 
                fmt.Sprintf("%s (选择性: %.2f%%)", idx.IndexName, idx.Selectivity*100))
        }
    }
    
    // 生成优化建议
    report.Recommendations = ia.generateRecommendations(report)
    
    return report, nil
}

type IndexOptimizationReport struct {
    TableName              string    `json:"table_name"`
    UnusedIndexes          []string  `json:"unused_indexes"`
    RedundantIndexes       []string  `json:"redundant_indexes"`
    LowSelectivityIndexes  []string  `json:"low_selectivity_indexes"`
    Recommendations        []string  `json:"recommendations"`
    Timestamp              time.Time `json:"timestamp"`
}

func (ia *IndexAnalyzer) generateRecommendations(report *IndexOptimizationReport) []string {
    var recommendations []string
    
    if len(report.UnusedIndexes) > 0 {
        recommendations = append(recommendations, 
            fmt.Sprintf("🗑️ 发现 %d 个未使用的索引，建议删除以节省存储空间和提升写入性能", 
                       len(report.UnusedIndexes)))
        for _, idx := range report.UnusedIndexes {
            recommendations = append(recommendations, 
                fmt.Sprintf("   DROP INDEX %s ON %s;", idx, report.TableName))
        }
    }
    
    if len(report.RedundantIndexes) > 0 {
        recommendations = append(recommendations, 
            fmt.Sprintf("🔄 发现 %d 个冗余索引，建议删除重复的索引", 
                       len(report.RedundantIndexes)))
    }
    
    if len(report.LowSelectivityIndexes) > 0 {
        recommendations = append(recommendations, 
            "📊 发现低选择性索引，考虑重新设计或删除")
    }
    
    return recommendations
}
```

---

## 2. 主从同步深度配置

### 2.1 生产级主从复制配置

#### 主库配置（my.cnf）
```ini
[mysqld]
# 基础配置
server-id = 1
log-bin = mysql-bin
binlog-format = ROW
binlog-do-db = production_db

# 性能优化
sync_binlog = 1
innodb_flush_log_at_trx_commit = 1

# 主从同步优化
max_binlog_size = 1G
binlog_cache_size = 32M
binlog_stmt_cache_size = 32M

# 半同步复制（推荐生产环境）
plugin-load = "rpl_semi_sync_master=semisync_master.so"
rpl_semi_sync_master_enabled = 1
rpl_semi_sync_master_timeout = 1000  # 1秒超时
rpl_semi_sync_master_wait_for_slave_count = 1

# GTID模式（推荐）
gtid_mode = ON
enforce_gtid_consistency = ON
log_slave_updates = ON
```

#### 从库配置（my.cnf）
```ini
[mysqld]
# 基础配置
server-id = 2
log-bin = mysql-bin
binlog-format = ROW
read_only = 1
super_read_only = 1

# 中继日志配置
relay-log = relay-bin
relay_log_purge = 1
relay_log_recovery = 1

# 半同步复制
plugin-load = "rpl_semi_sync_slave=semisync_slave.so"
rpl_semi_sync_slave_enabled = 1

# GTID模式
gtid_mode = ON
enforce_gtid_consistency = ON
log_slave_updates = ON

# 并行复制优化
slave_parallel_type = LOGICAL_CLOCK
slave_parallel_workers = 4
slave_preserve_commit_order = 1

# 复制过滤（可选）
replicate-do-db = production_db
```

### 2.2 延迟监控与自动化处理

#### Go语言实现的主从延迟监控系统

```go
package main

import (
    "context"
    "database/sql"
    "encoding/json"
    "fmt"
    "log"
    "sync"
    "time"
    
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
    _ "github.com/go-sql-driver/mysql"
)

// 主从延迟监控器
type ReplicationMonitor struct {
    masterDB    *sql.DB
    slaveDBs    []*sql.DB
    config      *MonitorConfig
    metrics     *ReplicationMetrics
    alertChan   chan *ReplicationAlert
    mu          sync.RWMutex
}

type MonitorConfig struct {
    CheckInterval     time.Duration `json:"check_interval"`
    MaxLagThreshold   time.Duration `json:"max_lag_threshold"`
    CriticalThreshold time.Duration `json:"critical_threshold"`
    AlertWebhook      string        `json:"alert_webhook"`
    AutoFailover      bool          `json:"auto_failover"`
}

type ReplicationMetrics struct {
    LagSeconds     prometheus.Gauge
    SlaveIORunning prometheus.Gauge
    SlaveSQLRunning prometheus.Gauge
    MasterLogPos   prometheus.Gauge
    SlaveLogPos    prometheus.Gauge
}

type ReplicationStatus struct {
    SlaveIOState       string        `json:"slave_io_state"`
    MasterLogFile      string        `json:"master_log_file"`
    ReadMasterLogPos   int64         `json:"read_master_log_pos"`
    RelayLogFile       string        `json:"relay_log_file"`
    RelayLogPos        int64         `json:"relay_log_pos"`
    RelayMasterLogFile string        `json:"relay_master_log_file"`
    SlaveIORunning     string        `json:"slave_io_running"`
    SlaveSQLRunning    string        `json:"slave_sql_running"`
    SecondsBehindMaster *int64       `json:"seconds_behind_master"`
    LastIOError        string        `json:"last_io_error"`
    LastSQLError       string        `json:"last_sql_error"`
    GTIDSet            string        `json:"executed_gtid_set"`
    AutoPosition       bool          `json:"auto_position"`
    Timestamp          time.Time     `json:"timestamp"`
}

type ReplicationAlert struct {
    Type        string            `json:"type"`
    Severity    string            `json:"severity"`
    Message     string            `json:"message"`
    SlaveHost   string            `json:"slave_host"`
    LagSeconds  *int64            `json:"lag_seconds,omitempty"`
    Details     map[string]interface{} `json:"details"`
    Timestamp   time.Time         `json:"timestamp"`
}

func NewReplicationMonitor(masterDSN string, slaveDSNs []string, config *MonitorConfig) (*ReplicationMonitor, error) {
    // 连接主库
    masterDB, err := sql.Open("mysql", masterDSN)
    if err != nil {
        return nil, fmt.Errorf("连接主库失败: %w", err)
    }
    
    // 连接从库
    var slaveDBs []*sql.DB
    for _, dsn := range slaveDSNs {
        slaveDB, err := sql.Open("mysql", dsn)
        if err != nil {
            return nil, fmt.Errorf("连接从库失败: %w", err)
        }
        slaveDBs = append(slaveDBs, slaveDB)
    }
    
    // 初始化Prometheus指标
    metrics := &ReplicationMetrics{
        LagSeconds: promauto.NewGauge(prometheus.GaugeOpts{
            Name: "mysql_replication_lag_seconds",
            Help: "MySQL主从复制延迟秒数",
        }),
        SlaveIORunning: promauto.NewGauge(prometheus.GaugeOpts{
            Name: "mysql_slave_io_running",
            Help: "MySQL从库IO线程运行状态",
        }),
        SlaveSQLRunning: promauto.NewGauge(prometheus.GaugeOpts{
            Name: "mysql_slave_sql_running",
            Help: "MySQL从库SQL线程运行状态",
        }),
    }
    
    return &ReplicationMonitor{
        masterDB:  masterDB,
        slaveDBs:  slaveDBs,
        config:    config,
        metrics:   metrics,
        alertChan: make(chan *ReplicationAlert, 100),
    }, nil
}

// 启动监控
func (rm *ReplicationMonitor) Start(ctx context.Context) {
    // 启动告警处理协程
    go rm.handleAlerts(ctx)
    
    ticker := time.NewTicker(rm.config.CheckInterval)
    defer ticker.Stop()
    
    for {
        select {
        case <-ctx.Done():
            return
        case <-ticker.C:
            rm.checkReplicationStatus()
        }
    }
}

// 检查复制状态
func (rm *ReplicationMonitor) checkReplicationStatus() {
    for i, slaveDB := range rm.slaveDBs {
        status, err := rm.getSlaveStatus(slaveDB)
        if err != nil {
            log.Printf("获取从库%d状态失败: %v", i, err)
            continue
        }
        
        rm.updateMetrics(status)
        rm.checkForAlerts(status, fmt.Sprintf("slave-%d", i))
    }
}

// 获取从库状态
func (rm *ReplicationMonitor) getSlaveStatus(db *sql.DB) (*ReplicationStatus, error) {
    query := "SHOW SLAVE STATUS"
    rows, err := db.Query(query)
    if err != nil {
        return nil, err
    }
    defer rows.Close()
    
    if !rows.Next() {
        return nil, fmt.Errorf("未找到从库状态信息")
    }
    
    // 获取列名
    columns, err := rows.Columns()
    if err != nil {
        return nil, err
    }
    
    // 创建扫描目标
    values := make([]interface{}, len(columns))
    valuePtrs := make([]interface{}, len(columns))
    for i := range values {
        valuePtrs[i] = &values[i]
    }
    
    // 扫描数据
    if err := rows.Scan(valuePtrs...); err != nil {
        return nil, err
    }
    
    // 解析结果
    status := &ReplicationStatus{
        Timestamp: time.Now(),
    }
    
    for i, col := range columns {
        val := values[i]
        if val == nil {
            continue
        }
        
        switch col {
        case "Slave_IO_State":
            status.SlaveIOState = string(val.([]byte))
        case "Master_Log_File":
            status.MasterLogFile = string(val.([]byte))
        case "Read_Master_Log_Pos":
            status.ReadMasterLogPos = val.(int64)
        case "Slave_IO_Running":
            status.SlaveIORunning = string(val.([]byte))
        case "Slave_SQL_Running":
            status.SlaveSQLRunning = string(val.([]byte))
        case "Seconds_Behind_Master":
            if val != nil {
                seconds := val.(int64)
                status.SecondsBehindMaster = &seconds
            }
        case "Last_IO_Error":
            status.LastIOError = string(val.([]byte))
        case "Last_SQL_Error":
            status.LastSQLError = string(val.([]byte))
        case "Executed_Gtid_Set":
            status.GTIDSet = string(val.([]byte))
        case "Auto_Position":
            status.AutoPosition = val.(int64) == 1
        }
    }
    
    return status, nil
}

// 更新Prometheus指标
func (rm *ReplicationMonitor) updateMetrics(status *ReplicationStatus) {
    if status.SecondsBehindMaster != nil {
        rm.metrics.LagSeconds.Set(float64(*status.SecondsBehindMaster))
    }
    
    if status.SlaveIORunning == "Yes" {
        rm.metrics.SlaveIORunning.Set(1)
    } else {
        rm.metrics.SlaveIORunning.Set(0)
    }
    
    if status.SlaveSQLRunning == "Yes" {
        rm.metrics.SlaveSQLRunning.Set(1)
    } else {
        rm.metrics.SlaveSQLRunning.Set(0)
    }
}

// 检查告警条件
func (rm *ReplicationMonitor) checkForAlerts(status *ReplicationStatus, slaveHost string) {
    // 检查IO线程状态
    if status.SlaveIORunning != "Yes" {
        alert := &ReplicationAlert{
            Type:      "io_thread_stopped",
            Severity:  "critical",
            Message:   "从库IO线程已停止",
            SlaveHost: slaveHost,
            Details: map[string]interface{}{
                "last_io_error": status.LastIOError,
                "io_state":      status.SlaveIOState,
            },
            Timestamp: time.Now(),
        }
        rm.sendAlert(alert)
    }
    
    // 检查SQL线程状态
    if status.SlaveSQLRunning != "Yes" {
        alert := &ReplicationAlert{
            Type:      "sql_thread_stopped",
            Severity:  "critical",
            Message:   "从库SQL线程已停止",
            SlaveHost: slaveHost,
            Details: map[string]interface{}{
                "last_sql_error": status.LastSQLError,
            },
            Timestamp: time.Now(),
        }
        rm.sendAlert(alert)
    }
    
    // 检查复制延迟
    if status.SecondsBehindMaster != nil {
        lagSeconds := *status.SecondsBehindMaster
        
        if time.Duration(lagSeconds)*time.Second > rm.config.CriticalThreshold {
            alert := &ReplicationAlert{
                Type:       "high_replication_lag",
                Severity:   "critical",
                Message:    fmt.Sprintf("主从复制延迟过高: %d秒", lagSeconds),
                SlaveHost:  slaveHost,
                LagSeconds: &lagSeconds,
                Timestamp:  time.Now(),
            }
            rm.sendAlert(alert)
        } else if time.Duration(lagSeconds)*time.Second > rm.config.MaxLagThreshold {
            alert := &ReplicationAlert{
                Type:       "moderate_replication_lag",
                Severity:   "warning",
                Message:    fmt.Sprintf("主从复制延迟较高: %d秒", lagSeconds),
                SlaveHost:  slaveHost,
                LagSeconds: &lagSeconds,
                Timestamp:  time.Now(),
            }
            rm.sendAlert(alert)
        }
    }
}

// 发送告警
func (rm *ReplicationMonitor) sendAlert(alert *ReplicationAlert) {
    select {
    case rm.alertChan <- alert:
    default:
        log.Printf("告警通道已满，丢弃告警: %+v", alert)
    }
}

// 处理告警
func (rm *ReplicationMonitor) handleAlerts(ctx context.Context) {
    for {
        select {
        case <-ctx.Done():
            return
        case alert := <-rm.alertChan:
            rm.processAlert(alert)
        }
    }
}

func (rm *ReplicationMonitor) processAlert(alert *ReplicationAlert) {
    // 记录日志
    alertJSON, _ := json.MarshalIndent(alert, "", "  ")
    log.Printf("🚨 主从复制告警:\n%s", string(alertJSON))
    
    // 发送到外部告警系统
    if rm.config.AlertWebhook != "" {
        rm.sendWebhookAlert(alert)
    }
    
    // 自动故障处理
    if rm.config.AutoFailover && alert.Severity == "critical" {
        rm.handleCriticalAlert(alert)
    }
}

func (rm *ReplicationMonitor) sendWebhookAlert(alert *ReplicationAlert) {
    // 实现Webhook告警发送逻辑
    // 可以集成钉钉、微信、Slack等
}

func (rm *ReplicationMonitor) handleCriticalAlert(alert *ReplicationAlert) {
    switch alert.Type {
    case "io_thread_stopped":
        rm.restartIOThread(alert.SlaveHost)
    case "sql_thread_stopped":
        rm.restartSQLThread(alert.SlaveHost)
    case "high_replication_lag":
        if rm.config.AutoFailover {
            rm.considerFailover(alert)
        }
    }
}

func (rm *ReplicationMonitor) restartIOThread(slaveHost string) {
    // 实现IO线程重启逻辑
    log.Printf("尝试重启从库 %s 的IO线程", slaveHost)
}

func (rm *ReplicationMonitor) restartSQLThread(slaveHost string) {
    // 实现SQL线程重启逻辑
    log.Printf("尝试重启从库 %s 的SQL线程", slaveHost)
}

func (rm *ReplicationMonitor) considerFailover(alert *ReplicationAlert) {
    // 实现故障转移决策逻辑
    log.Printf("考虑对从库 %s 执行故障转移", alert.SlaveHost)
}
```

### 2.3 数据一致性保证机制

#### 半同步复制配置脚本

```bash
#!/bin/bash
# 半同步复制配置脚本

set -e

# 配置参数
MASTER_HOST="192.168.1.10"
SLAVE_HOSTS=("192.168.1.11" "192.168.1.12")
MYSQL_USER="root"
MYSQL_PASS="your_password"
REPL_USER="repl_user"
REPL_PASS="repl_password"

echo "🚀 开始配置MySQL半同步复制..."

# 1. 在主库上启用半同步复制
echo "📝 配置主库半同步复制..."
mysql -h$MASTER_HOST -u$MYSQL_USER -p$MYSQL_PASS <<EOF
-- 安装半同步复制插件
INSTALL PLUGIN rpl_semi_sync_master SONAME 'semisync_master.so';

-- 启用半同步复制
SET GLOBAL rpl_semi_sync_master_enabled = 1;
SET GLOBAL rpl_semi_sync_master_timeout = 1000;
SET GLOBAL rpl_semi_sync_master_wait_for_slave_count = 1;

-- 创建复制用户
CREATE USER IF NOT EXISTS '$REPL_USER'@'%' IDENTIFIED BY '$REPL_PASS';
GRANT REPLICATION SLAVE ON *.* TO '$REPL_USER'@'%';
FLUSH PRIVILEGES;

-- 查看主库状态
SHOW MASTER STATUS;
EOF

# 2. 配置从库
for SLAVE_HOST in "${SLAVE_HOSTS[@]}"; do
    echo "📝 配置从库 $SLAVE_HOST..."
    
    mysql -h$SLAVE_HOST -u$MYSQL_USER -p$MYSQL_PASS <<EOF
-- 安装半同步复制插件
INSTALL PLUGIN rpl_semi_sync_slave SONAME 'semisync_slave.so';

-- 启用半同步复制
SET GLOBAL rpl_semi_sync_slave_enabled = 1;

-- 停止复制
STOP SLAVE;

-- 配置主库连接
CHANGE MASTER TO
    MASTER_HOST='$MASTER_HOST',
    MASTER_USER='$REPL_USER',
    MASTER_PASSWORD='$REPL_PASS',
    MASTER_AUTO_POSITION=1;

-- 启动复制
START SLAVE;

-- 查看从库状态
SHOW SLAVE STATUS\G
EOF

done

# 3. 验证半同步复制状态
echo "🔍 验证半同步复制状态..."
mysql -h$MASTER_HOST -u$MYSQL_USER -p$MYSQL_PASS <<EOF
SHOW STATUS LIKE 'Rpl_semi_sync_master%';
EOF

for SLAVE_HOST in "${SLAVE_HOSTS[@]}"; do
    echo "检查从库 $SLAVE_HOST 状态:"
    mysql -h$SLAVE_HOST -u$MYSQL_USER -p$MYSQL_PASS <<EOF
SHOW STATUS LIKE 'Rpl_semi_sync_slave%';
EOF
done

echo "✅ 半同步复制配置完成！"
```

#### 数据一致性检查工具

```go
// 数据一致性检查器
type ConsistencyChecker struct {
    masterDB *sql.DB
    slaveDB  *sql.DB
    config   *CheckConfig
}

type CheckConfig struct {
    Tables          []string      `json:"tables"`
    CheckInterval   time.Duration `json:"check_interval"`
    SampleSize      int           `json:"sample_size"`
    ToleranceWindow time.Duration `json:"tolerance_window"`
}

type ConsistencyResult struct {
    TableName       string    `json:"table_name"`
    MasterChecksum  string    `json:"master_checksum"`
    SlaveChecksum   string    `json:"slave_checksum"`
    IsConsistent    bool      `json:"is_consistent"`
    RowCount        int64     `json:"row_count"`
    CheckTime       time.Time `json:"check_time"`
    Inconsistencies []RowDiff `json:"inconsistencies,omitempty"`
}

type RowDiff struct {
    PrimaryKey   interface{} `json:"primary_key"`
    MasterData   map[string]interface{} `json:"master_data"`
    SlaveData    map[string]interface{} `json:"slave_data"`
    DiffFields   []string    `json:"diff_fields"`
}

// 执行一致性检查
func (cc *ConsistencyChecker) CheckTableConsistency(tableName string) (*ConsistencyResult, error) {
    result := &ConsistencyResult{
        TableName: tableName,
        CheckTime: time.Now(),
    }
    
    // 1. 获取表结构信息
    primaryKey, err := cc.getPrimaryKey(tableName)
    if err != nil {
        return nil, fmt.Errorf("获取主键失败: %w", err)
    }
    
    // 2. 计算校验和
    masterChecksum, err := cc.calculateChecksum(cc.masterDB, tableName)
    if err != nil {
        return nil, fmt.Errorf("计算主库校验和失败: %w", err)
    }
    
    slaveChecksum, err := cc.calculateChecksum(cc.slaveDB, tableName)
    if err != nil {
        return nil, fmt.Errorf("计算从库校验和失败: %w", err)
    }
    
    result.MasterChecksum = masterChecksum
    result.SlaveChecksum = slaveChecksum
    result.IsConsistent = masterChecksum == slaveChecksum
    
    // 3. 如果不一致，进行详细比较
    if !result.IsConsistent {
        inconsistencies, err := cc.findInconsistencies(tableName, primaryKey)
        if err != nil {
            log.Printf("查找不一致数据失败: %v", err)
        } else {
            result.Inconsistencies = inconsistencies
        }
    }
    
    return result, nil
}

// 计算表校验和
func (cc *ConsistencyChecker) calculateChecksum(db *sql.DB, tableName string) (string, error) {
    query := fmt.Sprintf(`
        SELECT BIT_XOR(CAST(CRC32(CONCAT_WS(',', 
            %s
        )) AS UNSIGNED)) as checksum
        FROM %s
    `, cc.getAllColumns(tableName), tableName)
    
    var checksum sql.NullString
    err := db.QueryRow(query).Scan(&checksum)
    if err != nil {
        return "", err
    }
    
    if checksum.Valid {
        return checksum.String, nil
    }
    return "0", nil
}

// 获取表的所有列
func (cc *ConsistencyChecker) getAllColumns(tableName string) string {
    query := `
        SELECT GROUP_CONCAT(column_name ORDER BY ordinal_position)
        FROM information_schema.columns 
        WHERE table_schema = DATABASE() 
        AND table_name = ?
    `
    
    var columns string
    cc.masterDB.QueryRow(query, tableName).Scan(&columns)
    return columns
}

// 获取主键列
func (cc *ConsistencyChecker) getPrimaryKey(tableName string) (string, error) {
    query := `
        SELECT column_name
        FROM information_schema.key_column_usage
        WHERE table_schema = DATABASE()
        AND table_name = ?
        AND constraint_name = 'PRIMARY'
        ORDER BY ordinal_position
        LIMIT 1
    `
    
    var primaryKey string
    err := cc.masterDB.QueryRow(query, tableName).Scan(&primaryKey)
    return primaryKey, err
}

// 查找不一致的数据
func (cc *ConsistencyChecker) findInconsistencies(tableName, primaryKey string) ([]RowDiff, error) {
    // 获取样本数据进行比较
    query := fmt.Sprintf("SELECT * FROM %s ORDER BY %s LIMIT %d", 
                        tableName, primaryKey, cc.config.SampleSize)
    
    masterRows, err := cc.queryRows(cc.masterDB, query)
    if err != nil {
        return nil, err
    }
    
    slaveRows, err := cc.queryRows(cc.slaveDB, query)
    if err != nil {
        return nil, err
    }
    
    return cc.compareRows(masterRows, slaveRows, primaryKey), nil
}

func (cc *ConsistencyChecker) queryRows(db *sql.DB, query string) ([]map[string]interface{}, error) {
    rows, err := db.Query(query)
    if err != nil {
        return nil, err
    }
    defer rows.Close()
    
    columns, err := rows.Columns()
    if err != nil {
        return nil, err
    }
    
    var result []map[string]interface{}
    for rows.Next() {
        values := make([]interface{}, len(columns))
        valuePtrs := make([]interface{}, len(columns))
        for i := range values {
            valuePtrs[i] = &values[i]
        }
        
        if err := rows.Scan(valuePtrs...); err != nil {
            continue
        }
        
        row := make(map[string]interface{})
        for i, col := range columns {
            row[col] = values[i]
        }
        result = append(result, row)
    }
    
    return result, nil
}

func (cc *ConsistencyChecker) compareRows(masterRows, slaveRows []map[string]interface{}, primaryKey string) []RowDiff {
    var diffs []RowDiff
    
    // 创建从库数据的映射
    slaveMap := make(map[interface{}]map[string]interface{})
    for _, row := range slaveRows {
        if pk, ok := row[primaryKey]; ok {
            slaveMap[pk] = row
        }
    }
    
    // 比较主库数据
    for _, masterRow := range masterRows {
        pk := masterRow[primaryKey]
        slaveRow, exists := slaveMap[pk]
        
        if !exists {
            // 从库缺少该行
            diffs = append(diffs, RowDiff{
                PrimaryKey: pk,
                MasterData: masterRow,
                SlaveData:  nil,
                DiffFields: []string{"missing_in_slave"},
            })
            continue
        }
        
        // 比较字段值
        var diffFields []string
        for field, masterValue := range masterRow {
            slaveValue := slaveRow[field]
            if !cc.valuesEqual(masterValue, slaveValue) {
                diffFields = append(diffFields, field)
            }
        }
        
        if len(diffFields) > 0 {
            diffs = append(diffs, RowDiff{
                PrimaryKey: pk,
                MasterData: masterRow,
                SlaveData:  slaveRow,
                DiffFields: diffFields,
            })
        }
    }
    
    return diffs
}

func (cc *ConsistencyChecker) valuesEqual(v1, v2 interface{}) bool {
    // 处理NULL值
    if v1 == nil && v2 == nil {
        return true
    }
    if v1 == nil || v2 == nil {
        return false
    }
    
    // 转换为字符串比较（简化处理）
    return fmt.Sprintf("%v", v1) == fmt.Sprintf("%v", v2)
}
```

---

## 3. 分库分表中间件实现

### 3.1 Go语言分库分表中间件架构

#### 核心架构设计

```go
package sharding

import (
    "context"
    "database/sql"
    "fmt"
    "hash/crc32"
    "regexp"
    "strconv"
    "strings"
    "sync"
    "time"
)

// 分片中间件核心结构
type ShardingMiddleware struct {
    config      *ShardingConfig
    dataSources map[string]*sql.DB
    router      *ShardingRouter
    parser      *SQLParser
    merger      *ResultMerger
    monitor     *ShardingMonitor
    mu          sync.RWMutex
}

// 分片配置
type ShardingConfig struct {
    Databases []DatabaseConfig `json:"databases"`
    Tables    []TableConfig    `json:"tables"`
    Rules     []ShardingRule   `json:"rules"`
}

type DatabaseConfig struct {
    Name        string `json:"name"`
    DSN         string `json:"dsn"`
    Weight      int    `json:"weight"`
    MaxConn     int    `json:"max_conn"`
    MaxIdle     int    `json:"max_idle"`
    MaxLifetime string `json:"max_lifetime"`
}

type TableConfig struct {
    LogicTable    string   `json:"logic_table"`
    ActualTables  []string `json:"actual_tables"`
    ShardingKey   string   `json:"sharding_key"`
    ShardingAlgo  string   `json:"sharding_algo"`
    DatabaseShards []string `json:"database_shards"`
}

type ShardingRule struct {
    TableName     string `json:"table_name"`
    ShardingKey   string `json:"sharding_key"`
    Algorithm     string `json:"algorithm"`
    ShardCount    int    `json:"shard_count"`
    DatabaseRule  string `json:"database_rule"`
    TableRule     string `json:"table_rule"`
}

// SQL解析器
type SQLParser struct {
    selectRegex *regexp.Regexp
    insertRegex *regexp.Regexp
    updateRegex *regexp.Regexp
    deleteRegex *regexp.Regexp
}

type ParsedSQL struct {
    Type        SQLType                `json:"type"`
    TableName   string                 `json:"table_name"`
    Columns     []string               `json:"columns"`
    Values      []interface{}          `json:"values"`
    Conditions  map[string]interface{} `json:"conditions"`
    OrderBy     []string               `json:"order_by"`
    GroupBy     []string               `json:"group_by"`
    Limit       *LimitClause           `json:"limit"`
    OriginalSQL string                 `json:"original_sql"`
}

type SQLType int

const (
    SQLTypeSelect SQLType = iota
    SQLTypeInsert
    SQLTypeUpdate
    SQLTypeDelete
)

type LimitClause struct {
    Offset int `json:"offset"`
    Count  int `json:"count"`
}

// 分片路由器
type ShardingRouter struct {
    config *ShardingConfig
    algos  map[string]ShardingAlgorithm
}

type ShardingAlgorithm interface {
    Shard(key interface{}, shardCount int) int
}

// 哈希分片算法
type HashShardingAlgorithm struct{}

func (h *HashShardingAlgorithm) Shard(key interface{}, shardCount int) int {
    keyStr := fmt.Sprintf("%v", key)
    hash := crc32.ChecksumIEEE([]byte(keyStr))
    return int(hash) % shardCount
}

// 范围分片算法
type RangeShardingAlgorithm struct {
    Ranges []RangeConfig `json:"ranges"`
}

type RangeConfig struct {
    Min   int64 `json:"min"`
    Max   int64 `json:"max"`
    Shard int   `json:"shard"`
}

func (r *RangeShardingAlgorithm) Shard(key interface{}, shardCount int) int {
    keyInt, _ := strconv.ParseInt(fmt.Sprintf("%v", key), 10, 64)
    
    for _, rangeConfig := range r.Ranges {
        if keyInt >= rangeConfig.Min && keyInt <= rangeConfig.Max {
            return rangeConfig.Shard
        }
    }
    
    // 默认使用哈希
    return int(keyInt) % shardCount
}

// 时间分片算法
type TimeShardingAlgorithm struct {
    TimeFormat string `json:"time_format"`
    ShardUnit  string `json:"shard_unit"` // month, day, year
}

func (t *TimeShardingAlgorithm) Shard(key interface{}, shardCount int) int {
    timeStr := fmt.Sprintf("%v", key)
    parsedTime, err := time.Parse(t.TimeFormat, timeStr)
    if err != nil {
        // 解析失败，使用哈希
        return int(crc32.ChecksumIEEE([]byte(timeStr))) % shardCount
    }
    
    switch t.ShardUnit {
    case "month":
        return int(parsedTime.Month()) % shardCount
    case "day":
        return parsedTime.YearDay() % shardCount
    case "year":
        return parsedTime.Year() % shardCount
    default:
        return int(parsedTime.Unix()) % shardCount
    }
}

// 创建分片中间件
func NewShardingMiddleware(config *ShardingConfig) (*ShardingMiddleware, error) {
    sm := &ShardingMiddleware{
        config:      config,
        dataSources: make(map[string]*sql.DB),
        router:      NewShardingRouter(config),
        parser:      NewSQLParser(),
        merger:      NewResultMerger(),
        monitor:     NewShardingMonitor(),
    }
    
    // 初始化数据源连接
    if err := sm.initDataSources(); err != nil {
        return nil, err
    }
    
    return sm, nil
}

func (sm *ShardingMiddleware) initDataSources() error {
    for _, dbConfig := range sm.config.Databases {
        db, err := sql.Open("mysql", dbConfig.DSN)
        if err != nil {
            return fmt.Errorf("连接数据库 %s 失败: %w", dbConfig.Name, err)
        }
        
        // 设置连接池参数
        db.SetMaxOpenConns(dbConfig.MaxConn)
        db.SetMaxIdleConns(dbConfig.MaxIdle)
        
        if dbConfig.MaxLifetime != "" {
            if duration, err := time.ParseDuration(dbConfig.MaxLifetime); err == nil {
                db.SetConnMaxLifetime(duration)
            }
        }
        
        sm.dataSources[dbConfig.Name] = db
    }
    
    return nil
}

func NewShardingRouter(config *ShardingConfig) *ShardingRouter {
    router := &ShardingRouter{
        config: config,
        algos:  make(map[string]ShardingAlgorithm),
    }
    
    // 注册分片算法
    router.algos["hash"] = &HashShardingAlgorithm{}
    router.algos["range"] = &RangeShardingAlgorithm{}
    router.algos["time"] = &TimeShardingAlgorithm{}
    
    return router
}

// 路由查询到具体分片
func (sr *ShardingRouter) Route(parsedSQL *ParsedSQL) (*RoutingResult, error) {
    tableConfig := sr.getTableConfig(parsedSQL.TableName)
    if tableConfig == nil {
        return &RoutingResult{
            DatabaseName: sr.config.Databases[0].Name,
            TableName:    parsedSQL.TableName,
        }, nil
    }
    
    shardingKey := tableConfig.ShardingKey
    shardingValue := parsedSQL.Conditions[shardingKey]
    
    if shardingValue == nil {
        // 没有分片键，需要查询所有分片
        return sr.routeToAllShards(tableConfig), nil
    }
    
    // 计算分片
    algo := sr.algos[tableConfig.ShardingAlgo]
    if algo == nil {
        algo = sr.algos["hash"] // 默认使用哈希
    }
    
    shardIndex := algo.Shard(shardingValue, len(tableConfig.ActualTables))
    
    return &RoutingResult{
        DatabaseName: tableConfig.DatabaseShards[shardIndex%len(tableConfig.DatabaseShards)],
        TableName:    tableConfig.ActualTables[shardIndex],
        ShardIndex:   shardIndex,
    }, nil
}

type RoutingResult struct {
    DatabaseName string `json:"database_name"`
    TableName    string `json:"table_name"`
    ShardIndex   int    `json:"shard_index"`
    IsMultiShard bool   `json:"is_multi_shard"`
    AllShards    []ShardInfo `json:"all_shards,omitempty"`
}

type ShardInfo struct {
    DatabaseName string `json:"database_name"`
    TableName    string `json:"table_name"`
    ShardIndex   int    `json:"shard_index"`
}

func (sr *ShardingRouter) routeToAllShards(tableConfig *TableConfig) *RoutingResult {
    result := &RoutingResult{
        IsMultiShard: true,
        AllShards:    make([]ShardInfo, 0),
    }
    
    for i, tableName := range tableConfig.ActualTables {
        dbIndex := i % len(tableConfig.DatabaseShards)
        result.AllShards = append(result.AllShards, ShardInfo{
            DatabaseName: tableConfig.DatabaseShards[dbIndex],
            TableName:    tableName,
            ShardIndex:   i,
        })
    }
    
    return result
}

func (sr *ShardingRouter) getTableConfig(tableName string) *TableConfig {
    for _, tableConfig := range sr.config.Tables {
        if tableConfig.LogicTable == tableName {
            return &tableConfig
        }
    }
    return nil
}

// SQL解析器实现
func NewSQLParser() *SQLParser {
    return &SQLParser{
        selectRegex: regexp.MustCompile(`(?i)^\s*SELECT\s+(.+?)\s+FROM\s+(\w+)(?:\s+WHERE\s+(.+?))?(?:\s+ORDER\s+BY\s+(.+?))?(?:\s+LIMIT\s+(\d+)(?:\s*,\s*(\d+))?)?\s*$`),
        insertRegex: regexp.MustCompile(`(?i)^\s*INSERT\s+INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)\s*$`),
        updateRegex: regexp.MustCompile(`(?i)^\s*UPDATE\s+(\w+)\s+SET\s+(.+?)(?:\s+WHERE\s+(.+?))?\s*$`),
        deleteRegex: regexp.MustCompile(`(?i)^\s*DELETE\s+FROM\s+(\w+)(?:\s+WHERE\s+(.+?))?\s*$`),
    }
}

func (sp *SQLParser) Parse(sql string) (*ParsedSQL, error) {
    sql = strings.TrimSpace(sql)
    
    // 判断SQL类型并解析
    if sp.selectRegex.MatchString(sql) {
        return sp.parseSelect(sql)
    } else if sp.insertRegex.MatchString(sql) {
        return sp.parseInsert(sql)
    } else if sp.updateRegex.MatchString(sql) {
        return sp.parseUpdate(sql)
    } else if sp.deleteRegex.MatchString(sql) {
        return sp.parseDelete(sql)
    }
    
    return nil, fmt.Errorf("不支持的SQL类型: %s", sql)
}

func (sp *SQLParser) parseSelect(sql string) (*ParsedSQL, error) {
    matches := sp.selectRegex.FindStringSubmatch(sql)
    if len(matches) < 3 {
        return nil, fmt.Errorf("解析SELECT语句失败")
    }
    
    parsed := &ParsedSQL{
        Type:        SQLTypeSelect,
        TableName:   matches[2],
        OriginalSQL: sql,
        Conditions:  make(map[string]interface{}),
    }
    
    // 解析列
    if matches[1] != "*" {
        parsed.Columns = strings.Split(strings.ReplaceAll(matches[1], " ", ""), ",")
    }
    
    // 解析WHERE条件
    if len(matches) > 3 && matches[3] != "" {
        parsed.Conditions = sp.parseWhereConditions(matches[3])
    }
    
    // 解析ORDER BY
    if len(matches) > 4 && matches[4] != "" {
        parsed.OrderBy = strings.Split(strings.ReplaceAll(matches[4], " ", ""), ",")
    }
    
    // 解析LIMIT
    if len(matches) > 5 && matches[5] != "" {
        limit := &LimitClause{}
        if len(matches) > 6 && matches[6] != "" {
            limit.Offset, _ = strconv.Atoi(matches[5])
            limit.Count, _ = strconv.Atoi(matches[6])
        } else {
            limit.Count, _ = strconv.Atoi(matches[5])
        }
        parsed.Limit = limit
    }
    
    return parsed, nil
}

func (sp *SQLParser) parseInsert(sql string) (*ParsedSQL, error) {
    matches := sp.insertRegex.FindStringSubmatch(sql)
    if len(matches) < 4 {
        return nil, fmt.Errorf("解析INSERT语句失败")
    }
    
    parsed := &ParsedSQL{
        Type:        SQLTypeInsert,
        TableName:   matches[1],
        OriginalSQL: sql,
        Conditions:  make(map[string]interface{}),
    }
    
    // 解析列名
    columns := strings.Split(strings.ReplaceAll(matches[2], " ", ""), ",")
    parsed.Columns = columns
    
    // 解析值
    values := strings.Split(matches[3], ",")
    parsed.Values = make([]interface{}, len(values))
    for i, val := range values {
        val = strings.Trim(strings.TrimSpace(val), "'\"")
        parsed.Values[i] = val
        
        // 构建条件映射（用于分片路由）
        if i < len(columns) {
            parsed.Conditions[columns[i]] = val
        }
    }
    
    return parsed, nil
}

func (sp *SQLParser) parseUpdate(sql string) (*ParsedSQL, error) {
    matches := sp.updateRegex.FindStringSubmatch(sql)
    if len(matches) < 3 {
        return nil, fmt.Errorf("解析UPDATE语句失败")
    }
    
    parsed := &ParsedSQL{
        Type:        SQLTypeUpdate,
        TableName:   matches[1],
        OriginalSQL: sql,
        Conditions:  make(map[string]interface{}),
    }
    
    // 解析SET子句
    setClause := matches[2]
    setPairs := strings.Split(setClause, ",")
    for _, pair := range setPairs {
        parts := strings.Split(strings.TrimSpace(pair), "=")
        if len(parts) == 2 {
            key := strings.TrimSpace(parts[0])
            value := strings.Trim(strings.TrimSpace(parts[1]), "'\"")
            parsed.Conditions[key] = value
        }
    }
    
    // 解析WHERE条件
    if len(matches) > 3 && matches[3] != "" {
        whereConditions := sp.parseWhereConditions(matches[3])
        for k, v := range whereConditions {
            parsed.Conditions[k] = v
        }
    }
    
    return parsed, nil
}

func (sp *SQLParser) parseDelete(sql string) (*ParsedSQL, error) {
    matches := sp.deleteRegex.FindStringSubmatch(sql)
    if len(matches) < 2 {
        return nil, fmt.Errorf("解析DELETE语句失败")
    }
    
    parsed := &ParsedSQL{
        Type:        SQLTypeDelete,
        TableName:   matches[1],
        OriginalSQL: sql,
        Conditions:  make(map[string]interface{}),
    }
    
    // 解析WHERE条件
    if len(matches) > 2 && matches[2] != "" {
        parsed.Conditions = sp.parseWhereConditions(matches[2])
    }
    
    return parsed, nil
}

func (sp *SQLParser) parseWhereConditions(whereClause string) map[string]interface{} {
    conditions := make(map[string]interface{})
    
    // 简单的条件解析（生产环境需要更复杂的解析器）
    parts := strings.Split(whereClause, " AND ")
    for _, part := range parts {
        part = strings.TrimSpace(part)
        if strings.Contains(part, "=") {
            keyValue := strings.Split(part, "=")
            if len(keyValue) == 2 {
                key := strings.TrimSpace(keyValue[0])
                value := strings.Trim(strings.TrimSpace(keyValue[1]), "'\"")
                conditions[key] = value
            }
        }
    }
    
    return conditions
}

// 查询执行器
func (sm *ShardingMiddleware) Execute(ctx context.Context, sql string, args ...interface{}) (*ShardingResult, error) {
    // 1. 解析SQL
    parsedSQL, err := sm.parser.Parse(sql)
    if err != nil {
        return nil, fmt.Errorf("SQL解析失败: %w", err)
    }
    
    // 2. 路由到分片
    routingResult, err := sm.router.Route(parsedSQL)
    if err != nil {
        return nil, fmt.Errorf("路由失败: %w", err)
    }
    
    // 3. 执行查询
    if routingResult.IsMultiShard {
        return sm.executeMultiShard(ctx, parsedSQL, routingResult, args...)
    } else {
        return sm.executeSingleShard(ctx, parsedSQL, routingResult, args...)
    }
}

type ShardingResult struct {
    Rows         []map[string]interface{} `json:"rows"`
    RowsAffected int64                    `json:"rows_affected"`
    LastInsertID int64                    `json:"last_insert_id"`
    ExecutionTime time.Duration           `json:"execution_time"`
    ShardCount   int                      `json:"shard_count"`
    Error        error                    `json:"error,omitempty"`
}

func (sm *ShardingMiddleware) executeSingleShard(ctx context.Context, parsedSQL *ParsedSQL, routing *RoutingResult, args ...interface{}) (*ShardingResult, error) {
    start := time.Now()
    
    db := sm.dataSources[routing.DatabaseName]
    if db == nil {
        return nil, fmt.Errorf("数据源 %s 不存在", routing.DatabaseName)
    }
    
    // 替换表名
    actualSQL := strings.ReplaceAll(parsedSQL.OriginalSQL, parsedSQL.TableName, routing.TableName)
    
    result := &ShardingResult{
        ShardCount: 1,
        ExecutionTime: time.Since(start),
    }
    
    switch parsedSQL.Type {
    case SQLTypeSelect:
        rows, err := db.QueryContext(ctx, actualSQL, args...)
        if err != nil {
            result.Error = err
            return result, err
        }
        defer rows.Close()
        
        result.Rows, err = sm.scanRows(rows)
        if err != nil {
            result.Error = err
            return result, err
        }
        
    default:
        execResult, err := db.ExecContext(ctx, actualSQL, args...)
        if err != nil {
            result.Error = err
            return result, err
        }
        
        result.RowsAffected, _ = execResult.RowsAffected()
        result.LastInsertID, _ = execResult.LastInsertId()
    }
    
    result.ExecutionTime = time.Since(start)
    return result, nil
}

func (sm *ShardingMiddleware) executeMultiShard(ctx context.Context, parsedSQL *ParsedSQL, routing *RoutingResult, args ...interface{}) (*ShardingResult, error) {
    start := time.Now()
    
    var wg sync.WaitGroup
    results := make([]*ShardingResult, len(routing.AllShards))
    errors := make([]error, len(routing.AllShards))
    
    // 并行执行所有分片
    for i, shard := range routing.AllShards {
        wg.Add(1)
        go func(index int, shardInfo ShardInfo) {
            defer wg.Done()
            
            shardRouting := &RoutingResult{
                DatabaseName: shardInfo.DatabaseName,
                TableName:    shardInfo.TableName,
                ShardIndex:   shardInfo.ShardIndex,
            }
            
            result, err := sm.executeSingleShard(ctx, parsedSQL, shardRouting, args...)
            results[index] = result
            errors[index] = err
        }(i, shard)
    }
    
    wg.Wait()
    
    // 合并结果
    mergedResult := &ShardingResult{
        ShardCount:    len(routing.AllShards),
        ExecutionTime: time.Since(start),
    }
    
    return sm.merger.Merge(parsedSQL, results, errors, mergedResult)
}

// 扫描查询结果
func (sm *ShardingMiddleware) scanRows(rows *sql.Rows) ([]map[string]interface{}, error) {
    columns, err := rows.Columns()
    if err != nil {
        return nil, err
    }
    
    var result []map[string]interface{}
    for rows.Next() {
        values := make([]interface{}, len(columns))
        valuePtrs := make([]interface{}, len(columns))
        for i := range values {
            valuePtrs[i] = &values[i]
        }
        
        if err := rows.Scan(valuePtrs...); err != nil {
            return nil, err
        }
        
        row := make(map[string]interface{})
        for i, col := range columns {
            val := values[i]
            if b, ok := val.([]byte); ok {
                row[col] = string(b)
            } else {
                row[col] = val
            }
        }
        result = append(result, row)
    }
    
    return result, nil
}

// 结果合并器
type ResultMerger struct{}

func NewResultMerger() *ResultMerger {
    return &ResultMerger{}
}

func (rm *ResultMerger) Merge(parsedSQL *ParsedSQL, results []*ShardingResult, errors []error, mergedResult *ShardingResult) (*ShardingResult, error) {
    // 检查错误
    for i, err := range errors {
        if err != nil {
            return nil, fmt.Errorf("分片 %d 执行失败: %w", i, err)
        }
    }
    
    switch parsedSQL.Type {
    case SQLTypeSelect:
        return rm.mergeSelectResults(parsedSQL, results, mergedResult)
    default:
        return rm.mergeModifyResults(results, mergedResult)
    }
}

func (rm *ResultMerger) mergeSelectResults(parsedSQL *ParsedSQL, results []*ShardingResult, mergedResult *ShardingResult) (*ShardingResult, error) {
    var allRows []map[string]interface{}
    
    // 合并所有分片的结果
    for _, result := range results {
        if result != nil && result.Rows != nil {
            allRows = append(allRows, result.Rows...)
        }
    }
    
    // 排序
    if len(parsedSQL.OrderBy) > 0 {
        rm.sortRows(allRows, parsedSQL.OrderBy)
    }
    
    // 应用LIMIT
    if parsedSQL.Limit != nil {
        start := parsedSQL.Limit.Offset
        end := start + parsedSQL.Limit.Count
        if start > len(allRows) {
            allRows = []map[string]interface{}{}
        } else if end > len(allRows) {
            allRows = allRows[start:]
        } else {
            allRows = allRows[start:end]
        }
    }
    
    mergedResult.Rows = allRows
    return mergedResult, nil
}

func (rm *ResultMerger) mergeModifyResults(results []*ShardingResult, mergedResult *ShardingResult) (*ShardingResult, error) {
    var totalAffected int64
    var lastInsertID int64
    
    for _, result := range results {
        if result != nil {
            totalAffected += result.RowsAffected
            if result.LastInsertID > 0 {
                lastInsertID = result.LastInsertID
            }
        }
    }
    
    mergedResult.RowsAffected = totalAffected
    mergedResult.LastInsertID = lastInsertID
    return mergedResult, nil
}

func (rm *ResultMerger) sortRows(rows []map[string]interface{}, orderBy []string) {
    // 简单的排序实现（生产环境需要更复杂的排序逻辑）
    // 这里只实现单字段排序
    if len(orderBy) == 0 {
        return
    }
    
    sortField := strings.TrimSpace(orderBy[0])
    isDesc := strings.HasSuffix(strings.ToUpper(sortField), " DESC")
    if isDesc {
        sortField = strings.TrimSuffix(sortField, " DESC")
        sortField = strings.TrimSpace(sortField)
    }
    
    // 这里需要实现具体的排序逻辑
    // 由于Go的sort包需要具体的比较函数，这里省略具体实现
}

// 分片监控器
type ShardingMonitor struct {
    metrics map[string]*ShardMetrics
    mu      sync.RWMutex
}

type ShardMetrics struct {
    QueryCount    int64         `json:"query_count"`
    ErrorCount    int64         `json:"error_count"`
    AvgLatency    time.Duration `json:"avg_latency"`
    MaxLatency    time.Duration `json:"max_latency"`
    LastQueryTime time.Time     `json:"last_query_time"`
}

func NewShardingMonitor() *ShardingMonitor {
    return &ShardingMonitor{
        metrics: make(map[string]*ShardMetrics),
    }
}

func (sm *ShardingMonitor) RecordQuery(shardName string, latency time.Duration, err error) {
    sm.mu.Lock()
    defer sm.mu.Unlock()
    
    metrics, exists := sm.metrics[shardName]
    if !exists {
        metrics = &ShardMetrics{}
        sm.metrics[shardName] = metrics
    }
    
    metrics.QueryCount++
    metrics.LastQueryTime = time.Now()
    
    if err != nil {
        metrics.ErrorCount++
    }
    
    // 更新延迟统计
    if latency > metrics.MaxLatency {
        metrics.MaxLatency = latency
    }
    
    // 简单的平均延迟计算
    metrics.AvgLatency = (metrics.AvgLatency*time.Duration(metrics.QueryCount-1) + latency) / time.Duration(metrics.QueryCount)
}

func (sm *ShardingMonitor) GetMetrics() map[string]*ShardMetrics {
    sm.mu.RLock()
    defer sm.mu.RUnlock()
    
    result := make(map[string]*ShardMetrics)
    for k, v := range sm.metrics {
        result[k] = v
    }
    return result
}

### 3.2 分片配置示例

#### 电商订单表分片配置

```json
{
  "databases": [
    {
      "name": "order_db_0",
      "dsn": "user:password@tcp(192.168.1.10:3306)/order_db_0?charset=utf8mb4",
      "weight": 1,
      "max_conn": 100,
      "max_idle": 10,
      "max_lifetime": "1h"
    },
    {
      "name": "order_db_1",
      "dsn": "user:password@tcp(192.168.1.11:3306)/order_db_1?charset=utf8mb4",
      "weight": 1,
      "max_conn": 100,
      "max_idle": 10,
      "max_lifetime": "1h"
    }
  ],
  "tables": [
    {
      "logic_table": "orders",
      "actual_tables": [
        "orders_0", "orders_1", "orders_2", "orders_3",
        "orders_4", "orders_5", "orders_6", "orders_7"
      ],
      "sharding_key": "user_id",
      "sharding_algo": "hash",
      "database_shards": ["order_db_0", "order_db_1"]
    },
    {
      "logic_table": "order_items",
      "actual_tables": [
        "order_items_0", "order_items_1", "order_items_2", "order_items_3"
      ],
      "sharding_key": "order_id",
      "sharding_algo": "hash",
      "database_shards": ["order_db_0", "order_db_1"]
    }
  ],
  "rules": [
    {
      "table_name": "orders",
      "sharding_key": "user_id",
      "algorithm": "hash",
      "shard_count": 8,
      "database_rule": "order_db_${user_id % 2}",
      "table_rule": "orders_${user_id % 8}"
    }
  ]
}
```

#### 使用示例

```go
func main() {
    // 1. 加载配置
    config := &ShardingConfig{}
    configData, _ := ioutil.ReadFile("sharding_config.json")
    json.Unmarshal(configData, config)
    
    // 2. 创建分片中间件
    middleware, err := NewShardingMiddleware(config)
    if err != nil {
        log.Fatal("创建分片中间件失败:", err)
    }
    
    // 3. 执行查询
    ctx := context.Background()
    
    // 单分片查询（包含分片键）
    result, err := middleware.Execute(ctx, 
        "SELECT * FROM orders WHERE user_id = 12345")
    if err != nil {
        log.Printf("查询失败: %v", err)
    } else {
        log.Printf("查询结果: %+v", result)
    }
    
    // 多分片查询（不包含分片键）
    result, err = middleware.Execute(ctx, 
        "SELECT COUNT(*) FROM orders WHERE status = 'completed'")
    if err != nil {
        log.Printf("查询失败: %v", err)
    } else {
        log.Printf("查询结果: %+v", result)
    }
    
    // 插入数据
    result, err = middleware.Execute(ctx, 
        "INSERT INTO orders (user_id, total, status) VALUES (12345, 99.99, 'pending')")
    if err != nil {
        log.Printf("插入失败: %v", err)
    } else {
        log.Printf("插入结果: %+v", result)
    }
}
```

---

## 4. 备份恢复自动化运维

### 4.1 mysqldump自动化备份脚本

#### 全量备份脚本

```bash
#!/bin/bash
# MySQL全量备份脚本
# 文件名: mysql_full_backup.sh

set -e

# 配置参数
MYSQL_HOST="localhost"
MYSQL_PORT="3306"
MYSQL_USER="backup_user"
MYSQL_PASS="backup_password"
BACKUP_DIR="/data/mysql_backup"
LOG_FILE="/var/log/mysql_backup.log"
RETENTION_DAYS=7
COMPRESSION=true
ENCRYPTION=true
ENCRYPTION_KEY="/etc/mysql/backup.key"

# 数据库列表（空表示备份所有数据库）
DATABASES=("production_db" "user_db" "order_db")

# 邮件通知配置
EMAIL_ENABLED=true
EMAIL_TO="admin@company.com"
SMTP_SERVER="smtp.company.com"

# 钉钉通知配置
DINGTALK_ENABLED=true
DINGTALK_WEBHOOK="https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN"

# 日志函数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# 错误处理函数
error_exit() {
    log "❌ 错误: $1"
    send_alert "备份失败" "$1"
    exit 1
}

# 发送告警
send_alert() {
    local title="$1"
    local message="$2"
    
    if [ "$EMAIL_ENABLED" = true ]; then
        echo "$message" | mail -s "$title" "$EMAIL_TO"
    fi
    
    if [ "$DINGTALK_ENABLED" = true ]; then
        curl -X POST "$DINGTALK_WEBHOOK" \
            -H 'Content-Type: application/json' \
            -d "{
                \"msgtype\": \"text\",
                \"text\": {
                    \"content\": \"🚨 MySQL备份告警\\n标题: $title\\n详情: $message\\n时间: $(date)\"
                }
            }"
    fi
}

# 检查依赖
check_dependencies() {
    log "🔍 检查依赖..."
    
    command -v mysqldump >/dev/null 2>&1 || error_exit "mysqldump 未安装"
    command -v mysql >/dev/null 2>&1 || error_exit "mysql 客户端未安装"
    
    if [ "$COMPRESSION" = true ]; then
        command -v gzip >/dev/null 2>&1 || error_exit "gzip 未安装"
    fi
    
    if [ "$ENCRYPTION" = true ]; then
        command -v openssl >/dev/null 2>&1 || error_exit "openssl 未安装"
        [ -f "$ENCRYPTION_KEY" ] || error_exit "加密密钥文件不存在: $ENCRYPTION_KEY"
    fi
}

# 测试数据库连接
test_connection() {
    log "🔗 测试数据库连接..."
    
    mysql -h"$MYSQL_HOST" -P"$MYSQL_PORT" -u"$MYSQL_USER" -p"$MYSQL_PASS" \
        -e "SELECT 1" >/dev/null 2>&1 || error_exit "数据库连接失败"
    
    log "✅ 数据库连接正常"
}

# 创建备份目录
create_backup_dir() {
    local backup_date=$(date +%Y%m%d_%H%M%S)
    CURRENT_BACKUP_DIR="$BACKUP_DIR/$backup_date"
    
    mkdir -p "$CURRENT_BACKUP_DIR" || error_exit "创建备份目录失败: $CURRENT_BACKUP_DIR"
    log "📁 创建备份目录: $CURRENT_BACKUP_DIR"
}

# 备份单个数据库
backup_database() {
    local db_name="$1"
    local backup_file="$CURRENT_BACKUP_DIR/${db_name}_$(date +%Y%m%d_%H%M%S).sql"
    
    log "📦 开始备份数据库: $db_name"
    
    # mysqldump参数说明:
    # --single-transaction: 保证InnoDB表的一致性
    # --routines: 备份存储过程和函数
    # --triggers: 备份触发器
    # --events: 备份事件
    # --hex-blob: 使用十六进制格式备份BLOB字段
    # --master-data=2: 记录binlog位置（注释形式）
    # --flush-logs: 刷新日志
    mysqldump \
        -h"$MYSQL_HOST" \
        -P"$MYSQL_PORT" \
        -u"$MYSQL_USER" \
        -p"$MYSQL_PASS" \
        --single-transaction \
        --routines \
        --triggers \
        --events \
        --hex-blob \
        --master-data=2 \
        --flush-logs \
        --default-character-set=utf8mb4 \
        "$db_name" > "$backup_file" || error_exit "备份数据库 $db_name 失败"
    
    # 压缩备份文件
    if [ "$COMPRESSION" = true ]; then
        log "🗜️ 压缩备份文件..."
        gzip "$backup_file" || error_exit "压缩备份文件失败"
        backup_file="${backup_file}.gz"
    fi
    
    # 加密备份文件
    if [ "$ENCRYPTION" = true ]; then
        log "🔐 加密备份文件..."
        openssl enc -aes-256-cbc -salt -in "$backup_file" -out "${backup_file}.enc" \
            -pass file:"$ENCRYPTION_KEY" || error_exit "加密备份文件失败"
        rm "$backup_file"
        backup_file="${backup_file}.enc"
    fi
    
    # 计算文件大小和校验和
    local file_size=$(du -h "$backup_file" | cut -f1)
    local checksum=$(sha256sum "$backup_file" | cut -d' ' -f1)
    
    log "✅ 数据库 $db_name 备份完成"
    log "   文件: $backup_file"
    log "   大小: $file_size"
    log "   校验和: $checksum"
    
    # 记录备份信息
    echo "$db_name|$backup_file|$file_size|$checksum|$(date)" >> "$CURRENT_BACKUP_DIR/backup_info.txt"
}

# 备份所有数据库
backup_all_databases() {
    if [ ${#DATABASES[@]} -eq 0 ]; then
        # 获取所有数据库列表
        local all_dbs=$(mysql -h"$MYSQL_HOST" -P"$MYSQL_PORT" -u"$MYSQL_USER" -p"$MYSQL_PASS" \
            -e "SHOW DATABASES;" | grep -v -E '^(Database|information_schema|performance_schema|mysql|sys)$')
        
        for db in $all_dbs; do
            backup_database "$db"
        done
    else
        for db in "${DATABASES[@]}"; do
            backup_database "$db"
        done
    fi
}

# 清理旧备份
cleanup_old_backups() {
    log "🧹 清理 $RETENTION_DAYS 天前的备份..."
    
    find "$BACKUP_DIR" -type d -name "20*" -mtime +$RETENTION_DAYS -exec rm -rf {} + 2>/dev/null || true
    
    log "✅ 旧备份清理完成"
}

# 验证备份完整性
verify_backup() {
    log "🔍 验证备份完整性..."
    
    local backup_info_file="$CURRENT_BACKUP_DIR/backup_info.txt"
    if [ ! -f "$backup_info_file" ]; then
        error_exit "备份信息文件不存在"
    fi
    
    while IFS='|' read -r db_name backup_file file_size checksum backup_time; do
        if [ ! -f "$backup_file" ]; then
            error_exit "备份文件不存在: $backup_file"
        fi
        
        local current_checksum=$(sha256sum "$backup_file" | cut -d' ' -f1)
        if [ "$checksum" != "$current_checksum" ]; then
            error_exit "备份文件校验和不匹配: $backup_file"
        fi
        
        log "✅ $db_name 备份文件验证通过"
    done < "$backup_info_file"
}

# 生成备份报告
generate_report() {
    local report_file="$CURRENT_BACKUP_DIR/backup_report.txt"
    local total_size=$(du -sh "$CURRENT_BACKUP_DIR" | cut -f1)
    local backup_count=$(ls -1 "$CURRENT_BACKUP_DIR"/*.sql* 2>/dev/null | wc -l)
    
    cat > "$report_file" << EOF
MySQL备份报告
=============

备份时间: $(date)
备份目录: $CURRENT_BACKUP_DIR
备份数量: $backup_count 个数据库
总大小: $total_size

备份详情:
EOF
    
    if [ -f "$CURRENT_BACKUP_DIR/backup_info.txt" ]; then
        echo "" >> "$report_file"
        printf "%-20s %-50s %-10s %-20s\n" "数据库" "备份文件" "大小" "备份时间" >> "$report_file"
        printf "%-20s %-50s %-10s %-20s\n" "--------" "--------" "----" "--------" >> "$report_file"
        
        while IFS='|' read -r db_name backup_file file_size checksum backup_time; do
            local short_file=$(basename "$backup_file")
            printf "%-20s %-50s %-10s %-20s\n" "$db_name" "$short_file" "$file_size" "$backup_time" >> "$report_file"
        done < "$CURRENT_BACKUP_DIR/backup_info.txt"
    fi
    
    log "📊 备份报告已生成: $report_file"
}

# 主函数
main() {
    log "🚀 开始MySQL全量备份..."
    
    check_dependencies
    test_connection
    create_backup_dir
    backup_all_databases
    verify_backup
    generate_report
    cleanup_old_backups
    
    local total_time=$(($(date +%s) - $start_time))
    log "✅ 备份完成，总耗时: ${total_time}秒"
    
    # 发送成功通知
    local report_content=$(cat "$CURRENT_BACKUP_DIR/backup_report.txt")
    send_alert "MySQL备份成功" "$report_content"
}

# 脚本入口
start_time=$(date +%s)
trap 'error_exit "脚本被中断"' INT TERM

main "$@"
```

#### 增量备份脚本（基于binlog）

```bash
#!/bin/bash
# MySQL增量备份脚本（基于binlog）
# 文件名: mysql_incremental_backup.sh

set -e

# 配置参数
MYSQL_HOST="localhost"
MYSQL_PORT="3306"
MYSQL_USER="backup_user"
MYSQL_PASS="backup_password"
BACKUP_DIR="/data/mysql_backup/incremental"
LOG_FILE="/var/log/mysql_incremental_backup.log"
BINLOG_DIR="/var/lib/mysql"
LAST_BACKUP_INFO="/data/mysql_backup/last_backup_info.txt"
RETENTION_DAYS=30

# 日志函数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# 错误处理函数
error_exit() {
    log "❌ 错误: $1"
    exit 1
}

# 获取当前binlog位置
get_current_binlog_position() {
    mysql -h"$MYSQL_HOST" -P"$MYSQL_PORT" -u"$MYSQL_USER" -p"$MYSQL_PASS" \
        -e "SHOW MASTER STATUS\G" | grep -E "(File|Position)" | awk '{print $2}' | tr '\n' '|'
}

# 获取上次备份的binlog位置
get_last_backup_position() {
    if [ -f "$LAST_BACKUP_INFO" ]; then
        cat "$LAST_BACKUP_INFO"
    else
        echo "|"
    fi
}

# 备份binlog
backup_binlog() {
    local current_position=$(get_current_binlog_position)
    local last_position=$(get_last_backup_position)
    
    local current_file=$(echo "$current_position" | cut -d'|' -f1)
    local current_pos=$(echo "$current_position" | cut -d'|' -f2)
    local last_file=$(echo "$last_position" | cut -d'|' -f1)
    local last_pos=$(echo "$last_position" | cut -d'|' -f2)
    
    log "📍 当前binlog位置: $current_file:$current_pos"
    log "📍 上次备份位置: $last_file:$last_pos"
    
    # 创建备份目录
    local backup_date=$(date +%Y%m%d_%H%M%S)
    local current_backup_dir="$BACKUP_DIR/$backup_date"
    mkdir -p "$current_backup_dir"
    
    # 如果是第一次备份，从当前位置开始
    if [ -z "$last_file" ]; then
        log "🔄 首次增量备份，从当前位置开始"
        echo "$current_position" > "$LAST_BACKUP_INFO"
        return 0
    fi
    
    # 使用mysqlbinlog备份指定范围的binlog
    local backup_file="$current_backup_dir/binlog_${backup_date}.sql"
    
    if [ "$last_file" = "$current_file" ]; then
        # 同一个binlog文件内的增量
        mysqlbinlog --start-position="$last_pos" --stop-position="$current_pos" \
            "$BINLOG_DIR/$current_file" > "$backup_file" || error_exit "备份binlog失败"
    else
        # 跨多个binlog文件的增量
        # 获取binlog文件列表
        local binlog_files=$(mysql -h"$MYSQL_HOST" -P"$MYSQL_PORT" -u"$MYSQL_USER" -p"$MYSQL_PASS" \
            -e "SHOW BINARY LOGS" | awk 'NR>1 {print $1}' | \
            awk -v start="$last_file" -v end="$current_file" '
                $0 >= start && $0 <= end {print}'
        )
        
        > "$backup_file"  # 清空文件
        
        local first_file=true
        for binlog_file in $binlog_files; do
            if [ "$first_file" = true ]; then
                # 第一个文件：从指定位置开始
                mysqlbinlog --start-position="$last_pos" \
                    "$BINLOG_DIR/$binlog_file" >> "$backup_file"
                first_file=false
            elif [ "$binlog_file" = "$current_file" ]; then
                # 最后一个文件：到指定位置结束
                mysqlbinlog --stop-position="$current_pos" \
                    "$BINLOG_DIR/$binlog_file" >> "$backup_file"
            else
                # 中间文件：完整备份
                mysqlbinlog "$BINLOG_DIR/$binlog_file" >> "$backup_file"
            fi
        done
    fi
    
    # 压缩备份文件
    gzip "$backup_file"
    backup_file="${backup_file}.gz"
    
    # 计算文件大小和校验和
    local file_size=$(du -h "$backup_file" | cut -f1)
    local checksum=$(sha256sum "$backup_file" | cut -d' ' -f1)
    
    log "✅ 增量备份完成"
    log "   文件: $backup_file"
    log "   大小: $file_size"
    log "   校验和: $checksum"
    log "   范围: $last_file:$last_pos -> $current_file:$current_pos"
    
    # 更新备份位置信息
    echo "$current_position" > "$LAST_BACKUP_INFO"
    
    # 记录备份信息
    echo "$backup_date|$backup_file|$file_size|$checksum|$last_file:$last_pos|$current_file:$current_pos|$(date)" \
        >> "$BACKUP_DIR/incremental_backup_log.txt"
}

# 清理旧的增量备份
cleanup_old_incremental_backups() {
    log "🧹 清理 $RETENTION_DAYS 天前的增量备份..."
    
    find "$BACKUP_DIR" -type d -name "20*" -mtime +$RETENTION_DAYS -exec rm -rf {} + 2>/dev/null || true
    
    log "✅ 旧增量备份清理完成"
}

# 主函数
main() {
    log "🚀 开始MySQL增量备份..."
    
    backup_binlog
    cleanup_old_incremental_backups
    
    log "✅ 增量备份完成"
}

# 脚本入口
trap 'error_exit "脚本被中断"' INT TERM
main "$@"
```

### 4.2 binlog恢复脚本

#### 自动化恢复脚本

```bash
#!/bin/bash
# MySQL binlog恢复脚本
# 文件名: mysql_recovery.sh

set -e

# 配置参数
MYSQL_HOST="localhost"
MYSQL_PORT="3306"
MYSQL_USER="root"
MYSQL_PASS="root_password"
BACKUP_DIR="/data/mysql_backup"
LOG_FILE="/var/log/mysql_recovery.log"
TEMP_DIR="/tmp/mysql_recovery"

# 日志函数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# 错误处理函数
error_exit() {
    log "❌ 错误: $1"
    exit 1
}

# 显示使用说明
show_usage() {
    cat << EOF
使用说明:
$0 [选项]

选项:
  -t, --type TYPE           恢复类型: full|incremental|point_in_time
  -d, --database DB         要恢复的数据库名
  -f, --full-backup FILE    全量备份文件路径
  -i, --incremental-dir DIR 增量备份目录
  -p, --point-in-time TIME  恢复到指定时间点 (格式: YYYY-MM-DD HH:MM:SS)
  -s, --start-time TIME     开始时间 (格式: YYYY-MM-DD HH:MM:SS)
  -e, --end-time TIME       结束时间 (格式: YYYY-MM-DD HH:MM:SS)
  -n, --dry-run             试运行模式，不实际执行恢复
  -h, --help                显示此帮助信息

示例:
  # 全量恢复
  $0 -t full -d mydb -f /data/backup/mydb_20231201.sql.gz
  
  # 增量恢复
  $0 -t incremental -d mydb -f /data/backup/mydb_20231201.sql.gz -i /data/backup/incremental
  
  # 时间点恢复
  $0 -t point_in_time -d mydb -f /data/backup/mydb_20231201.sql.gz -p "2023-12-01 15:30:00"
EOF
}

# 解析命令行参数
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -t|--type)
                RECOVERY_TYPE="$2"
                shift 2
                ;;
            -d|--database)
                DATABASE="$2"
                shift 2
                ;;
            -f|--full-backup)
                FULL_BACKUP_FILE="$2"
                shift 2
                ;;
            -i|--incremental-dir)
                INCREMENTAL_DIR="$2"
                shift 2
                ;;
            -p|--point-in-time)
                POINT_IN_TIME="$2"
                shift 2
                ;;
            -s|--start-time)
                START_TIME="$2"
                shift 2
                ;;
            -e|--end-time)
                END_TIME="$2"
                shift 2
                ;;
            -n|--dry-run)
                DRY_RUN=true
                shift
                ;;
            -h|--help)
                show_usage
                exit 0
                ;;
            *)
                echo "未知参数: $1"
                show_usage
                exit 1
                ;;
        esac
    done
    
    # 验证必需参数
    if [ -z "$RECOVERY_TYPE" ]; then
        error_exit "必须指定恢复类型 (-t|--type)"
    fi
    
    if [ -z "$DATABASE" ]; then
        error_exit "必须指定数据库名 (-d|--database)"
    fi
    
    if [ -z "$FULL_BACKUP_FILE" ]; then
        error_exit "必须指定全量备份文件 (-f|--full-backup)"
    fi
}

# 验证备份文件
validate_backup_files() {
    log "🔍 验证备份文件..."
    
    if [ ! -f "$FULL_BACKUP_FILE" ]; then
        error_exit "全量备份文件不存在: $FULL_BACKUP_FILE"
    fi
    
    if [ "$RECOVERY_TYPE" = "incremental" ] && [ ! -d "$INCREMENTAL_DIR" ]; then
        error_exit "增量备份目录不存在: $INCREMENTAL_DIR"
    fi
    
    log "✅ 备份文件验证通过"
}

# 创建临时目录
create_temp_dir() {
    rm -rf "$TEMP_DIR"
    mkdir -p "$TEMP_DIR"
    log "📁 创建临时目录: $TEMP_DIR"
}

# 解压备份文件
extract_backup_file() {
    local backup_file="$1"
    local output_file="$2"
    
    log "📦 解压备份文件: $backup_file"
    
    if [[ "$backup_file" == *.gz ]]; then
        gunzip -c "$backup_file" > "$output_file"
    elif [[ "$backup_file" == *.enc ]]; then
        # 如果是加密文件，需要先解密
        local encryption_key="/etc/mysql/backup.key"
        if [ ! -f "$encryption_key" ]; then
            error_exit "加密密钥文件不存在: $encryption_key"
        fi
        openssl enc -aes-256-cbc -d -in "$backup_file" -out "$output_file" \
            -pass file:"$encryption_key" || error_exit "解密备份文件失败"
    else
        cp "$backup_file" "$output_file"
    fi
}

# 执行SQL文件
execute_sql_file() {
    local sql_file="$1"
    local description="$2"
    
    log "🔄 执行$description: $sql_file"
    
    if [ "$DRY_RUN" = true ]; then
        log "🔍 [试运行] 跳过执行: $sql_file"
        return 0
    fi
    
    mysql -h"$MYSQL_HOST" -P"$MYSQL_PORT" -u"$MYSQL_USER" -p"$MYSQL_PASS" \
        "$DATABASE" < "$sql_file" || error_exit "执行$description失败"
    
    log "✅ $description执行完成"
}

# 全量恢复
full_recovery() {
    log "🚀 开始全量恢复..."
    
    local temp_sql="$TEMP_DIR/full_backup.sql"
    extract_backup_file "$FULL_BACKUP_FILE" "$temp_sql"
    
    # 创建数据库（如果不存在）
    if [ "$DRY_RUN" != true ]; then
        mysql -h"$MYSQL_HOST" -P"$MYSQL_PORT" -u"$MYSQL_USER" -p"$MYSQL_PASS" \
            -e "CREATE DATABASE IF NOT EXISTS \`$DATABASE\`" || error_exit "创建数据库失败"
    fi
    
    execute_sql_file "$temp_sql" "全量备份恢复"
    
    log "✅ 全量恢复完成"
}

# 增量恢复
incremental_recovery() {
    log "🚀 开始增量恢复..."
    
    # 先执行全量恢复
    full_recovery
    
    # 获取增量备份文件列表（按时间排序）
    local incremental_files=$(find "$INCREMENTAL_DIR" -name "*.sql.gz" -type f | sort)
    
    if [ -z "$incremental_files" ]; then
        log "⚠️ 未找到增量备份文件"
        return 0
    fi
    
    # 逐个应用增量备份
    for inc_file in $incremental_files; do
        local temp_inc_sql="$TEMP_DIR/$(basename "$inc_file" .gz)"
        extract_backup_file "$inc_file" "$temp_inc_sql"
        execute_sql_file "$temp_inc_sql" "增量备份恢复 ($(basename "$inc_file"))"
        rm -f "$temp_inc_sql"
    done
    
    log "✅ 增量恢复完成"
}

# 时间点恢复
point_in_time_recovery() {
    log "🚀 开始时间点恢复..."
    
    if [ -z "$POINT_IN_TIME" ]; then
        error_exit "时间点恢复需要指定目标时间 (-p|--point-in-time)"
    fi
    
    # 先执行全量恢复
    full_recovery
    
    # 应用binlog到指定时间点
    local binlog_files=$(find "$INCREMENTAL_DIR" -name "*.sql.gz" -type f | sort)
    
    for binlog_file in $binlog_files; do
        local temp_binlog="$TEMP_DIR/$(basename "$binlog_file" .gz)"
        extract_backup_file "$binlog_file" "$temp_binlog"
        
        # 使用mysqlbinlog过滤到指定时间点
        local filtered_binlog="$TEMP_DIR/filtered_$(basename "$temp_binlog")"
        
        if [ -n "$START_TIME" ]; then
            mysqlbinlog --start-datetime="$START_TIME" --stop-datetime="$POINT_IN_TIME" \
                "$temp_binlog" > "$filtered_binlog"
        else
            mysqlbinlog --stop-datetime="$POINT_IN_TIME" \
                "$temp_binlog" > "$filtered_binlog"
        fi
        
        if [ -s "$filtered_binlog" ]; then
            execute_sql_file "$filtered_binlog" "时间点恢复 (到 $POINT_IN_TIME)"
        fi
        
        rm -f "$temp_binlog" "$filtered_binlog"
    done
    
    log "✅ 时间点恢复完成"
}

# 清理临时文件
cleanup() {
    log "🧹 清理临时文件..."
    rm -rf "$TEMP_DIR"
}

# 主函数
main() {
    log "🚀 开始MySQL数据恢复..."
    log "恢复类型: $RECOVERY_TYPE"
    log "目标数据库: $DATABASE"
    log "全量备份: $FULL_BACKUP_FILE"
    
    if [ "$DRY_RUN" = true ]; then
        log "🔍 试运行模式已启用"
    fi
    
    validate_backup_files
    create_temp_dir
    
    case "$RECOVERY_TYPE" in
        "full")
            full_recovery
            ;;
        "incremental")
            incremental_recovery
            ;;
        "point_in_time")
            point_in_time_recovery
            ;;
        *)
            error_exit "不支持的恢复类型: $RECOVERY_TYPE"
            ;;
    esac
    
    cleanup
    
    log "✅ 数据恢复完成"
}

# 脚本入口
trap 'cleanup; error_exit "脚本被中断"' INT TERM

# 解析参数
parse_args "$@"

# 执行主函数
main
```

### 4.3 自动化运维脚本集成

#### 备份恢复管理脚本

```bash
#!/bin/bash
# MySQL备份恢复管理脚本
# 文件名: mysql_backup_manager.sh

set -e

# 配置文件路径
CONFIG_FILE="/etc/mysql/backup_config.conf"
SCRIPT_DIR="/opt/mysql_scripts"
LOG_DIR="/var/log/mysql_backup"

# 默认配置
DEFAULT_CONFIG="
# MySQL备份配置文件
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=backup_user
MYSQL_PASS=backup_password
BACKUP_DIR=/data/mysql_backup
FULL_BACKUP_SCHEDULE='0 2 * * 0'  # 每周日凌晨2点
INCREMENTAL_BACKUP_SCHEDULE='0 */6 * * *'  # 每6小时
RETENTION_DAYS=30
COMPRESSION=true
ENCRYPTION=true
ENCRYPTION_KEY=/etc/mysql/backup.key
EMAIL_ENABLED=true
EMAIL_TO=admin@company.com
DINGTALK_ENABLED=true
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN
"

# 日志函数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_DIR/manager.log"
}

# 错误处理函数
error_exit() {
    log "❌ 错误: $1"
    exit 1
}

# 显示使用说明
show_usage() {
    cat << EOF
MySQL备份恢复管理工具

使用说明:
$0 [命令] [选项]

命令:
  install           安装备份系统
  uninstall         卸载备份系统
  start             启动备份服务
  stop              停止备份服务
  status            查看备份状态
  backup-now        立即执行备份
  list-backups      列出所有备份
  restore           恢复数据
  test              测试备份系统
  config            配置管理
  logs              查看日志

选项:
  -h, --help        显示此帮助信息
  -v, --verbose     详细输出
  -c, --config FILE 指定配置文件

示例:
  $0 install                    # 安装备份系统
  $0 backup-now --type full     # 立即执行全量备份
  $0 restore --help             # 查看恢复选项
  $0 list-backups --last 7      # 列出最近7天的备份
EOF
}

# 加载配置
load_config() {
    if [ -f "$CONFIG_FILE" ]; then
        source "$CONFIG_FILE"
    else
        log "⚠️ 配置文件不存在，使用默认配置"
    fi
}

# 安装备份系统
install_backup_system() {
    log "🚀 开始安装MySQL备份系统..."
    
    # 创建必要目录
    mkdir -p "$SCRIPT_DIR" "$LOG_DIR" "$(dirname "$CONFIG_FILE")"
    mkdir -p "$BACKUP_DIR" "$BACKUP_DIR/incremental"
    
    # 创建配置文件
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "$DEFAULT_CONFIG" > "$CONFIG_FILE"
        log "📝 创建配置文件: $CONFIG_FILE"
    fi
    
    # 复制脚本文件
    cp "mysql_full_backup.sh" "$SCRIPT_DIR/"
    cp "mysql_incremental_backup.sh" "$SCRIPT_DIR/"
    cp "mysql_recovery.sh" "$SCRIPT_DIR/"
    chmod +x "$SCRIPT_DIR"/*.sh
    
    # 创建crontab任务
    local cron_file="/tmp/mysql_backup_cron"
    cat > "$cron_file" << EOF
# MySQL自动备份任务
$FULL_BACKUP_SCHEDULE $SCRIPT_DIR/mysql_full_backup.sh
$INCREMENTAL_BACKUP_SCHEDULE $SCRIPT_DIR/mysql_incremental_backup.sh
EOF
    
    crontab "$cron_file"
    rm "$cron_file"
    
    # 生成加密密钥
    if [ ! -f "$ENCRYPTION_KEY" ]; then
        openssl rand -base64 32 > "$ENCRYPTION_KEY"
        chmod 600 "$ENCRYPTION_KEY"
        log "🔐 生成加密密钥: $ENCRYPTION_KEY"
    fi
    
    log "✅ MySQL备份系统安装完成"
    log "📋 请编辑配置文件: $CONFIG_FILE"
    log "🔑 请妥善保管加密密钥: $ENCRYPTION_KEY"
}

# 卸载备份系统
uninstall_backup_system() {
    log "🗑️ 开始卸载MySQL备份系统..."
    
    # 删除crontab任务
    crontab -l | grep -v "mysql_.*_backup.sh" | crontab -
    
    # 删除脚本文件
    rm -rf "$SCRIPT_DIR"
    
    log "✅ MySQL备份系统卸载完成"
    log "⚠️ 备份数据和配置文件已保留"
}

# 立即执行备份
backup_now() {
    local backup_type="$1"
    
    case "$backup_type" in
        "full")
            log "🚀 执行全量备份..."
            "$SCRIPT_DIR/mysql_full_backup.sh"
            ;;
        "incremental")
            log "🚀 执行增量备份..."
            "$SCRIPT_DIR/mysql_incremental_backup.sh"
            ;;
        *)
            error_exit "不支持的备份类型: $backup_type"
            ;;
    esac
}

# 列出备份
list_backups() {
    local days="${1:-30}"
    
    log "📋 最近 $days 天的备份列表:"
    
    echo "全量备份:"
    find "$BACKUP_DIR" -name "*.sql*" -mtime -"$days" -type f | sort -r | head -20
    
    echo "\n增量备份:"
    find "$BACKUP_DIR/incremental" -name "*.sql*" -mtime -"$days" -type f | sort -r | head -20
}

# 查看备份状态
show_status() {
    log "📊 MySQL备份系统状态:"
    
    # 检查crontab任务
    echo "定时任务状态:"
    crontab -l | grep "mysql_.*_backup.sh" || echo "未找到定时任务"
    
    # 检查最近的备份
    echo "\n最近的全量备份:"
    find "$BACKUP_DIR" -name "*.sql*" -mtime -7 -type f | sort -r | head -5
    
    echo "\n最近的增量备份:"
    find "$BACKUP_DIR/incremental" -name "*.sql*" -mtime -1 -type f | sort -r | head -5
    
    # 检查磁盘空间
    echo "\n备份目录磁盘使用情况:"
    du -sh "$BACKUP_DIR"
}

# 查看日志
show_logs() {
    local log_type="${1:-all}"
    local lines="${2:-50}"
    
    case "$log_type" in
        "full")
            tail -n "$lines" "/var/log/mysql_backup.log"
            ;;
        "incremental")
            tail -n "$lines" "/var/log/mysql_incremental_backup.log"
            ;;
        "recovery")
            tail -n "$lines" "/var/log/mysql_recovery.log"
            ;;
        "all")
            echo "=== 全量备份日志 ==="
            tail -n 20 "/var/log/mysql_backup.log" 2>/dev/null || echo "日志文件不存在"
            echo "\n=== 增量备份日志 ==="
            tail -n 20 "/var/log/mysql_incremental_backup.log" 2>/dev/null || echo "日志文件不存在"
            echo "\n=== 恢复日志 ==="
            tail -n 20 "/var/log/mysql_recovery.log" 2>/dev/null || echo "日志文件不存在"
            ;;
        *)
            error_exit "不支持的日志类型: $log_type"
            ;;
    esac
}

# 测试备份系统
test_backup_system() {
    log "🧪 测试MySQL备份系统..."
    
    # 测试数据库连接
    mysql -h"$MYSQL_HOST" -P"$MYSQL_PORT" -u"$MYSQL_USER" -p"$MYSQL_PASS" \
        -e "SELECT 1" >/dev/null 2>&1 || error_exit "数据库连接失败"
    log "✅ 数据库连接正常"
    
    # 测试备份目录权限
    touch "$BACKUP_DIR/test_file" && rm "$BACKUP_DIR/test_file" || error_exit "备份目录权限不足"
    log "✅ 备份目录权限正常"
    
    # 测试加密密钥
    if [ "$ENCRYPTION" = true ] && [ ! -f "$ENCRYPTION_KEY" ]; then
        error_exit "加密密钥文件不存在: $ENCRYPTION_KEY"
    fi
    log "✅ 加密配置正常"
    
    log "✅ 备份系统测试通过"
}

# 主函数
main() {
    local command="$1"
    shift
    
    # 创建日志目录
    mkdir -p "$LOG_DIR"
    
    case "$command" in
        "install")
            install_backup_system
            ;;
        "uninstall")
            uninstall_backup_system
            ;;
        "backup-now")
            load_config
            backup_now "${1:-full}"
            ;;
        "list-backups")
            load_config
            list_backups "$1"
            ;;
        "status")
            load_config
            show_status
            ;;
        "logs")
            show_logs "$1" "$2"
            ;;
        "test")
            load_config
            test_backup_system
            ;;
        "restore")
            load_config
            "$SCRIPT_DIR/mysql_recovery.sh" "$@"
            ;;
        "config")
            echo "配置文件位置: $CONFIG_FILE"
            if [ "$1" = "edit" ]; then
                ${EDITOR:-vi} "$CONFIG_FILE"
            fi
            ;;
        "help"|-h|--help)
            show_usage
            ;;
        *)
            echo "未知命令: $command"
            show_usage
            exit 1
            ;;
    esac
}

# 脚本入口
if [ $# -eq 0 ]; then
    show_usage
    exit 1
fi

main "$@"
```

---

## 5. 总结与最佳实践

### 5.1 核心优化要点

#### 慢查询优化
- **EXPLAIN分析**: 重点关注type、key、rows、Extra字段
- **索引设计**: 遵循最左前缀原则，避免过度索引
- **查询重写**: 避免SELECT *，合理使用LIMIT
- **统计信息**: 定期更新表统计信息

#### 主从同步优化
- **延迟监控**: 实时监控Seconds_Behind_Master
- **并行复制**: 启用基于LOGICAL_CLOCK的并行复制
- **半同步复制**: 保证数据一致性
- **读写分离**: 合理分配读写流量

#### 分库分表策略
- **分片键选择**: 选择分布均匀的字段作为分片键
- **路由算法**: 根据业务特点选择合适的分片算法
- **跨分片查询**: 尽量避免，必要时使用结果合并
- **数据迁移**: 制定完善的扩容方案

#### 备份恢复自动化
- **备份策略**: 全量+增量的组合备份策略
- **压缩加密**: 节省存储空间，保证数据安全
- **验证机制**: 定期验证备份文件完整性
- **恢复演练**: 定期进行恢复演练

### 5.2 生产环境建议

1. **监控告警**: 建立完善的监控告警体系
2. **容量规划**: 提前进行容量规划和扩容准备
3. **安全加固**: 实施数据库安全最佳实践
4. **文档管理**: 维护详细的运维文档
5. **团队培训**: 定期进行技术培训和演练

通过以上深度优化方案，可以显著提升MySQL数据库的性能、可用性和可维护性，为业务发展提供强有力的数据支撑。