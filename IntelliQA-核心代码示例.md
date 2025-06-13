# IntelliQA核心代码示例

## 项目结构

```
intelliqa/
├── cmd/
│   ├── api/           # API服务入口
│   ├── worker/        # 后台任务处理
│   └── migrate/       # 数据库迁移
├── internal/
│   ├── config/        # 配置管理
│   ├── models/        # 数据模型
│   ├── services/      # 业务逻辑
│   ├── handlers/      # HTTP处理器
│   ├── middleware/    # 中间件
│   └── utils/         # 工具函数
├── pkg/
│   ├── rag/          # RAG引擎
│   ├── vectordb/     # 向量数据库客户端
│   ├── llm/          # LLM客户端
│   └── cache/        # 缓存组件
├── configs/          # 配置文件
├── scripts/          # 部署脚本
├── docker-compose.yml
├── Dockerfile
├── go.mod
└── README.md
```

## 核心代码实现

### 1. 数据模型定义

```go
// internal/models/document.go
package models

import (
    "time"
    "github.com/google/uuid"
    "gorm.io/gorm"
)

// Document 文档模型
type Document struct {
    ID          uuid.UUID `gorm:"type:uuid;primary_key;default:gen_random_uuid()" json:"id"`
    Title       string    `gorm:"size:255;not null" json:"title"`
    Content     string    `gorm:"type:text" json:"content"`
    FileType    string    `gorm:"size:50" json:"file_type"`
    FilePath    string    `gorm:"size:500" json:"file_path"`
    FileSize    int64     `json:"file_size"`
    Status      string    `gorm:"size:20;default:'pending'" json:"status"` // pending, processing, completed, failed
    UserID      uuid.UUID `gorm:"type:uuid;not null" json:"user_id"`
    CreatedAt   time.Time `json:"created_at"`
    UpdatedAt   time.Time `json:"updated_at"`
    DeletedAt   gorm.DeletedAt `gorm:"index" json:"-"`
    
    // 关联
    Chunks      []Chunk   `gorm:"foreignKey:DocumentID" json:"chunks,omitempty"`
    User        User      `gorm:"foreignKey:UserID" json:"user,omitempty"`
}

// Chunk 文档分块模型
type Chunk struct {
    ID           uuid.UUID `gorm:"type:uuid;primary_key;default:gen_random_uuid()" json:"id"`
    DocumentID   uuid.UUID `gorm:"type:uuid;not null;index" json:"document_id"`
    Content      string    `gorm:"type:text;not null" json:"content"`
    TokenCount   int       `json:"token_count"`
    ChunkIndex   int       `json:"chunk_index"`
    StartPos     int       `json:"start_pos"`
    EndPos       int       `json:"end_pos"`
    VectorID     string    `gorm:"size:100;index" json:"vector_id"` // Milvus中的向量ID
    Metadata     JSON      `gorm:"type:jsonb" json:"metadata"`
    CreatedAt    time.Time `json:"created_at"`
    
    // 关联
    Document     Document  `gorm:"foreignKey:DocumentID" json:"document,omitempty"`
}

// ChatSession 对话会话模型
type ChatSession struct {
    ID          uuid.UUID `gorm:"type:uuid;primary_key;default:gen_random_uuid()" json:"id"`
    UserID      uuid.UUID `gorm:"type:uuid;not null;index" json:"user_id"`
    Title       string    `gorm:"size:255" json:"title"`
    Status      string    `gorm:"size:20;default:'active'" json:"status"` // active, archived
    CreatedAt   time.Time `json:"created_at"`
    UpdatedAt   time.Time `json:"updated_at"`
    
    // 关联
    Messages    []Message `gorm:"foreignKey:SessionID" json:"messages,omitempty"`
    User        User      `gorm:"foreignKey:UserID" json:"user,omitempty"`
}

// Message 消息模型
type Message struct {
    ID          uuid.UUID `gorm:"type:uuid;primary_key;default:gen_random_uuid()" json:"id"`
    SessionID   uuid.UUID `gorm:"type:uuid;not null;index" json:"session_id"`
    Role        string    `gorm:"size:20;not null" json:"role"` // user, assistant
    Content     string    `gorm:"type:text;not null" json:"content"`
    Sources     JSON      `gorm:"type:jsonb" json:"sources"`
    Metadata    JSON      `gorm:"type:jsonb" json:"metadata"`
    TokenUsage  JSON      `gorm:"type:jsonb" json:"token_usage"`
    CreatedAt   time.Time `json:"created_at"`
    
    // 关联
    Session     ChatSession `gorm:"foreignKey:SessionID" json:"session,omitempty"`
}

// User 用户模型
type User struct {
    ID          uuid.UUID `gorm:"type:uuid;primary_key;default:gen_random_uuid()" json:"id"`
    Username    string    `gorm:"size:50;uniqueIndex;not null" json:"username"`
    Email       string    `gorm:"size:100;uniqueIndex;not null" json:"email"`
    PasswordHash string   `gorm:"size:255;not null" json:"-"`
    Role        string    `gorm:"size:20;default:'user'" json:"role"` // admin, user
    Status      string    `gorm:"size:20;default:'active'" json:"status"` // active, inactive
    CreatedAt   time.Time `json:"created_at"`
    UpdatedAt   time.Time `json:"updated_at"`
}

// JSON 自定义JSON类型
type JSON map[string]interface{}
```

