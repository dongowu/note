# IntelliQA项目代码实现

## 项目结构

```
intelliqa/
├── cmd/
│   ├── gateway/          # API网关服务
│   ├── document/         # 文档处理服务
│   ├── embedding/        # 向量化服务
│   ├── retrieval/        # 检索服务
│   └── chat/            # 对话服务
├── internal/
│   ├── config/          # 配置管理
│   ├── models/          # 数据模型
│   ├── services/        # 业务逻辑
│   ├── repositories/    # 数据访问层
│   └── utils/           # 工具函数
├── pkg/
│   ├── rag/             # RAG核心引擎
│   ├── vectordb/        # 向量数据库客户端
│   ├── llm/             # LLM客户端
│   └── middleware/      # 中间件
├── api/
│   └── proto/           # gRPC协议定义
├── deployments/
│   ├── docker/          # Docker配置
│   └── k8s/             # Kubernetes配置
└── docs/                # 项目文档
```

---

## 核心代码实现

### 1. 数据模型定义

```go
// internal/models/document.go
package models

import (
    "time"
    "github.com/google/uuid"
)

type Document struct {
    ID          uuid.UUID `json:"id" gorm:"type:uuid;primary_key"`
    Title       string    `json:"title" gorm:"size:255;not null"`
    Content     string    `json:"content" gorm:"type:text"`
    FileType    string    `json:"file_type" gorm:"size:50"`
    FileSize    int64     `json:"file_size"`
    FilePath    string    `json:"file_path" gorm:"size:500"`
    UserID      uuid.UUID `json:"user_id" gorm:"type:uuid;not null"`
    Status      string    `json:"status" gorm:"size:20;default:'processing'"`
    Metadata    Metadata  `json:"metadata" gorm:"type:jsonb"`
    CreatedAt   time.Time `json:"created_at"`
    UpdatedAt   time.Time `json:"updated_at"`
    Chunks      []Chunk   `json:"chunks" gorm:"foreignKey:DocumentID"`
}

type Chunk struct {
    ID          uuid.UUID `json:"id" gorm:"type:uuid;primary_key"`
    DocumentID  uuid.UUID `json:"document_id" gorm:"type:uuid;not null"`
    Content     string    `json:"content" gorm:"type:text;not null"`
    ChunkIndex  int       `json:"chunk_index"`
    TokenCount  int       `json:"token_count"`
    Vector      []float32 `json:"vector" gorm:"-"` // 存储在向量数据库
    VectorID    string    `json:"vector_id" gorm:"size:100"`
    Metadata    Metadata  `json:"metadata" gorm:"type:jsonb"`
    CreatedAt   time.Time `json:"created_at"`
}

type Metadata map[string]interface{}

type ChatSession struct {
    ID          uuid.UUID `json:"id" gorm:"type:uuid;primary_key"`
    UserID      uuid.UUID `json:"user_id" gorm:"type:uuid;not null"`
    Title       string    `json:"title" gorm:"size:255"`
    Messages    []Message `json:"messages" gorm:"foreignKey:SessionID"`
    Context     Metadata  `json:"context" gorm:"type:jsonb"`
    CreatedAt   time.Time `json:"created_at"`
    UpdatedAt   time.Time `json:"updated_at"`
}

type Message struct {
    ID          uuid.UUID `json:"id" gorm:"type:uuid;primary_key"`
    SessionID   uuid.UUID `json:"session_id" gorm:"type:uuid;not null"`
    Role        string    `json:"role" gorm:"size:20;not null"` // user, assistant, system
    Content     string    `json:"content" gorm:"type:text;not null"`
    Sources     []Source  `json:"sources" gorm:"type:jsonb"`
    Metadata    Metadata  `json:"metadata" gorm:"type:jsonb"`
    CreatedAt   time.Time `json:"created_at"`
}

type Source struct {
    DocumentID   uuid.UUID `json:"document_id"`
    ChunkID      uuid.UUID `json:"chunk_id"`
    Title        string    `json:"title"`
    Content      string    `json:"content"`
    Score        float64   `json:"score"`
    Relevance    float64   `json:"relevance"`
}
```

### 2. RAG核心引擎

```go
// pkg/rag/engine.go
package rag

import (
    "context"
    "fmt"
    "sort"
    "time"
    
    "github.com/intelliqa/internal/models"
    "github.com/intelliqa/pkg/llm"
    "github.com/intelliqa/pkg/vectordb"
)

type Engine struct {
    vectorDB    vectordb.Client
    llmClient   llm.Client
    retriever   *HybridRetriever
    reranker    *CrossEncoder
    promptMgr   *PromptManager
    config      *Config
}

type Config struct {
    TopK            int     `yaml:"top_k"`
    ScoreThreshold  float64 `yaml:"score_threshold"`
    MaxTokens       int     `yaml:"max_tokens"`
    Temperature     float64 `yaml:"temperature"`
    VectorWeight    float64 `yaml:"vector_weight"`
    KeywordWeight   float64 `yaml:"keyword_weight"`
}

type RetrievalResult struct {
    Query       string          `json:"query"`
    Chunks      []models.Chunk  `json:"chunks"`
    Sources     []models.Source `json:"sources"`
    Scores      []float64       `json:"scores"`
    TotalTime   time.Duration   `json:"total_time"`
    RetrievalTime time.Duration `json:"retrieval_time"`
    RerankTime    time.Duration `json:"rerank_time"`
}

type GenerationResult struct {
    Answer      string          `json:"answer"`
    Sources     []models.Source `json:"sources"`
    Confidence  float64         `json:"confidence"`
    TokenUsage  TokenUsage      `json:"token_usage"`
    GenerationTime time.Duration `json:"generation_time"`
}

type TokenUsage struct {
    PromptTokens     int `json:"prompt_tokens"`
    CompletionTokens int `json:"completion_tokens"`
    TotalTokens      int `json:"total_tokens"`
}

func NewEngine(vectorDB vectordb.Client, llmClient llm.Client, config *Config) *Engine {
    return &Engine{
        vectorDB:  vectorDB,
        llmClient: llmClient,
        retriever: NewHybridRetriever(vectorDB, config),
        reranker:  NewCrossEncoder(),
        promptMgr: NewPromptManager(),
        config:    config,
    }
}

func (e *Engine) Retrieve(ctx context.Context, query string) (*RetrievalResult, error) {
    startTime := time.Now()
    
    // 1. 混合检索
    retrievalStart := time.Now()
    chunks, scores, err := e.retriever.Retrieve(ctx, query, e.config.TopK*2)
    if err != nil {
        return nil, fmt.Errorf("retrieval failed: %w", err)
    }
    retrievalTime := time.Since(retrievalStart)
    
    // 2. 重排序
    rerankStart := time.Now()
    rerankedChunks, rerankedScores := e.reranker.Rerank(ctx, query, chunks, scores)
    rerankTime := time.Since(rerankStart)
    
    // 3. 过滤低分结果
    filteredChunks, filteredScores := e.filterByScore(rerankedChunks, rerankedScores)
    
    // 4. 构建源信息
    sources := e.buildSources(filteredChunks, filteredScores)
    
    return &RetrievalResult{
        Query:         query,
        Chunks:        filteredChunks[:min(len(filteredChunks), e.config.TopK)],
        Sources:       sources,
        Scores:        filteredScores[:min(len(filteredScores), e.config.TopK)],
        TotalTime:     time.Since(startTime),
        RetrievalTime: retrievalTime,
        RerankTime:    rerankTime,
    }, nil
}

func (e *Engine) Generate(ctx context.Context, query string, retrieval *RetrievalResult) (*GenerationResult, error) {
    startTime := time.Now()
    
    // 1. 构建提示词
    prompt := e.promptMgr.BuildRAGPrompt(query, retrieval.Chunks)
    
    // 2. 调用LLM生成
    response, err := e.llmClient.Generate(ctx, &llm.GenerateRequest{
        Prompt:      prompt,
        MaxTokens:   e.config.MaxTokens,
        Temperature: e.config.Temperature,
    })
    if err != nil {
        return nil, fmt.Errorf("generation failed: %w", err)
    }
    
    // 3. 计算置信度
    confidence := e.calculateConfidence(retrieval.Scores)
    
    return &GenerationResult{
        Answer:         response.Text,
        Sources:        retrieval.Sources,
        Confidence:     confidence,
        TokenUsage:     TokenUsage(response.Usage),
        GenerationTime: time.Since(startTime),
    }, nil
}

func (e *Engine) Chat(ctx context.Context, query string, sessionID string) (*GenerationResult, error) {
    // 1. 检索相关文档
    retrieval, err := e.Retrieve(ctx, query)
    if err != nil {
        return nil, err
    }
    
    // 2. 生成回答
    generation, err := e.Generate(ctx, query, retrieval)
    if err != nil {
        return nil, err
    }
    
    return generation, nil
}

func (e *Engine) filterByScore(chunks []models.Chunk, scores []float64) ([]models.Chunk, []float64) {
    var filteredChunks []models.Chunk
    var filteredScores []float64
    
    for i, score := range scores {
        if score >= e.config.ScoreThreshold {
            filteredChunks = append(filteredChunks, chunks[i])
            filteredScores = append(filteredScores, score)
        }
    }
    
    return filteredChunks, filteredScores
}

func (e *Engine) buildSources(chunks []models.Chunk, scores []float64) []models.Source {
    sources := make([]models.Source, len(chunks))
    for i, chunk := range chunks {
        sources[i] = models.Source{
            DocumentID: chunk.DocumentID,
            ChunkID:    chunk.ID,
            Content:    chunk.Content,
            Score:      scores[i],
            Relevance:  scores[i],
        }
    }
    return sources
}

func (e *Engine) calculateConfidence(scores []float64) float64 {
    if len(scores) == 0 {
        return 0.0
    }
    
    // 基于最高分和平均分计算置信度
    maxScore := scores[0]
    var sum float64
    for _, score := range scores {
        sum += score
    }
    avgScore := sum / float64(len(scores))
    
    return (maxScore + avgScore) / 2.0
}

func min(a, b int) int {
    if a < b {
        return a
    }
    return b
}
```