### 2. RAG引擎核心实现

```go
// pkg/rag/engine.go
package rag

import (
    "context"
    "fmt"
    "sort"
    "strings"
    "time"
    
    "github.com/intelliqa/internal/models"
    "github.com/intelliqa/pkg/llm"
    "github.com/intelliqa/pkg/vectordb"
    "go.uber.org/zap"
)

// Engine RAG引擎
type Engine struct {
    vectorDB    vectordb.Client
    llmClient   llm.Client
    retriever   Retriever
    promptMgr   *PromptManager
    config      *Config
    logger      *zap.Logger
    metrics     *Metrics
}

// Config RAG引擎配置
type Config struct {
    MaxChunks       int     `yaml:"max_chunks"`
    MaxTokens       int     `yaml:"max_tokens"`
    Temperature     float64 `yaml:"temperature"`
    TopP            float64 `yaml:"top_p"`
    VectorWeight    float64 `yaml:"vector_weight"`
    KeywordWeight   float64 `yaml:"keyword_weight"`
    RerankThreshold float64 `yaml:"rerank_threshold"`
}

// RetrievalResult 检索结果
type RetrievalResult struct {
    Chunks        []models.Chunk `json:"chunks"`
    TotalFound    int            `json:"total_found"`
    RetrievalTime time.Duration  `json:"retrieval_time"`
    Query         string         `json:"query"`
    ExpandedQuery []string       `json:"expanded_query"`
}

// GenerationResult 生成结果
type GenerationResult struct {
    Answer      string                 `json:"answer"`
    Sources     []SourceInfo          `json:"sources"`
    Confidence  float64               `json:"confidence"`
    TokenUsage  llm.TokenUsage        `json:"token_usage"`
    Metadata    map[string]interface{} `json:"metadata"`
}

// SourceInfo 来源信息
type SourceInfo struct {
    DocumentID   string  `json:"document_id"`
    DocumentTitle string `json:"document_title"`
    ChunkID      string  `json:"chunk_id"`
    Content      string  `json:"content"`
    Score        float64 `json:"score"`
    Page         int     `json:"page,omitempty"`
}

// NewEngine 创建RAG引擎
func NewEngine(vectorDB vectordb.Client, llmClient llm.Client, config *Config, logger *zap.Logger) *Engine {
    return &Engine{
        vectorDB:  vectorDB,
        llmClient: llmClient,
        retriever: NewHybridRetriever(vectorDB, config),
        promptMgr: NewPromptManager(),
        config:    config,
        logger:    logger,
        metrics:   NewMetrics(),
    }
}

// Retrieve 检索相关文档
func (e *Engine) Retrieve(ctx context.Context, query string) (*RetrievalResult, error) {
    start := time.Now()
    
    // 记录指标
    defer func() {
        e.metrics.RetrievalDuration.Observe(time.Since(start).Seconds())
    }()
    
    // 查询扩展
    expandedQueries := e.expandQuery(query)
    
    // 混合检索
    chunks, err := e.retriever.Retrieve(ctx, query, expandedQueries, e.config.MaxChunks)
    if err != nil {
        e.logger.Error("检索失败", zap.Error(err), zap.String("query", query))
        return nil, fmt.Errorf("检索失败: %w", err)
    }
    
    // 重排序
    rerankedChunks := e.rerank(query, chunks)
    
    return &RetrievalResult{
        Chunks:        rerankedChunks,
        TotalFound:    len(chunks),
        RetrievalTime: time.Since(start),
        Query:         query,
        ExpandedQuery: expandedQueries,
    }, nil
}

// Generate 生成回答
func (e *Engine) Generate(ctx context.Context, query string, retrieval *RetrievalResult) (*GenerationResult, error) {
    start := time.Now()
    
    // 记录指标
    defer func() {
        e.metrics.LLMRequests.Inc()
        e.metrics.GenerationDuration.Observe(time.Since(start).Seconds())
    }()
    
    // 构建提示词
    prompt := e.promptMgr.BuildRAGPrompt(query, retrieval.Chunks)
    
    // 调用LLM
    response, err := e.llmClient.Generate(ctx, &llm.GenerateRequest{
        Messages: []llm.Message{
            {Role: "user", Content: prompt},
        },
        MaxTokens:   e.config.MaxTokens,
        Temperature: e.config.Temperature,
        TopP:        e.config.TopP,
    })
    if err != nil {
        e.logger.Error("LLM生成失败", zap.Error(err))
        return nil, fmt.Errorf("生成回答失败: %w", err)
    }
    
    // 记录token使用量
    e.metrics.TokenUsage.Add(float64(response.TokenUsage.TotalTokens))
    
    // 构建来源信息
    sources := e.buildSources(retrieval.Chunks)
    
    // 计算置信度
    confidence := e.calculateConfidence(response.Content, retrieval.Chunks)
    
    return &GenerationResult{
        Answer:     response.Content,
        Sources:    sources,
        Confidence: confidence,
        TokenUsage: response.TokenUsage,
        Metadata: map[string]interface{}{
            "model":           response.Model,
            "retrieval_time": retrieval.RetrievalTime.Milliseconds(),
            "generation_time": time.Since(start).Milliseconds(),
            "chunks_used":     len(retrieval.Chunks),
        },
    }, nil
}

// Chat 对话接口
func (e *Engine) Chat(ctx context.Context, query string, history []models.Message) (*GenerationResult, error) {
    // 检索相关文档
    retrieval, err := e.Retrieve(ctx, query)
    if err != nil {
        return nil, err
    }
    
    // 构建对话提示词
    prompt := e.promptMgr.BuildChatPrompt(query, history, retrieval.Chunks)
    
    // 生成回答
    response, err := e.llmClient.Generate(ctx, &llm.GenerateRequest{
        Messages: []llm.Message{
            {Role: "user", Content: prompt},
        },
        MaxTokens:   e.config.MaxTokens,
        Temperature: e.config.Temperature,
        TopP:        e.config.TopP,
    })
    if err != nil {
        return nil, fmt.Errorf("对话生成失败: %w", err)
    }
    
    // 构建结果
    sources := e.buildSources(retrieval.Chunks)
    confidence := e.calculateConfidence(response.Content, retrieval.Chunks)
    
    return &GenerationResult{
        Answer:     response.Content,
        Sources:    sources,
        Confidence: confidence,
        TokenUsage: response.TokenUsage,
        Metadata: map[string]interface{}{
            "model":           response.Model,
            "retrieval_time": retrieval.RetrievalTime.Milliseconds(),
            "chunks_used":     len(retrieval.Chunks),
            "history_length":  len(history),
        },
    }, nil
}

// expandQuery 查询扩展
func (e *Engine) expandQuery(query string) []string {
    // 简化实现，实际可以使用同义词词典、LLM重写等
    expanded := []string{query}
    
    // 添加一些简单的扩展策略
    words := strings.Fields(query)
    if len(words) > 1 {
        // 添加部分词组合
        for i := 0; i < len(words)-1; i++ {
            expanded = append(expanded, words[i]+" "+words[i+1])
        }
    }
    
    return expanded
}

// rerank 重排序
func (e *Engine) rerank(query string, chunks []models.Chunk) []models.Chunk {
    // 简化实现，实际可以使用CrossEncoder等重排序模型
    
    type scoredChunk struct {
        chunk models.Chunk
        score float64
    }
    
    scored := make([]scoredChunk, len(chunks))
    queryLower := strings.ToLower(query)
    
    for i, chunk := range chunks {
        contentLower := strings.ToLower(chunk.Content)
        
        // 简单的TF-IDF相似度计算
        score := e.calculateTFIDF(queryLower, contentLower)
        
        scored[i] = scoredChunk{
            chunk: chunk,
            score: score,
        }
    }
    
    // 按分数排序
    sort.Slice(scored, func(i, j int) bool {
        return scored[i].score > scored[j].score
    })
    
    // 提取排序后的chunks
    result := make([]models.Chunk, len(scored))
    for i, sc := range scored {
        result[i] = sc.chunk
    }
    
    return result
}

// calculateTFIDF 计算TF-IDF相似度（简化版）
func (e *Engine) calculateTFIDF(query, content string) float64 {
    queryWords := strings.Fields(query)
    contentWords := strings.Fields(content)
    
    if len(queryWords) == 0 || len(contentWords) == 0 {
        return 0.0
    }
    
    // 计算词频
    contentWordCount := make(map[string]int)
    for _, word := range contentWords {
        contentWordCount[word]++
    }
    
    // 计算匹配分数
    matches := 0
    for _, word := range queryWords {
        if count, exists := contentWordCount[word]; exists {
            matches += count
        }
    }
    
    return float64(matches) / float64(len(contentWords))
}

// buildSources 构建来源信息
func (e *Engine) buildSources(chunks []models.Chunk) []SourceInfo {
    sources := make([]SourceInfo, len(chunks))
    
    for i, chunk := range chunks {
        sources[i] = SourceInfo{
            DocumentID:   chunk.DocumentID.String(),
            ChunkID:      chunk.ID.String(),
            Content:      chunk.Content,
            Score:        1.0, // 实际应该从检索结果中获取
        }
        
        // 从metadata中提取额外信息
        if chunk.Metadata != nil {
            if title, ok := chunk.Metadata["title"].(string); ok {
                sources[i].DocumentTitle = title
            }
            if page, ok := chunk.Metadata["page"].(float64); ok {
                sources[i].Page = int(page)
            }
        }
    }
    
    return sources
}

// calculateConfidence 计算置信度
func (e *Engine) calculateConfidence(answer string, chunks []models.Chunk) float64 {
    if len(chunks) == 0 {
        return 0.0
    }
    
    // 简化的置信度计算
    // 实际可以使用更复杂的算法，如基于语义相似度、覆盖度等
    
    answerWords := strings.Fields(strings.ToLower(answer))
    if len(answerWords) == 0 {
        return 0.0
    }
    
    totalMatches := 0
    for _, chunk := range chunks {
        chunkWords := strings.Fields(strings.ToLower(chunk.Content))
        chunkWordSet := make(map[string]bool)
        for _, word := range chunkWords {
            chunkWordSet[word] = true
        }
        
        matches := 0
        for _, word := range answerWords {
            if chunkWordSet[word] {
                matches++
            }
        }
        totalMatches += matches
    }
    
    confidence := float64(totalMatches) / float64(len(answerWords) * len(chunks))
    if confidence > 1.0 {
        confidence = 1.0
    }
    
    return confidence
}
```

### 3. 混合检索器实现

```go
// pkg/rag/retriever.go
package rag

import (
    "context"
    "fmt"
    "sort"
    
    "github.com/intelliqa/internal/models"
    "github.com/intelliqa/pkg/vectordb"
)

// Retriever 检索器接口
type Retriever interface {
    Retrieve(ctx context.Context, query string, expandedQueries []string, maxChunks int) ([]models.Chunk, error)
}

// HybridRetriever 混合检索器
type HybridRetriever struct {
    vectorDB       vectordb.Client
    keywordSearch  KeywordSearcher
    config         *Config
}

// KeywordSearcher 关键词搜索接口
type KeywordSearcher interface {
    Search(ctx context.Context, query string, limit int) ([]models.Chunk, error)
}

// NewHybridRetriever 创建混合检索器
func NewHybridRetriever(vectorDB vectordb.Client, config *Config) *HybridRetriever {
    return &HybridRetriever{
        vectorDB:      vectorDB,
        keywordSearch: NewElasticsearchSearcher(), // 假设使用Elasticsearch
        config:        config,
    }
}

// Retrieve 执行混合检索
func (r *HybridRetriever) Retrieve(ctx context.Context, query string, expandedQueries []string, maxChunks int) ([]models.Chunk, error) {
    // 并行执行向量检索和关键词检索
    vectorChan := make(chan []models.Chunk, 1)
    keywordChan := make(chan []models.Chunk, 1)
    errorChan := make(chan error, 2)
    
    // 向量检索
    go func() {
        chunks, err := r.vectorSearch(ctx, query, maxChunks)
        if err != nil {
            errorChan <- fmt.Errorf("向量检索失败: %w", err)
            return
        }
        vectorChan <- chunks
    }()
    
    // 关键词检索
    go func() {
        chunks, err := r.keywordSearch.Search(ctx, query, maxChunks)
        if err != nil {
            errorChan <- fmt.Errorf("关键词检索失败: %w", err)
            return
        }
        keywordChan <- chunks
    }()
    
    // 收集结果
    var vectorResults, keywordResults []models.Chunk
    var vectorErr, keywordErr error
    
    for i := 0; i < 2; i++ {
        select {
        case chunks := <-vectorChan:
            vectorResults = chunks
        case chunks := <-keywordChan:
            keywordResults = chunks
        case err := <-errorChan:
            if vectorErr == nil {
                vectorErr = err
            } else {
                keywordErr = err
            }
        }
    }
    
    // 如果两个检索都失败，返回错误
    if vectorErr != nil && keywordErr != nil {
        return nil, fmt.Errorf("检索失败: vector=%v, keyword=%v", vectorErr, keywordErr)
    }
    
    // 融合结果
    fusedResults := r.fuseResults(vectorResults, keywordResults)
    
    // 限制返回数量
    if len(fusedResults) > maxChunks {
        fusedResults = fusedResults[:maxChunks]
    }
    
    return fusedResults, nil
}

// vectorSearch 向量检索
func (r *HybridRetriever) vectorSearch(ctx context.Context, query string, limit int) ([]models.Chunk, error) {
    // 生成查询向量
    queryVector, err := r.vectorDB.Embed(ctx, query)
    if err != nil {
        return nil, fmt.Errorf("生成查询向量失败: %w", err)
    }
    
    // 向量检索
    results, err := r.vectorDB.Search(ctx, &vectordb.SearchRequest{
        Vector:     queryVector,
        TopK:       limit,
        Collection: "chunks",
    })
    if err != nil {
        return nil, fmt.Errorf("向量检索失败: %w", err)
    }
    
    // 转换为Chunk模型
    chunks := make([]models.Chunk, len(results.Hits))
    for i, hit := range results.Hits {
        chunks[i] = models.Chunk{
            ID:      hit.ID,
            Content: hit.Content,
            // 其他字段从hit.Metadata中提取
        }
    }
    
    return chunks, nil
}

// fuseResults 融合检索结果（RRF算法）
func (r *HybridRetriever) fuseResults(vectorResults, keywordResults []models.Chunk) []models.Chunk {
    const k = 60 // RRF参数
    
    scoreMap := make(map[string]*fusedChunk)
    
    // 处理向量检索结果
    for rank, chunk := range vectorResults {
        id := chunk.ID.String()
        if _, exists := scoreMap[id]; !exists {
            scoreMap[id] = &fusedChunk{
                chunk: chunk,
                score: 0,
            }
        }
        scoreMap[id].score += r.config.VectorWeight / float64(rank+k)
    }
    
    // 处理关键词检索结果
    for rank, chunk := range keywordResults {
        id := chunk.ID.String()
        if _, exists := scoreMap[id]; !exists {
            scoreMap[id] = &fusedChunk{
                chunk: chunk,
                score: 0,
            }
        }
        scoreMap[id].score += r.config.KeywordWeight / float64(rank+k)
    }
    
    // 转换为切片并排序
    fusedSlice := make([]*fusedChunk, 0, len(scoreMap))
    for _, fc := range scoreMap {
        fusedSlice = append(fusedSlice, fc)
    }
    
    sort.Slice(fusedSlice, func(i, j int) bool {
        return fusedSlice[i].score > fusedSlice[j].score
    })
    
    // 提取最终结果
    result := make([]models.Chunk, len(fusedSlice))
    for i, fc := range fusedSlice {
        result[i] = fc.chunk
    }
    
    return result
}

type fusedChunk struct {
    chunk models.Chunk
    score float64
}
```