### 3. 混合检索器

```go
// pkg/rag/retriever.go
package rag

import (
    "context"
    "fmt"
    "math"
    "sort"
    
    "github.com/intelliqa/internal/models"
    "github.com/intelliqa/pkg/vectordb"
)

type HybridRetriever struct {
    vectorDB      vectordb.Client
    keywordSearch KeywordSearcher
    embedder      Embedder
    config        *Config
}

type KeywordSearcher interface {
    Search(ctx context.Context, query string, topK int) ([]models.Chunk, []float64, error)
}

type Embedder interface {
    Embed(ctx context.Context, text string) ([]float32, error)
}

type SearchResult struct {
    Chunk models.Chunk
    Score float64
    Type  string // "vector" or "keyword"
}

func NewHybridRetriever(vectorDB vectordb.Client, config *Config) *HybridRetriever {
    return &HybridRetriever{
        vectorDB:      vectorDB,
        keywordSearch: NewElasticsearchSearcher(),
        embedder:      NewOpenAIEmbedder(),
        config:        config,
    }
}

func (r *HybridRetriever) Retrieve(ctx context.Context, query string, topK int) ([]models.Chunk, []float64, error) {
    // 1. 向量检索
    vectorResults, err := r.vectorSearch(ctx, query, topK)
    if err != nil {
        return nil, nil, fmt.Errorf("vector search failed: %w", err)
    }
    
    // 2. 关键词检索
    keywordResults, err := r.keywordSearch.Search(ctx, query, topK)
    if err != nil {
        return nil, nil, fmt.Errorf("keyword search failed: %w", err)
    }
    
    // 3. 结果融合
    fusedResults := r.fuseResults(vectorResults, keywordResults)
    
    // 4. 排序和截取
    sort.Slice(fusedResults, func(i, j int) bool {
        return fusedResults[i].Score > fusedResults[j].Score
    })
    
    if len(fusedResults) > topK {
        fusedResults = fusedResults[:topK]
    }
    
    chunks := make([]models.Chunk, len(fusedResults))
    scores := make([]float64, len(fusedResults))
    for i, result := range fusedResults {
        chunks[i] = result.Chunk
        scores[i] = result.Score
    }
    
    return chunks, scores, nil
}

func (r *HybridRetriever) vectorSearch(ctx context.Context, query string, topK int) ([]SearchResult, error) {
    // 1. 查询向量化
    queryVector, err := r.embedder.Embed(ctx, query)
    if err != nil {
        return nil, err
    }
    
    // 2. 向量检索
    searchReq := &vectordb.SearchRequest{
        Vector: queryVector,
        TopK:   topK,
        Filter: nil,
    }
    
    searchResp, err := r.vectorDB.Search(ctx, searchReq)
    if err != nil {
        return nil, err
    }
    
    // 3. 构建结果
    results := make([]SearchResult, len(searchResp.Results))
    for i, result := range searchResp.Results {
        chunk := models.Chunk{
            ID:      result.ID,
            Content: result.Metadata["content"].(string),
            // ... 其他字段
        }
        
        results[i] = SearchResult{
            Chunk: chunk,
            Score: result.Score,
            Type:  "vector",
        }
    }
    
    return results, nil
}

func (r *HybridRetriever) fuseResults(vectorResults []SearchResult, keywordChunks []models.Chunk) []SearchResult {
    // 使用RRF (Reciprocal Rank Fusion) 算法融合结果
    scoreMap := make(map[string]float64)
    chunkMap := make(map[string]models.Chunk)
    
    // 处理向量检索结果
    for rank, result := range vectorResults {
        id := result.Chunk.ID.String()
        scoreMap[id] += r.config.VectorWeight / float64(rank+60) // RRF with k=60
        chunkMap[id] = result.Chunk
    }
    
    // 处理关键词检索结果
    for rank, chunk := range keywordChunks {
        id := chunk.ID.String()
        scoreMap[id] += r.config.KeywordWeight / float64(rank+60)
        chunkMap[id] = chunk
    }
    
    // 构建融合结果
    var fusedResults []SearchResult
    for id, score := range scoreMap {
        fusedResults = append(fusedResults, SearchResult{
            Chunk: chunkMap[id],
            Score: score,
            Type:  "hybrid",
        })
    }
    
    return fusedResults
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
    "github.com/intelliqa/internal/repositories"
    "github.com/intelliqa/pkg/rag"
)

type DocumentService struct {
    docRepo     repositories.DocumentRepository
    chunkRepo   repositories.ChunkRepository
    parser      DocumentParser
    chunker     TextChunker
    embedder    rag.Embedder
    vectorDB    vectordb.Client
}

type DocumentParser interface {
    Parse(reader io.Reader, fileType string) (*ParsedDocument, error)
    SupportedTypes() []string
}

type TextChunker interface {
    Chunk(text string, metadata models.Metadata) ([]ChunkData, error)
}

type ParsedDocument struct {
    Title    string
    Content  string
    Metadata models.Metadata
}

type ChunkData struct {
    Content    string
    Index      int
    TokenCount int
    Metadata   models.Metadata
}

func NewDocumentService(
    docRepo repositories.DocumentRepository,
    chunkRepo repositories.ChunkRepository,
    parser DocumentParser,
    chunker TextChunker,
    embedder rag.Embedder,
    vectorDB vectordb.Client,
) *DocumentService {
    return &DocumentService{
        docRepo:   docRepo,
        chunkRepo: chunkRepo,
        parser:    parser,
        chunker:   chunker,
        embedder:  embedder,
        vectorDB:  vectorDB,
    }
}

func (s *DocumentService) ProcessDocument(ctx context.Context, reader io.Reader, filename string, userID uuid.UUID) (*models.Document, error) {
    // 1. 创建文档记录
    doc := &models.Document{
        ID:       uuid.New(),
        Title:    s.extractTitle(filename),
        FileType: s.getFileType(filename),
        UserID:   userID,
        Status:   "processing",
        Metadata: make(models.Metadata),
    }
    
    if err := s.docRepo.Create(ctx, doc); err != nil {
        return nil, fmt.Errorf("failed to create document: %w", err)
    }
    
    // 2. 异步处理文档
    go s.processDocumentAsync(ctx, doc, reader)
    
    return doc, nil
}

func (s *DocumentService) processDocumentAsync(ctx context.Context, doc *models.Document, reader io.Reader) {
    defer func() {
        if r := recover(); r != nil {
            s.updateDocumentStatus(ctx, doc.ID, "failed", fmt.Sprintf("panic: %v", r))
        }
    }()
    
    // 1. 解析文档
    parsed, err := s.parser.Parse(reader, doc.FileType)
    if err != nil {
        s.updateDocumentStatus(ctx, doc.ID, "failed", err.Error())
        return
    }
    
    // 2. 更新文档内容
    doc.Content = parsed.Content
    doc.Metadata = parsed.Metadata
    if err := s.docRepo.Update(ctx, doc); err != nil {
        s.updateDocumentStatus(ctx, doc.ID, "failed", err.Error())
        return
    }
    
    // 3. 文本分块
    chunks, err := s.chunker.Chunk(parsed.Content, parsed.Metadata)
    if err != nil {
        s.updateDocumentStatus(ctx, doc.ID, "failed", err.Error())
        return
    }
    
    // 4. 处理每个分块
    for _, chunkData := range chunks {
        if err := s.processChunk(ctx, doc.ID, chunkData); err != nil {
            // 记录错误但继续处理其他分块
            fmt.Printf("Failed to process chunk: %v\n", err)
        }
    }
    
    // 5. 更新文档状态
    s.updateDocumentStatus(ctx, doc.ID, "completed", "")
}

func (s *DocumentService) processChunk(ctx context.Context, docID uuid.UUID, chunkData ChunkData) error {
    // 1. 创建分块记录
    chunk := &models.Chunk{
        ID:         uuid.New(),
        DocumentID: docID,
        Content:    chunkData.Content,
        ChunkIndex: chunkData.Index,
        TokenCount: chunkData.TokenCount,
        Metadata:   chunkData.Metadata,
    }
    
    if err := s.chunkRepo.Create(ctx, chunk); err != nil {
        return fmt.Errorf("failed to create chunk: %w", err)
    }
    
    // 2. 生成向量
    vector, err := s.embedder.Embed(ctx, chunkData.Content)
    if err != nil {
        return fmt.Errorf("failed to embed chunk: %w", err)
    }
    
    // 3. 存储到向量数据库
    vectorID := fmt.Sprintf("%s_%d", docID.String(), chunkData.Index)
    insertReq := &vectordb.InsertRequest{
        ID:     vectorID,
        Vector: vector,
        Metadata: map[string]interface{}{
            "chunk_id":    chunk.ID.String(),
            "document_id": docID.String(),
            "content":     chunkData.Content,
            "chunk_index": chunkData.Index,
        },
    }
    
    if err := s.vectorDB.Insert(ctx, insertReq); err != nil {
        return fmt.Errorf("failed to insert vector: %w", err)
    }
    
    // 4. 更新分块的向量ID
    chunk.VectorID = vectorID
    if err := s.chunkRepo.Update(ctx, chunk); err != nil {
        return fmt.Errorf("failed to update chunk vector ID: %w", err)
    }
    
    return nil
}

func (s *DocumentService) updateDocumentStatus(ctx context.Context, docID uuid.UUID, status, errorMsg string) {
    doc, err := s.docRepo.GetByID(ctx, docID)
    if err != nil {
        return
    }
    
    doc.Status = status
    if errorMsg != "" {
        doc.Metadata["error"] = errorMsg
    }
    doc.UpdatedAt = time.Now()
    
    s.docRepo.Update(ctx, doc)
}

func (s *DocumentService) extractTitle(filename string) string {
    base := filepath.Base(filename)
    ext := filepath.Ext(base)
    return strings.TrimSuffix(base, ext)
}

func (s *DocumentService) getFileType(filename string) string {
    ext := strings.ToLower(filepath.Ext(filename))
    switch ext {
    case ".pdf":
        return "pdf"
    case ".docx", ".doc":
        return "word"
    case ".txt":
        return "text"
    case ".md":
        return "markdown"
    default:
        return "unknown"
    }
}
```