### 4. 文档处理服务

```go
// internal/services/document_service.go
package services

import (
    "context"
    "fmt"
    "io"
    "path/filepath"
    "strings"
    "time"
    
    "github.com/google/uuid"
    "github.com/intelliqa/internal/models"
    "github.com/intelliqa/pkg/rag"
    "github.com/intelliqa/pkg/vectordb"
    "go.uber.org/zap"
    "gorm.io/gorm"
)

// DocumentService 文档服务
type DocumentService struct {
    db          *gorm.DB
    vectorDB    vectordb.Client
    parser      DocumentParser
    chunker     TextChunker
    embedder    Embedder
    logger      *zap.Logger
    taskQueue   chan *ProcessTask
}

// DocumentParser 文档解析器接口
type DocumentParser interface {
    Parse(reader io.Reader, fileType string) (*ParsedDocument, error)
    SupportedTypes() []string
}

// TextChunker 文本分块器接口
type TextChunker interface {
    Chunk(text string, metadata map[string]interface{}) ([]ChunkData, error)
}

// Embedder 向量化器接口
type Embedder interface {
    Embed(ctx context.Context, text string) ([]float32, error)
    EmbedBatch(ctx context.Context, texts []string) ([][]float32, error)
}

// ProcessTask 处理任务
type ProcessTask struct {
    DocumentID uuid.UUID
    FilePath   string
    FileType   string
    UserID     uuid.UUID
}

// ParsedDocument 解析后的文档
type ParsedDocument struct {
    Content  string
    Metadata map[string]interface{}
}

// ChunkData 分块数据
type ChunkData struct {
    Content    string
    TokenCount int
    Index      int
    Metadata   map[string]interface{}
}

// NewDocumentService 创建文档服务
func NewDocumentService(db *gorm.DB, vectorDB vectordb.Client, logger *zap.Logger) *DocumentService {
    service := &DocumentService{
        db:        db,
        vectorDB:  vectorDB,
        parser:    NewMultiFormatParser(),
        chunker:   NewSemanticChunker(),
        embedder:  NewOpenAIEmbedder(),
        logger:    logger,
        taskQueue: make(chan *ProcessTask, 1000),
    }
    
    // 启动后台处理器
    go service.processWorker()
    
    return service
}

// UploadDocument 上传文档
func (s *DocumentService) UploadDocument(ctx context.Context, reader io.Reader, filename string, userID uuid.UUID) (*models.Document, error) {
    // 检测文件类型
    fileType := s.detectFileType(filename)
    if !s.isSupportedType(fileType) {
        return nil, fmt.Errorf("不支持的文件类型: %s", fileType)
    }
    
    // 保存文件
    filePath, fileSize, err := s.saveFile(reader, filename)
    if err != nil {
        return nil, fmt.Errorf("保存文件失败: %w", err)
    }
    
    // 创建文档记录
    document := &models.Document{
        ID:       uuid.New(),
        Title:    s.extractTitle(filename),
        FileType: fileType,
        FilePath: filePath,
        FileSize: fileSize,
        Status:   "pending",
        UserID:   userID,
    }
    
    if err := s.db.Create(document).Error; err != nil {
        return nil, fmt.Errorf("创建文档记录失败: %w", err)
    }
    
    // 提交处理任务
    task := &ProcessTask{
        DocumentID: document.ID,
        FilePath:   filePath,
        FileType:   fileType,
        UserID:     userID,
    }
    
    select {
    case s.taskQueue <- task:
        s.logger.Info("文档处理任务已提交", zap.String("document_id", document.ID.String()))
    default:
        s.logger.Warn("任务队列已满，稍后重试", zap.String("document_id", document.ID.String()))
        // 可以考虑使用持久化队列（如Redis、Kafka）
    }
    
    return document, nil
}

// processWorker 后台处理器
func (s *DocumentService) processWorker() {
    for task := range s.taskQueue {
        if err := s.processDocument(context.Background(), task); err != nil {
            s.logger.Error("文档处理失败", 
                zap.String("document_id", task.DocumentID.String()),
                zap.Error(err))
            
            // 更新文档状态为失败
            s.db.Model(&models.Document{}).Where("id = ?", task.DocumentID).Update("status", "failed")
        }
    }
}

// processDocument 处理文档
func (s *DocumentService) processDocument(ctx context.Context, task *ProcessTask) error {
    // 更新状态为处理中
    if err := s.db.Model(&models.Document{}).Where("id = ?", task.DocumentID).Update("status", "processing").Error; err != nil {
        return fmt.Errorf("更新文档状态失败: %w", err)
    }
    
    // 1. 解析文档
    file, err := s.openFile(task.FilePath)
    if err != nil {
        return fmt.Errorf("打开文件失败: %w", err)
    }
    defer file.Close()
    
    parsed, err := s.parser.Parse(file, task.FileType)
    if err != nil {
        return fmt.Errorf("解析文档失败: %w", err)
    }
    
    // 2. 文本分块
    chunks, err := s.chunker.Chunk(parsed.Content, parsed.Metadata)
    if err != nil {
        return fmt.Errorf("文本分块失败: %w", err)
    }
    
    // 3. 批量向量化
    texts := make([]string, len(chunks))
    for i, chunk := range chunks {
        texts[i] = chunk.Content
    }
    
    vectors, err := s.embedder.EmbedBatch(ctx, texts)
    if err != nil {
        return fmt.Errorf("向量化失败: %w", err)
    }
    
    // 4. 保存到数据库和向量数据库
    tx := s.db.Begin()
    defer func() {
        if r := recover(); r != nil {
            tx.Rollback()
        }
    }()
    
    for i, chunk := range chunks {
        // 创建分块记录
        chunkModel := &models.Chunk{
            ID:         uuid.New(),
            DocumentID: task.DocumentID,
            Content:    chunk.Content,
            TokenCount: chunk.TokenCount,
            ChunkIndex: chunk.Index,
            Metadata:   chunk.Metadata,
        }
        
        if err := tx.Create(chunkModel).Error; err != nil {
            tx.Rollback()
            return fmt.Errorf("保存分块失败: %w", err)
        }
        
        // 保存到向量数据库
        vectorID, err := s.vectorDB.Insert(ctx, &vectordb.InsertRequest{
            ID:         chunkModel.ID.String(),
            Vector:     vectors[i],
            Content:    chunk.Content,
            Metadata:   chunk.Metadata,
            Collection: "chunks",
        })
        if err != nil {
            tx.Rollback()
            return fmt.Errorf("保存向量失败: %w", err)
        }
        
        // 更新向量ID
        chunkModel.VectorID = vectorID
        if err := tx.Save(chunkModel).Error; err != nil {
            tx.Rollback()
            return fmt.Errorf("更新向量ID失败: %w", err)
        }
    }
    
    // 更新文档状态和内容
    if err := tx.Model(&models.Document{}).Where("id = ?", task.DocumentID).Updates(map[string]interface{}{
        "status":  "completed",
        "content": parsed.Content,
    }).Error; err != nil {
        tx.Rollback()
        return fmt.Errorf("更新文档状态失败: %w", err)
    }
    
    if err := tx.Commit().Error; err != nil {
        return fmt.Errorf("提交事务失败: %w", err)
    }
    
    s.logger.Info("文档处理完成", 
        zap.String("document_id", task.DocumentID.String()),
        zap.Int("chunks_count", len(chunks)))
    
    return nil
}

// 辅助方法
func (s *DocumentService) detectFileType(filename string) string {
    ext := strings.ToLower(filepath.Ext(filename))
    switch ext {
    case ".pdf":
        return "pdf"
    case ".docx":
        return "docx"
    case ".txt":
        return "txt"
    case ".md":
        return "markdown"
    default:
        return "unknown"
    }
}

func (s *DocumentService) isSupportedType(fileType string) bool {
    supportedTypes := s.parser.SupportedTypes()
    for _, t := range supportedTypes {
        if t == fileType {
            return true
        }
    }
    return false
}

func (s *DocumentService) extractTitle(filename string) string {
    name := filepath.Base(filename)
    ext := filepath.Ext(name)
    return strings.TrimSuffix(name, ext)
}

func (s *DocumentService) saveFile(reader io.Reader, filename string) (string, int64, error) {
    // 实现文件保存逻辑
    // 返回文件路径和大小
    return "/path/to/saved/file", 0, nil
}

func (s *DocumentService) openFile(filePath string) (io.ReadCloser, error) {
    // 实现文件打开逻辑
    return nil, nil
}
```

### 5. HTTP处理器

```go
// internal/handlers/chat_handler.go
package handlers

import (
    "encoding/json"
    "net/http"
    "strconv"
    
    "github.com/gin-gonic/gin"
    "github.com/google/uuid"
    "github.com/intelliqa/internal/models"
    "github.com/intelliqa/internal/services"
    "github.com/intelliqa/pkg/rag"
    "go.uber.org/zap"
)

// ChatHandler 对话处理器
type ChatHandler struct {
    chatService *services.ChatService
    ragEngine   *rag.Engine
    logger      *zap.Logger
}

// ChatRequest 对话请求
type ChatRequest struct {
    Message   string    `json:"message" binding:"required"`
    SessionID uuid.UUID `json:"session_id,omitempty"`
    Stream    bool      `json:"stream,omitempty"`
}

// ChatResponse 对话响应
type ChatResponse struct {
    SessionID  uuid.UUID           `json:"session_id"`
    MessageID  uuid.UUID           `json:"message_id"`
    Answer     string              `json:"answer"`
    Sources    []rag.SourceInfo    `json:"sources"`
    Confidence float64             `json:"confidence"`
    Metadata   map[string]interface{} `json:"metadata"`
}

// NewChatHandler 创建对话处理器
func NewChatHandler(chatService *services.ChatService, ragEngine *rag.Engine, logger *zap.Logger) *ChatHandler {
    return &ChatHandler{
        chatService: chatService,
        ragEngine:   ragEngine,
        logger:      logger,
    }
}

// Chat 处理对话请求
func (h *ChatHandler) Chat(c *gin.Context) {
    var req ChatRequest
    if err := c.ShouldBindJSON(&req); err != nil {
        c.JSON(http.StatusBadRequest, gin.H{"error": "无效的请求参数"})
        return
    }
    
    // 获取用户ID
    userID, exists := c.Get("user_id")
    if !exists {
        c.JSON(http.StatusUnauthorized, gin.H{"error": "未授权"})
        return
    }
    
    userUUID, ok := userID.(uuid.UUID)
    if !ok {
        c.JSON(http.StatusInternalServerError, gin.H{"error": "用户ID格式错误"})
        return
    }
    
    // 处理流式响应
    if req.Stream {
        h.handleStreamChat(c, &req, userUUID)
        return
    }
    
    // 处理普通对话
    response, err := h.chatService.Chat(c.Request.Context(), &services.ChatRequest{
        UserID:    userUUID,
        SessionID: req.SessionID,
        Message:   req.Message,
    })
    if err != nil {
        h.logger.Error("对话处理失败", zap.Error(err))
        c.JSON(http.StatusInternalServerError, gin.H{"error": "对话处理失败"})
        return
    }
    
    c.JSON(http.StatusOK, ChatResponse{
        SessionID:  response.SessionID,
        MessageID:  response.MessageID,
        Answer:     response.Answer,
        Sources:    response.Sources,
        Confidence: response.Confidence,
        Metadata:   response.Metadata,
    })
}

// handleStreamChat 处理流式对话
func (h *ChatHandler) handleStreamChat(c *gin.Context, req *ChatRequest, userID uuid.UUID) {
    // 设置SSE头
    c.Header("Content-Type", "text/event-stream")
    c.Header("Cache-Control", "no-cache")
    c.Header("Connection", "keep-alive")
    c.Header("Access-Control-Allow-Origin", "*")
    
    // 创建流式响应通道
    responseChan := make(chan *services.StreamChatResponse, 10)
    
    // 启动流式对话
    go func() {
        defer close(responseChan)
        
        err := h.chatService.StreamChat(c.Request.Context(), &services.ChatRequest{
            UserID:    userID,
            SessionID: req.SessionID,
            Message:   req.Message,
        }, responseChan)
        
        if err != nil {
            h.logger.Error("流式对话失败", zap.Error(err))
            responseChan <- &services.StreamChatResponse{
                Type:  "error",
                Error: err.Error(),
            }
        }
    }()
    
    // 发送流式响应
    for response := range responseChan {
        data, _ := json.Marshal(response)
        c.SSEvent("message", string(data))
        c.Writer.Flush()
    }
}

// GetChatHistory 获取对话历史
func (h *ChatHandler) GetChatHistory(c *gin.Context) {
    sessionIDStr := c.Param("session_id")
    sessionID, err := uuid.Parse(sessionIDStr)
    if err != nil {
        c.JSON(http.StatusBadRequest, gin.H{"error": "无效的会话ID"})
        return
    }
    
    // 获取分页参数
    page, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
    limit, _ := strconv.Atoi(c.DefaultQuery("limit", "20"))
    
    history, total, err := h.chatService.GetChatHistory(c.Request.Context(), sessionID, page, limit)
    if err != nil {
        h.logger.Error("获取对话历史失败", zap.Error(err))
        c.JSON(http.StatusInternalServerError, gin.H{"error": "获取对话历史失败"})
        return
    }
    
    c.JSON(http.StatusOK, gin.H{
        "messages": history,
        "total":    total,
        "page":     page,
        "limit":    limit,
    })
}

// CreateSession 创建新会话
func (h *ChatHandler) CreateSession(c *gin.Context) {
    userID, exists := c.Get("user_id")
    if !exists {
        c.JSON(http.StatusUnauthorized, gin.H{"error": "未授权"})
        return
    }
    
    userUUID, ok := userID.(uuid.UUID)
    if !ok {
        c.JSON(http.StatusInternalServerError, gin.H{"error": "用户ID格式错误"})
        return
    }
    
    var req struct {
        Title string `json:"title"`
    }
    
    if err := c.ShouldBindJSON(&req); err != nil {
        c.JSON(http.StatusBadRequest, gin.H{"error": "无效的请求参数"})
        return
    }
    
    session, err := h.chatService.CreateSession(c.Request.Context(), userUUID, req.Title)
    if err != nil {
        h.logger.Error("创建会话失败", zap.Error(err))
        c.JSON(http.StatusInternalServerError, gin.H{"error": "创建会话失败"})
        return
    }
    
    c.JSON(http.StatusCreated, session)
}
```