### 5. 对话服务

```go
// internal/services/chat_service.go
package services

import (
    "context"
    "fmt"
    "time"
    
    "github.com/google/uuid"
    "github.com/intelliqa/internal/models"
    "github.com/intelliqa/internal/repositories"
    "github.com/intelliqa/pkg/rag"
)

type ChatService struct {
    sessionRepo repositories.SessionRepository
    messageRepo repositories.MessageRepository
    ragEngine   *rag.Engine
}

type ChatRequest struct {
    SessionID string `json:"session_id"`
    Message   string `json:"message"`
    UserID    string `json:"user_id"`
}

type ChatResponse struct {
    SessionID   string          `json:"session_id"`
    MessageID   string          `json:"message_id"`
    Answer      string          `json:"answer"`
    Sources     []models.Source `json:"sources"`
    Confidence  float64         `json:"confidence"`
    TokenUsage  rag.TokenUsage  `json:"token_usage"`
    ResponseTime time.Duration  `json:"response_time"`
}

type StreamChatChunk struct {
    Type      string      `json:"type"` // "retrieval", "generation", "done"
    Content   string      `json:"content,omitempty"`
    Sources   []models.Source `json:"sources,omitempty"`
    Metadata  interface{} `json:"metadata,omitempty"`
}

func NewChatService(
    sessionRepo repositories.SessionRepository,
    messageRepo repositories.MessageRepository,
    ragEngine *rag.Engine,
) *ChatService {
    return &ChatService{
        sessionRepo: sessionRepo,
        messageRepo: messageRepo,
        ragEngine:   ragEngine,
    }
}

func (s *ChatService) Chat(ctx context.Context, req *ChatRequest) (*ChatResponse, error) {
    startTime := time.Now()
    
    // 1. 获取或创建会话
    session, err := s.getOrCreateSession(ctx, req.SessionID, req.UserID)
    if err != nil {
        return nil, fmt.Errorf("failed to get session: %w", err)
    }
    
    // 2. 保存用户消息
    userMessage := &models.Message{
        ID:        uuid.New(),
        SessionID: session.ID,
        Role:      "user",
        Content:   req.Message,
        Metadata:  make(models.Metadata),
        CreatedAt: time.Now(),
    }
    
    if err := s.messageRepo.Create(ctx, userMessage); err != nil {
        return nil, fmt.Errorf("failed to save user message: %w", err)
    }
    
    // 3. RAG生成回答
    generation, err := s.ragEngine.Chat(ctx, req.Message, req.SessionID)
    if err != nil {
        return nil, fmt.Errorf("failed to generate answer: %w", err)
    }
    
    // 4. 保存助手消息
    assistantMessage := &models.Message{
        ID:        uuid.New(),
        SessionID: session.ID,
        Role:      "assistant",
        Content:   generation.Answer,
        Sources:   generation.Sources,
        Metadata: models.Metadata{
            "confidence":      generation.Confidence,
            "token_usage":     generation.TokenUsage,
            "generation_time": generation.GenerationTime.Milliseconds(),
        },
        CreatedAt: time.Now(),
    }
    
    if err := s.messageRepo.Create(ctx, assistantMessage); err != nil {
        return nil, fmt.Errorf("failed to save assistant message: %w", err)
    }
    
    // 5. 更新会话
    session.UpdatedAt = time.Now()
    if err := s.sessionRepo.Update(ctx, session); err != nil {
        // 非关键错误，记录但不返回
        fmt.Printf("Failed to update session: %v\n", err)
    }
    
    return &ChatResponse{
        SessionID:    session.ID.String(),
        MessageID:    assistantMessage.ID.String(),
        Answer:       generation.Answer,
        Sources:      generation.Sources,
        Confidence:   generation.Confidence,
        TokenUsage:   generation.TokenUsage,
        ResponseTime: time.Since(startTime),
    }, nil
}

func (s *ChatService) StreamChat(ctx context.Context, req *ChatRequest) (<-chan StreamChatChunk, error) {
    resultChan := make(chan StreamChatChunk, 100)
    
    go func() {
        defer close(resultChan)
        
        // 1. 获取或创建会话
        session, err := s.getOrCreateSession(ctx, req.SessionID, req.UserID)
        if err != nil {
            resultChan <- StreamChatChunk{
                Type:    "error",
                Content: fmt.Sprintf("Failed to get session: %v", err),
            }
            return
        }
        
        // 2. 保存用户消息
        userMessage := &models.Message{
            ID:        uuid.New(),
            SessionID: session.ID,
            Role:      "user",
            Content:   req.Message,
            CreatedAt: time.Now(),
        }
        
        if err := s.messageRepo.Create(ctx, userMessage); err != nil {
            resultChan <- StreamChatChunk{
                Type:    "error",
                Content: fmt.Sprintf("Failed to save message: %v", err),
            }
            return
        }
        
        // 3. 检索阶段
        retrieval, err := s.ragEngine.Retrieve(ctx, req.Message)
        if err != nil {
            resultChan <- StreamChatChunk{
                Type:    "error",
                Content: fmt.Sprintf("Retrieval failed: %v", err),
            }
            return
        }
        
        resultChan <- StreamChatChunk{
            Type:    "retrieval",
            Sources: retrieval.Sources,
            Metadata: map[string]interface{}{
                "retrieval_time": retrieval.RetrievalTime.Milliseconds(),
                "chunks_found":   len(retrieval.Chunks),
            },
        }
        
        // 4. 生成阶段 (这里简化，实际应该支持流式生成)
        generation, err := s.ragEngine.Generate(ctx, req.Message, retrieval)
        if err != nil {
            resultChan <- StreamChatChunk{
                Type:    "error",
                Content: fmt.Sprintf("Generation failed: %v", err),
            }
            return
        }
        
        // 模拟流式输出
        words := strings.Fields(generation.Answer)
        for i, word := range words {
            resultChan <- StreamChatChunk{
                Type:    "generation",
                Content: word + " ",
            }
            time.Sleep(50 * time.Millisecond) // 模拟延迟
        }
        
        // 5. 完成
        resultChan <- StreamChatChunk{
            Type:    "done",
            Sources: generation.Sources,
            Metadata: map[string]interface{}{
                "confidence":      generation.Confidence,
                "token_usage":     generation.TokenUsage,
                "generation_time": generation.GenerationTime.Milliseconds(),
            },
        }
        
        // 6. 保存助手消息
        assistantMessage := &models.Message{
            ID:        uuid.New(),
            SessionID: session.ID,
            Role:      "assistant",
            Content:   generation.Answer,
            Sources:   generation.Sources,
            Metadata: models.Metadata{
                "confidence":  generation.Confidence,
                "token_usage": generation.TokenUsage,
            },
            CreatedAt: time.Now(),
        }
        
        s.messageRepo.Create(ctx, assistantMessage)
    }()
    
    return resultChan, nil
}

func (s *ChatService) getOrCreateSession(ctx context.Context, sessionID, userID string) (*models.ChatSession, error) {
    if sessionID != "" {
        if id, err := uuid.Parse(sessionID); err == nil {
            if session, err := s.sessionRepo.GetByID(ctx, id); err == nil {
                return session, nil
            }
        }
    }
    
    // 创建新会话
    userUUID, err := uuid.Parse(userID)
    if err != nil {
        return nil, fmt.Errorf("invalid user ID: %w", err)
    }
    
    session := &models.ChatSession{
        ID:        uuid.New(),
        UserID:    userUUID,
        Title:     "New Chat",
        Context:   make(models.Metadata),
        CreatedAt: time.Now(),
        UpdatedAt: time.Now(),
    }
    
    if err := s.sessionRepo.Create(ctx, session); err != nil {
        return nil, fmt.Errorf("failed to create session: %w", err)
    }
    
    return session, nil
}

func (s *ChatService) GetChatHistory(ctx context.Context, sessionID string, limit int) ([]models.Message, error) {
    id, err := uuid.Parse(sessionID)
    if err != nil {
        return nil, fmt.Errorf("invalid session ID: %w", err)
    }
    
    return s.messageRepo.GetBySessionID(ctx, id, limit)
}

func (s *ChatService) GetUserSessions(ctx context.Context, userID string, limit int) ([]models.ChatSession, error) {
    id, err := uuid.Parse(userID)
    if err != nil {
        return nil, fmt.Errorf("invalid user ID: %w", err)
    }
    
    return s.sessionRepo.GetByUserID(ctx, id, limit)
}
```