### 6. 配置文件示例

```yaml
# configs/config.yaml
server:
  host: "0.0.0.0"
  port: 8080
  mode: "debug" # debug, release

database:
  postgres:
    host: "localhost"
    port: 5432
    user: "intelliqa"
    password: "password"
    dbname: "intelliqa"
    sslmode: "disable"
    max_open_conns: 100
    max_idle_conns: 10
    conn_max_lifetime: "1h"
  
  redis:
    addr: "localhost:6379"
    password: ""
    db: 0
    pool_size: 100
    min_idle_conns: 10

vectordb:
  milvus:
    host: "localhost"
    port: 19530
    collection: "chunks"
    dimension: 1536
    metric_type: "COSINE"
    index_type: "HNSW"
    index_params:
      M: 16
      efConstruction: 200
    search_params:
      ef: 100

llm:
  openai:
    api_key: "${OPENAI_API_KEY}"
    base_url: "https://api.openai.com/v1"
    model: "gpt-3.5-turbo"
    embedding_model: "text-embedding-ada-002"
    max_tokens: 2048
    temperature: 0.7
    timeout: "30s"

rag:
  max_chunks: 5
  max_tokens: 2048
  temperature: 0.7
  top_p: 0.9
  vector_weight: 0.7
  keyword_weight: 0.3
  rerank_threshold: 0.5

logging:
  level: "info"
  format: "json"
  output: "stdout"

monitoring:
  prometheus:
    enabled: true
    port: 9090
  jaeger:
    enabled: true
    endpoint: "http://localhost:14268/api/traces"

security:
  jwt:
    secret: "${JWT_SECRET}"
    expires_in: "24h"
  cors:
    allowed_origins: ["*"]
    allowed_methods: ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    allowed_headers: ["*"]
```