---

## 性能监控与指标

### 监控指标定义

```go
// pkg/metrics/metrics.go
package metrics

import (
    "time"
    
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
)

var (
    // 检索相关指标
    RetrievalDuration = promauto.NewHistogramVec(
        prometheus.HistogramOpts{
            Name:    "intelliqa_retrieval_duration_seconds",
            Help:    "Duration of retrieval operations",
            Buckets: prometheus.DefBuckets,
        },
        []string{"type"}, // vector, keyword, hybrid
    )
    
    RetrievalAccuracy = promauto.NewGaugeVec(
        prometheus.GaugeOpts{
            Name: "intelliqa_retrieval_accuracy",
            Help: "Retrieval accuracy score",
        },
        []string{"model"},
    )
    
    // LLM相关指标
    LLMRequestDuration = promauto.NewHistogramVec(
        prometheus.HistogramOpts{
            Name:    "intelliqa_llm_request_duration_seconds",
            Help:    "Duration of LLM requests",
            Buckets: []float64{0.1, 0.5, 1.0, 2.0, 5.0, 10.0},
        },
        []string{"model", "status"},
    )
    
    LLMTokenUsage = promauto.NewCounterVec(
        prometheus.CounterOpts{
            Name: "intelliqa_llm_tokens_total",
            Help: "Total number of tokens used",
        },
        []string{"model", "type"}, // prompt, completion
    )
    
    // 业务指标
    ChatRequestsTotal = promauto.NewCounterVec(
        prometheus.CounterOpts{
            Name: "intelliqa_chat_requests_total",
            Help: "Total number of chat requests",
        },
        []string{"status"}, // success, error
    )
    
    UserSatisfactionScore = promauto.NewGaugeVec(
        prometheus.GaugeOpts{
            Name: "intelliqa_user_satisfaction_score",
            Help: "User satisfaction score",
        },
        []string{"session_type"},
    )
    
    // 系统指标
    VectorDBConnections = promauto.NewGauge(
        prometheus.GaugeOpts{
            Name: "intelliqa_vectordb_connections",
            Help: "Number of active vector database connections",
        },
    )
    
    DocumentProcessingQueue = promauto.NewGauge(
        prometheus.GaugeOpts{
            Name: "intelliqa_document_processing_queue_size",
            Help: "Number of documents in processing queue",
        },
    )
)

// 记录检索延迟
func RecordRetrievalDuration(retrievalType string, duration time.Duration) {
    RetrievalDuration.WithLabelValues(retrievalType).Observe(duration.Seconds())
}

// 记录LLM调用
func RecordLLMRequest(model, status string, duration time.Duration) {
    LLMRequestDuration.WithLabelValues(model, status).Observe(duration.Seconds())
}

// 记录Token使用
func RecordTokenUsage(model, tokenType string, count int) {
    LLMTokenUsage.WithLabelValues(model, tokenType).Add(float64(count))
}

// 记录聊天请求
func RecordChatRequest(status string) {
    ChatRequestsTotal.WithLabelValues(status).Inc()
}
```