### 7. Docker Compose配置

```yaml
# docker-compose.yml
version: '3.8'

services:
  # API服务
  api:
    build: .
    ports:
      - "8080:8080"
    environment:
      - CONFIG_PATH=/app/configs/config.yaml
      - POSTGRES_HOST=postgres
      - REDIS_HOST=redis
      - MILVUS_HOST=milvus
      - ELASTICSEARCH_HOST=elasticsearch
    depends_on:
      - postgres
      - redis
      - milvus
      - elasticsearch
    volumes:
      - ./configs:/app/configs
      - ./uploads:/app/uploads

  # PostgreSQL数据库
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: intelliqa
      POSTGRES_USER: intelliqa
      POSTGRES_PASSWORD: password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  # Redis缓存
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  # Milvus向量数据库
  etcd:
    image: quay.io/coreos/etcd:v3.5.5
    environment:
      - ETCD_AUTO_COMPACTION_MODE=revision
      - ETCD_AUTO_COMPACTION_RETENTION=1000
      - ETCD_QUOTA_BACKEND_BYTES=4294967296
      - ETCD_SNAPSHOT_COUNT=50000
    volumes:
      - etcd_data:/etcd
    command: etcd -advertise-client-urls=http://127.0.0.1:2379 -listen-client-urls http://0.0.0.0:2379 --data-dir /etcd

  minio:
    image: minio/minio:RELEASE.2023-03-20T20-16-18Z
    environment:
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    ports:
      - "9001:9001"
      - "9000:9000"
    volumes:
      - minio_data:/data
    command: minio server /data --console-address ":9001"

  milvus:
    image: milvusdb/milvus:v2.3.0
    command: ["milvus", "run", "standalone"]
    environment:
      ETCD_ENDPOINTS: etcd:2379
      MINIO_ADDRESS: minio:9000
    volumes:
      - milvus_data:/var/lib/milvus
    ports:
      - "19530:19530"
    depends_on:
      - "etcd"
      - "minio"

  # Elasticsearch
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.8.0
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
      - "ES_JAVA_OPTS=-Xms512m -Xmx512m"
    ports:
      - "9200:9200"
    volumes:
      - elasticsearch_data:/usr/share/elasticsearch/data

  # Kafka
  zookeeper:
    image: confluentinc/cp-zookeeper:7.4.0
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
      ZOOKEEPER_TICK_TIME: 2000
    volumes:
      - zookeeper_data:/var/lib/zookeeper/data

  kafka:
    image: confluentinc/cp-kafka:7.4.0
    depends_on:
      - zookeeper
    ports:
      - "9092:9092"
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
    volumes:
      - kafka_data:/var/lib/kafka/data

  # 监控
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana_data:/var/lib/grafana
      - ./monitoring/grafana:/etc/grafana/provisioning

volumes:
  postgres_data:
  redis_data:
  milvus_data:
  etcd_data:
  minio_data:
  elasticsearch_data:
  zookeeper_data:
  kafka_data:
  prometheus_data:
  grafana_data:
```

---

## 项目特色和亮点

### 1. 技术架构亮点
- **微服务架构**: 服务独立部署，易于扩展和维护
- **混合检索**: 向量检索+关键词检索，提升检索精度
- **流式响应**: WebSocket实时交互，提升用户体验
- **多级缓存**: 本地+分布式+向量数据库缓存策略

### 2. 工程实践亮点
- **完整的可观测性**: 监控、日志、链路追踪
- **高并发处理**: 协程池、连接池、批量处理
- **容器化部署**: Docker + Kubernetes
- **自动化测试**: 单元测试、集成测试、性能测试

### 3. 业务价值亮点
- **智能文档处理**: 支持多格式文档解析和智能分块
- **高质量问答**: 基于上下文的准确回答生成
- **用户体验优化**: 自然语言交互，零学习成本
- **数据驱动决策**: 完整的数据分析和质量评估

这个项目展示了在RAG/Agent开发领域的深度技术能力和工程实践经验，涵盖了从系统架构设计到具体代码实现的完整技术栈。