---

## 部署配置

### Docker Compose

```yaml
# deployments/docker/docker-compose.yml
version: '3.8'

services:
  # API网关
  gateway:
    build:
      context: ../../
      dockerfile: deployments/docker/Dockerfile.gateway
    ports:
      - "8080:8080"
    environment:
      - CONFIG_PATH=/app/config/gateway.yaml
    volumes:
      - ./config:/app/config
    depends_on:
      - postgres
      - redis
      - milvus
    networks:
      - intelliqa

  # 文档处理服务
  document-service:
    build:
      context: ../../
      dockerfile: deployments/docker/Dockerfile.document
    environment:
      - CONFIG_PATH=/app/config/document.yaml
    volumes:
      - ./config:/app/config
      - ./uploads:/app/uploads
    depends_on:
      - postgres
      - kafka
    networks:
      - intelliqa

  # 检索服务
  retrieval-service:
    build:
      context: ../../
      dockerfile: deployments/docker/Dockerfile.retrieval
    environment:
      - CONFIG_PATH=/app/config/retrieval.yaml
    volumes:
      - ./config:/app/config
    depends_on:
      - milvus
      - elasticsearch
    networks:
      - intelliqa

  # 对话服务
  chat-service:
    build:
      context: ../../
      dockerfile: deployments/docker/Dockerfile.chat
    environment:
      - CONFIG_PATH=/app/config/chat.yaml
    volumes:
      - ./config:/app/config
    depends_on:
      - postgres
      - redis
    networks:
      - intelliqa

  # 数据库
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: intelliqa
      POSTGRES_USER: intelliqa
      POSTGRES_PASSWORD: password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    networks:
      - intelliqa

  # 缓存
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    networks:
      - intelliqa

  # 向量数据库
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
      - etcd
      - minio
    networks:
      - intelliqa

  # 搜索引擎
  elasticsearch:
    image: elasticsearch:8.8.0
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
    volumes:
      - es_data:/usr/share/elasticsearch/data
    ports:
      - "9200:9200"
    networks:
      - intelliqa

  # 消息队列
  kafka:
    image: confluentinc/cp-kafka:latest
    environment:
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
    ports:
      - "9092:9092"
    depends_on:
      - zookeeper
    networks:
      - intelliqa

  zookeeper:
    image: confluentinc/cp-zookeeper:latest
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
      ZOOKEEPER_TICK_TIME: 2000
    networks:
      - intelliqa

  # Milvus依赖
  etcd:
    image: quay.io/coreos/etcd:v3.5.0
    command: etcd -advertise-client-urls=http://127.0.0.1:2379 -listen-client-urls http://0.0.0.0:2379 --data-dir /etcd
    volumes:
      - etcd_data:/etcd
    networks:
      - intelliqa

  minio:
    image: minio/minio:RELEASE.2023-03-20T20-16-18Z
    command: minio server /minio_data --console-address ":9001"
    environment:
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    volumes:
      - minio_data:/minio_data
    ports:
      - "9000:9000"
      - "9001:9001"
    networks:
      - intelliqa

  # 监控
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    networks:
      - intelliqa

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana_data:/var/lib/grafana
      - ./monitoring/grafana:/etc/grafana/provisioning
    networks:
      - intelliqa

volumes:
  postgres_data:
  redis_data:
  milvus_data:
  es_data:
  etcd_data:
  minio_data:
  prometheus_data:
  grafana_data:

networks:
  intelliqa:
    driver: bridge
```

---

*本项目代码实现展示了完整的RAG系统架构，包含文档处理、向量检索、混合搜索、对话管理等核心功能，体现了在Go语言和AI领域的深度技术能力。*