# PostgreSQL 实战案例分析

## 目录
- [电商系统案例](#电商系统案例)
- [金融系统案例](#金融系统案例)
- [日志分析系统案例](#日志分析系统案例)
- [社交媒体系统案例](#社交媒体系统案例)
- [物联网数据处理案例](#物联网数据处理案例)
- [数据仓库案例](#数据仓库案例)

## 电商系统案例

### 场景描述
某大型电商平台，日订单量100万+，需要处理商品库存、订单处理、支付流程等核心业务。

### 技术挑战
1. **高并发库存扣减**：防止超卖
2. **订单数据一致性**：确保订单状态正确
3. **查询性能优化**：商品搜索、订单查询
4. **数据分片策略**：处理海量历史数据

### 解决方案

#### 1. 数据库设计

```sql
-- 商品表（支持分布式锁）
CREATE TABLE products (
    id BIGSERIAL PRIMARY KEY,
    sku VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    stock INTEGER NOT NULL DEFAULT 0,
    reserved_stock INTEGER NOT NULL DEFAULT 0, -- 预留库存
    version BIGINT NOT NULL DEFAULT 1,          -- 乐观锁版本
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 库存变更日志表
CREATE TABLE stock_logs (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT REFERENCES products(id),
    change_type VARCHAR(20) NOT NULL, -- 'reserve', 'confirm', 'release'
    quantity INTEGER NOT NULL,
    before_stock INTEGER NOT NULL,
    after_stock INTEGER NOT NULL,
    order_id BIGINT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 订单表（按时间分区）
CREATE TABLE orders (
    id BIGSERIAL,
    user_id BIGINT NOT NULL,
    order_no VARCHAR(32) UNIQUE NOT NULL,
    total_amount DECIMAL(12,2) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    payment_status VARCHAR(20) DEFAULT 'unpaid',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
) PARTITION BY RANGE (created_at);

-- 创建月度分区
CREATE TABLE orders_2024_01 PARTITION OF orders
FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');

CREATE TABLE orders_2024_02 PARTITION OF orders
FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');

-- 订单项表
CREATE TABLE order_items (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL,
    product_id BIGINT REFERENCES products(id),
    sku VARCHAR(50) NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    total_price DECIMAL(10,2) NOT NULL
);

-- 索引优化
CREATE INDEX idx_products_sku ON products(sku);
CREATE INDEX idx_products_status_stock ON products(status, stock) WHERE status = 'active';
CREATE INDEX idx_orders_user_created ON orders(user_id, created_at DESC);
CREATE INDEX idx_orders_status_created ON orders(status, created_at);
CREATE INDEX idx_order_items_order_id ON order_items(order_id);
CREATE INDEX idx_stock_logs_product_created ON stock_logs(product_id, created_at);
```

#### 2. Go实现 - 库存管理服务

```go
package inventory

import (
    "context"
    "database/sql"
    "errors"
    "fmt"
    "time"
    
    "github.com/lib/pq"
)

type InventoryService struct {
    db *sql.DB
}

type StockReservation struct {
    ProductID int64
    Quantity  int
    OrderID   int64
}

// 预留库存（两阶段提交第一阶段）
func (s *InventoryService) ReserveStock(ctx context.Context, reservations []StockReservation) error {
    tx, err := s.db.BeginTx(ctx, &sql.TxOptions{
        Isolation: sql.LevelReadCommitted,
    })
    if err != nil {
        return fmt.Errorf("begin transaction: %w", err)
    }
    defer tx.Rollback()
    
    for _, reservation := range reservations {
        // 使用乐观锁更新库存
        var currentStock, reservedStock, version int
        err := tx.QueryRowContext(ctx, `
            SELECT stock, reserved_stock, version 
            FROM products 
            WHERE id = $1 AND status = 'active'
        `, reservation.ProductID).Scan(&currentStock, &reservedStock, &version)
        
        if err != nil {
            if err == sql.ErrNoRows {
                return errors.New("product not found or inactive")
            }
            return fmt.Errorf("query product: %w", err)
        }
        
        // 检查可用库存
        availableStock := currentStock - reservedStock
        if availableStock < reservation.Quantity {
            return fmt.Errorf("insufficient stock for product %d: available=%d, required=%d", 
                reservation.ProductID, availableStock, reservation.Quantity)
        }
        
        // 更新预留库存
        result, err := tx.ExecContext(ctx, `
            UPDATE products 
            SET reserved_stock = reserved_stock + $1, 
                version = version + 1,
                updated_at = NOW()
            WHERE id = $2 AND version = $3
        `, reservation.Quantity, reservation.ProductID, version)
        
        if err != nil {
            return fmt.Errorf("update reserved stock: %w", err)
        }
        
        rowsAffected, _ := result.RowsAffected()
        if rowsAffected == 0 {
            return errors.New("product was modified by another transaction, please retry")
        }
        
        // 记录库存变更日志
        _, err = tx.ExecContext(ctx, `
            INSERT INTO stock_logs (product_id, change_type, quantity, before_stock, after_stock, order_id)
            VALUES ($1, 'reserve', $2, $3, $4, $5)
        `, reservation.ProductID, reservation.Quantity, 
           availableStock, availableStock-reservation.Quantity, reservation.OrderID)
        
        if err != nil {
            return fmt.Errorf("insert stock log: %w", err)
        }
    }
    
    return tx.Commit()
}

// 确认库存扣减（两阶段提交第二阶段）
func (s *InventoryService) ConfirmStock(ctx context.Context, orderID int64) error {
    tx, err := s.db.BeginTx(ctx, nil)
    if err != nil {
        return err
    }
    defer tx.Rollback()
    
    // 获取预留的库存信息
    rows, err := tx.QueryContext(ctx, `
        SELECT product_id, quantity 
        FROM stock_logs 
        WHERE order_id = $1 AND change_type = 'reserve'
    `, orderID)
    if err != nil {
        return err
    }
    defer rows.Close()
    
    var reservations []StockReservation
    for rows.Next() {
        var r StockReservation
        if err := rows.Scan(&r.ProductID, &r.Quantity); err != nil {
            return err
        }
        r.OrderID = orderID
        reservations = append(reservations, r)
    }
    
    // 确认扣减库存
    for _, reservation := range reservations {
        _, err = tx.ExecContext(ctx, `
            UPDATE products 
            SET stock = stock - $1,
                reserved_stock = reserved_stock - $1,
                updated_at = NOW()
            WHERE id = $2
        `, reservation.Quantity, reservation.ProductID)
        
        if err != nil {
            return err
        }
        
        // 记录确认日志
        _, err = tx.ExecContext(ctx, `
            INSERT INTO stock_logs (product_id, change_type, quantity, order_id)
            VALUES ($1, 'confirm', $2, $3)
        `, reservation.ProductID, reservation.Quantity, orderID)
        
        if err != nil {
            return err
        }
    }
    
    return tx.Commit()
}

// 释放预留库存（订单取消时）
func (s *InventoryService) ReleaseStock(ctx context.Context, orderID int64) error {
    tx, err := s.db.BeginTx(ctx, nil)
    if err != nil {
        return err
    }
    defer tx.Rollback()
    
    // 获取预留的库存信息
    rows, err := tx.QueryContext(ctx, `
        SELECT product_id, quantity 
        FROM stock_logs 
        WHERE order_id = $1 AND change_type = 'reserve'
    `, orderID)
    if err != nil {
        return err
    }
    defer rows.Close()
    
    for rows.Next() {
        var productID int64
        var quantity int
        if err := rows.Scan(&productID, &quantity); err != nil {
            return err
        }
        
        // 释放预留库存
        _, err = tx.ExecContext(ctx, `
            UPDATE products 
            SET reserved_stock = reserved_stock - $1,
                updated_at = NOW()
            WHERE id = $2
        `, quantity, productID)
        
        if err != nil {
            return err
        }
        
        // 记录释放日志
        _, err = tx.ExecContext(ctx, `
            INSERT INTO stock_logs (product_id, change_type, quantity, order_id)
            VALUES ($1, 'release', $2, $3)
        `, productID, quantity, orderID)
        
        if err != nil {
            return err
        }
    }
    
    return tx.Commit()
}
```

#### 3. 订单服务实现

```go
package order

import (
    "context"
    "database/sql"
    "fmt"
    "time"
    
    "github.com/google/uuid"
)

type OrderService struct {
    db        *sql.DB
    inventory *InventoryService
}

type CreateOrderRequest struct {
    UserID int64
    Items  []OrderItem
}

type OrderItem struct {
    ProductID int64
    SKU       string
    Quantity  int
    UnitPrice float64
}

func (s *OrderService) CreateOrder(ctx context.Context, req CreateOrderRequest) (*Order, error) {
    // 生成订单号
    orderNo := generateOrderNo()
    
    tx, err := s.db.BeginTx(ctx, &sql.TxOptions{
        Isolation: sql.LevelReadCommitted,
    })
    if err != nil {
        return nil, err
    }
    defer tx.Rollback()
    
    // 1. 创建订单
    var orderID int64
    var totalAmount float64
    for _, item := range req.Items {
        totalAmount += item.UnitPrice * float64(item.Quantity)
    }
    
    err = tx.QueryRowContext(ctx, `
        INSERT INTO orders (user_id, order_no, total_amount, status, created_at)
        VALUES ($1, $2, $3, 'pending', NOW())
        RETURNING id
    `, req.UserID, orderNo, totalAmount).Scan(&orderID)
    
    if err != nil {
        return nil, fmt.Errorf("create order: %w", err)
    }
    
    // 2. 创建订单项
    for _, item := range req.Items {
        _, err = tx.ExecContext(ctx, `
            INSERT INTO order_items (order_id, product_id, sku, quantity, unit_price, total_price)
            VALUES ($1, $2, $3, $4, $5, $6)
        `, orderID, item.ProductID, item.SKU, item.Quantity, 
           item.UnitPrice, item.UnitPrice*float64(item.Quantity))
        
        if err != nil {
            return nil, fmt.Errorf("create order item: %w", err)
        }
    }
    
    // 3. 预留库存
    var reservations []StockReservation
    for _, item := range req.Items {
        reservations = append(reservations, StockReservation{
            ProductID: item.ProductID,
            Quantity:  item.Quantity,
            OrderID:   orderID,
        })
    }
    
    if err := s.inventory.ReserveStock(ctx, reservations); err != nil {
        return nil, fmt.Errorf("reserve stock: %w", err)
    }
    
    if err := tx.Commit(); err != nil {
        // 如果订单创建失败，释放已预留的库存
        s.inventory.ReleaseStock(ctx, orderID)
        return nil, err
    }
    
    return &Order{
        ID:          orderID,
        UserID:      req.UserID,
        OrderNo:     orderNo,
        TotalAmount: totalAmount,
        Status:      "pending",
        CreatedAt:   time.Now(),
    }, nil
}

func generateOrderNo() string {
    return fmt.Sprintf("ORD%d%s", 
        time.Now().Unix(), 
        uuid.New().String()[:8])
}
```

#### 4. 性能监控与优化

```sql
-- 监控慢查询
SELECT 
    query,
    calls,
    total_time,
    mean_time,
    rows
FROM pg_stat_statements
WHERE mean_time > 100  -- 平均执行时间超过100ms
ORDER BY mean_time DESC
LIMIT 10;

-- 监控表大小和索引使用情况
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
    seq_scan,
    seq_tup_read,
    idx_scan,
    idx_tup_fetch,
    n_tup_ins,
    n_tup_upd,
    n_tup_del
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- 监控锁等待
SELECT 
    blocked_locks.pid AS blocked_pid,
    blocked_activity.usename AS blocked_user,
    blocking_locks.pid AS blocking_pid,
    blocking_activity.usename AS blocking_user,
    blocked_activity.query AS blocked_statement
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity 
    ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks 
    ON blocking_locks.locktype = blocked_locks.locktype
JOIN pg_catalog.pg_stat_activity blocking_activity 
    ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
```

### 性能优化结果

1. **库存并发处理能力**：从500 TPS提升到5000 TPS
2. **订单查询响应时间**：从平均200ms降低到20ms
3. **数据库连接池利用率**：从80%降低到30%
4. **锁等待时间**：减少95%

## 金融系统案例

### 场景描述
某银行核心系统，需要处理账户余额、转账交易、风控检查等关键业务，要求强一致性和高可用性。

### 技术挑战
1. **ACID事务保证**：确保资金安全
2. **并发控制**：防止余额不一致
3. **审计日志**：完整的操作记录
4. **性能要求**：毫秒级响应

### 解决方案

#### 1. 数据库设计

```sql
-- 账户表
CREATE TABLE accounts (
    id BIGSERIAL PRIMARY KEY,
    account_no VARCHAR(20) UNIQUE NOT NULL,
    user_id BIGINT NOT NULL,
    account_type VARCHAR(20) NOT NULL, -- 'savings', 'checking', 'credit'
    balance DECIMAL(15,2) NOT NULL DEFAULT 0,
    frozen_amount DECIMAL(15,2) NOT NULL DEFAULT 0,
    currency VARCHAR(3) DEFAULT 'CNY',
    status VARCHAR(20) DEFAULT 'active',
    version BIGINT NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 交易表（按日期分区）
CREATE TABLE transactions (
    id BIGSERIAL,
    transaction_no VARCHAR(32) UNIQUE NOT NULL,
    from_account_id BIGINT,
    to_account_id BIGINT,
    amount DECIMAL(15,2) NOT NULL,
    transaction_type VARCHAR(20) NOT NULL, -- 'transfer', 'deposit', 'withdraw'
    status VARCHAR(20) DEFAULT 'pending',
    description TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP
) PARTITION BY RANGE (created_at);

-- 创建日分区
CREATE TABLE transactions_2024_01_01 PARTITION OF transactions
FOR VALUES FROM ('2024-01-01') TO ('2024-01-02');

-- 账户余额变更日志
CREATE TABLE balance_logs (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT REFERENCES accounts(id),
    transaction_id BIGINT,
    change_type VARCHAR(20) NOT NULL, -- 'debit', 'credit', 'freeze', 'unfreeze'
    amount DECIMAL(15,2) NOT NULL,
    balance_before DECIMAL(15,2) NOT NULL,
    balance_after DECIMAL(15,2) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 索引
CREATE INDEX idx_accounts_user_id ON accounts(user_id);
CREATE INDEX idx_accounts_account_no ON accounts(account_no);
CREATE INDEX idx_transactions_from_account ON transactions(from_account_id, created_at DESC);
CREATE INDEX idx_transactions_to_account ON transactions(to_account_id, created_at DESC);
CREATE INDEX idx_balance_logs_account_created ON balance_logs(account_id, created_at DESC);
```

#### 2. Go实现 - 转账服务

```go
package banking

import (
    "context"
    "database/sql"
    "errors"
    "fmt"
    "time"
    
    "github.com/google/uuid"
    "github.com/shopspring/decimal"
)

type BankingService struct {
    db *sql.DB
}

type TransferRequest struct {
    FromAccountNo string
    ToAccountNo   string
    Amount        decimal.Decimal
    Description   string
}

type Account struct {
    ID           int64
    AccountNo    string
    UserID       int64
    Balance      decimal.Decimal
    FrozenAmount decimal.Decimal
    Version      int64
}

// 转账操作（使用悲观锁确保一致性）
func (s *BankingService) Transfer(ctx context.Context, req TransferRequest) error {
    if req.Amount.LessThanOrEqual(decimal.Zero) {
        return errors.New("transfer amount must be positive")
    }
    
    tx, err := s.db.BeginTx(ctx, &sql.TxOptions{
        Isolation: sql.LevelSerializable, // 最高隔离级别
    })
    if err != nil {
        return err
    }
    defer tx.Rollback()
    
    // 1. 锁定并获取转出账户（按账户号排序避免死锁）
    var fromAccount, toAccount Account
    
    // 确保按固定顺序锁定账户，避免死锁
    firstAccountNo, secondAccountNo := req.FromAccountNo, req.ToAccountNo
    if req.FromAccountNo > req.ToAccountNo {
        firstAccountNo, secondAccountNo = req.ToAccountNo, req.FromAccountNo
    }
    
    // 锁定第一个账户
    var firstAccount Account
    err = tx.QueryRowContext(ctx, `
        SELECT id, account_no, user_id, balance, frozen_amount, version
        FROM accounts 
        WHERE account_no = $1 AND status = 'active'
        FOR UPDATE
    `, firstAccountNo).Scan(
        &firstAccount.ID, &firstAccount.AccountNo, &firstAccount.UserID,
        &firstAccount.Balance, &firstAccount.FrozenAmount, &firstAccount.Version)
    
    if err != nil {
        return fmt.Errorf("lock first account: %w", err)
    }
    
    // 锁定第二个账户
    var secondAccount Account
    err = tx.QueryRowContext(ctx, `
        SELECT id, account_no, user_id, balance, frozen_amount, version
        FROM accounts 
        WHERE account_no = $1 AND status = 'active'
        FOR UPDATE
    `, secondAccountNo).Scan(
        &secondAccount.ID, &secondAccount.AccountNo, &secondAccount.UserID,
        &secondAccount.Balance, &secondAccount.FrozenAmount, &secondAccount.Version)
    
    if err != nil {
        return fmt.Errorf("lock second account: %w", err)
    }
    
    // 确定转出和转入账户
    if firstAccount.AccountNo == req.FromAccountNo {
        fromAccount, toAccount = firstAccount, secondAccount
    } else {
        fromAccount, toAccount = secondAccount, firstAccount
    }
    
    // 2. 检查转出账户余额
    availableBalance := fromAccount.Balance.Sub(fromAccount.FrozenAmount)
    if availableBalance.LessThan(req.Amount) {
        return fmt.Errorf("insufficient balance: available=%s, required=%s", 
            availableBalance.String(), req.Amount.String())
    }
    
    // 3. 创建交易记录
    transactionNo := generateTransactionNo()
    var transactionID int64
    
    err = tx.QueryRowContext(ctx, `
        INSERT INTO transactions (transaction_no, from_account_id, to_account_id, amount, transaction_type, description, status)
        VALUES ($1, $2, $3, $4, 'transfer', $5, 'processing')
        RETURNING id
    `, transactionNo, fromAccount.ID, toAccount.ID, req.Amount, req.Description).Scan(&transactionID)
    
    if err != nil {
        return fmt.Errorf("create transaction: %w", err)
    }
    
    // 4. 更新转出账户余额
    newFromBalance := fromAccount.Balance.Sub(req.Amount)
    _, err = tx.ExecContext(ctx, `
        UPDATE accounts 
        SET balance = $1, version = version + 1, updated_at = NOW()
        WHERE id = $2
    `, newFromBalance, fromAccount.ID)
    
    if err != nil {
        return fmt.Errorf("update from account: %w", err)
    }
    
    // 5. 记录转出账户余额变更日志
    _, err = tx.ExecContext(ctx, `
        INSERT INTO balance_logs (account_id, transaction_id, change_type, amount, balance_before, balance_after)
        VALUES ($1, $2, 'debit', $3, $4, $5)
    `, fromAccount.ID, transactionID, req.Amount, fromAccount.Balance, newFromBalance)
    
    if err != nil {
        return fmt.Errorf("log from account change: %w", err)
    }
    
    // 6. 更新转入账户余额
    newToBalance := toAccount.Balance.Add(req.Amount)
    _, err = tx.ExecContext(ctx, `
        UPDATE accounts 
        SET balance = $1, version = version + 1, updated_at = NOW()
        WHERE id = $2
    `, newToBalance, toAccount.ID)
    
    if err != nil {
        return fmt.Errorf("update to account: %w", err)
    }
    
    // 7. 记录转入账户余额变更日志
    _, err = tx.ExecContext(ctx, `
        INSERT INTO balance_logs (account_id, transaction_id, change_type, amount, balance_before, balance_after)
        VALUES ($1, $2, 'credit', $3, $4, $5)
    `, toAccount.ID, transactionID, req.Amount, toAccount.Balance, newToBalance)
    
    if err != nil {
        return fmt.Errorf("log to account change: %w", err)
    }
    
    // 8. 更新交易状态为完成
    _, err = tx.ExecContext(ctx, `
        UPDATE transactions 
        SET status = 'completed', completed_at = NOW()
        WHERE id = $1
    `, transactionID)
    
    if err != nil {
        return fmt.Errorf("complete transaction: %w", err)
    }
    
    return tx.Commit()
}

func generateTransactionNo() string {
    return fmt.Sprintf("TXN%d%s", 
        time.Now().Unix(), 
        uuid.New().String()[:8])
}

// 查询账户余额
func (s *BankingService) GetAccountBalance(ctx context.Context, accountNo string) (*Account, error) {
    var account Account
    err := s.db.QueryRowContext(ctx, `
        SELECT id, account_no, user_id, balance, frozen_amount, version
        FROM accounts 
        WHERE account_no = $1 AND status = 'active'
    `, accountNo).Scan(
        &account.ID, &account.AccountNo, &account.UserID,
        &account.Balance, &account.FrozenAmount, &account.Version)
    
    if err != nil {
        return nil, err
    }
    
    return &account, nil
}

// 查询交易历史
func (s *BankingService) GetTransactionHistory(ctx context.Context, accountNo string, limit int) ([]Transaction, error) {
    query := `
        SELECT t.id, t.transaction_no, t.from_account_id, t.to_account_id, 
               t.amount, t.transaction_type, t.status, t.description, t.created_at
        FROM transactions t
        JOIN accounts a1 ON t.from_account_id = a1.id
        JOIN accounts a2 ON t.to_account_id = a2.id
        WHERE a1.account_no = $1 OR a2.account_no = $1
        ORDER BY t.created_at DESC
        LIMIT $2
    `
    
    rows, err := s.db.QueryContext(ctx, query, accountNo, limit)
    if err != nil {
        return nil, err
    }
    defer rows.Close()
    
    var transactions []Transaction
    for rows.Next() {
        var t Transaction
        err := rows.Scan(
            &t.ID, &t.TransactionNo, &t.FromAccountID, &t.ToAccountID,
            &t.Amount, &t.TransactionType, &t.Status, &t.Description, &t.CreatedAt)
        if err != nil {
            return nil, err
        }
        transactions = append(transactions, t)
    }
    
    return transactions, nil
}
```

#### 3. 风控检查

```go
type RiskControlService struct {
    db *sql.DB
}

// 风控检查
func (r *RiskControlService) CheckTransferRisk(ctx context.Context, req TransferRequest) error {
    // 1. 检查单笔限额
    if req.Amount.GreaterThan(decimal.NewFromInt(100000)) {
        return errors.New("single transaction limit exceeded")
    }
    
    // 2. 检查日累计限额
    var dailyTotal decimal.Decimal
    err := r.db.QueryRowContext(ctx, `
        SELECT COALESCE(SUM(amount), 0)
        FROM transactions t
        JOIN accounts a ON t.from_account_id = a.id
        WHERE a.account_no = $1 
        AND t.status = 'completed'
        AND t.created_at >= CURRENT_DATE
    `, req.FromAccountNo).Scan(&dailyTotal)
    
    if err != nil {
        return err
    }
    
    if dailyTotal.Add(req.Amount).GreaterThan(decimal.NewFromInt(500000)) {
        return errors.New("daily transaction limit exceeded")
    }
    
    // 3. 检查频率限制
    var recentCount int
    err = r.db.QueryRowContext(ctx, `
        SELECT COUNT(*)
        FROM transactions t
        JOIN accounts a ON t.from_account_id = a.id
        WHERE a.account_no = $1 
        AND t.created_at >= NOW() - INTERVAL '1 hour'
    `, req.FromAccountNo).Scan(&recentCount)
    
    if err != nil {
        return err
    }
    
    if recentCount >= 10 {
        return errors.New("transaction frequency limit exceeded")
    }
    
    return nil
}
```

### 性能监控

```sql
-- 监控转账性能
SELECT 
    DATE_TRUNC('hour', created_at) as hour,
    COUNT(*) as transaction_count,
    AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) as avg_duration_seconds
FROM transactions
WHERE created_at >= NOW() - INTERVAL '24 hours'
AND status = 'completed'
GROUP BY DATE_TRUNC('hour', created_at)
ORDER BY hour;

-- 监控账户余额分布
SELECT 
    CASE 
        WHEN balance < 1000 THEN '< 1K'
        WHEN balance < 10000 THEN '1K-10K'
        WHEN balance < 100000 THEN '10K-100K'
        ELSE '> 100K'
    END as balance_range,
    COUNT(*) as account_count
FROM accounts
WHERE status = 'active'
GROUP BY balance_range;
```

## 日志分析系统案例

### 场景描述
某互联网公司的日志分析系统，每日处理10TB+的日志数据，需要实时查询和分析。

### 技术挑战
1. **海量数据存储**：TB级别数据
2. **实时写入性能**：每秒百万条记录
3. **复杂查询支持**：多维度分析
4. **数据生命周期管理**：自动清理历史数据

### 解决方案

#### 1. 数据库设计

```sql
-- 日志表（时间分区 + 压缩）
CREATE TABLE access_logs (
    id BIGSERIAL,
    timestamp TIMESTAMPTZ NOT NULL,
    ip_address INET NOT NULL,
    user_agent TEXT,
    request_method VARCHAR(10) NOT NULL,
    request_path TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    response_time_ms INTEGER NOT NULL,
    bytes_sent BIGINT NOT NULL,
    referer TEXT,
    user_id BIGINT,
    session_id VARCHAR(64),
    geo_country VARCHAR(2),
    geo_city VARCHAR(100)
) PARTITION BY RANGE (timestamp);

-- 创建小时分区（高频写入）
CREATE TABLE access_logs_2024_01_01_00 PARTITION OF access_logs
FOR VALUES FROM ('2024-01-01 00:00:00+00') TO ('2024-01-01 01:00:00+00');

CREATE TABLE access_logs_2024_01_01_01 PARTITION OF access_logs
FOR VALUES FROM ('2024-01-01 01:00:00+00') TO ('2024-01-01 02:00:00+00');

-- 错误日志表
CREATE TABLE error_logs (
    id BIGSERIAL,
    timestamp TIMESTAMPTZ NOT NULL,
    level VARCHAR(10) NOT NULL, -- ERROR, WARN, INFO
    service_name VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    stack_trace TEXT,
    request_id VARCHAR(64),
    user_id BIGINT,
    metadata JSONB
) PARTITION BY RANGE (timestamp);

-- 性能指标表（预聚合）
CREATE TABLE performance_metrics (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    metric_name VARCHAR(100) NOT NULL,
    metric_value DOUBLE PRECISION NOT NULL,
    tags JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 索引优化
CREATE INDEX idx_access_logs_timestamp ON access_logs(timestamp DESC);
CREATE INDEX idx_access_logs_status_timestamp ON access_logs(status_code, timestamp DESC);
CREATE INDEX idx_access_logs_user_timestamp ON access_logs(user_id, timestamp DESC) WHERE user_id IS NOT NULL;
CREATE INDEX idx_access_logs_path_gin ON access_logs USING gin(to_tsvector('english', request_path));
CREATE INDEX idx_error_logs_service_timestamp ON error_logs(service_name, timestamp DESC);
CREATE INDEX idx_error_logs_level_timestamp ON error_logs(level, timestamp DESC);
```

#### 2. Go实现 - 日志收集服务

```go
package logging

import (
    "context"
    "database/sql"
    "encoding/json"
    "fmt"
    "net"
    "sync"
    "time"
    
    "github.com/lib/pq"
)

type LogCollector struct {
    db          *sql.DB
    batchSize   int
    flushInterval time.Duration
    logBuffer   []AccessLog
    errorBuffer []ErrorLog
    mutex       sync.Mutex
    stopCh      chan struct{}
}

type AccessLog struct {
    Timestamp      time.Time `json:"timestamp"`
    IPAddress      string    `json:"ip_address"`
    UserAgent      string    `json:"user_agent"`
    RequestMethod  string    `json:"request_method"`
    RequestPath    string    `json:"request_path"`
    StatusCode     int       `json:"status_code"`
    ResponseTimeMs int       `json:"response_time_ms"`
    BytesSent      int64     `json:"bytes_sent"`
    Referer        string    `json:"referer"`
    UserID         *int64    `json:"user_id,omitempty"`
    SessionID      string    `json:"session_id"`
    GeoCountry     string    `json:"geo_country"`
    GeoCity        string    `json:"geo_city"`
}

type ErrorLog struct {
    Timestamp   time.Time              `json:"timestamp"`
    Level       string                 `json:"level"`
    ServiceName string                 `json:"service_name"`
    Message     string                 `json:"message"`
    StackTrace  string                 `json:"stack_trace,omitempty"`
    RequestID   string                 `json:"request_id,omitempty"`
    UserID      *int64                 `json:"user_id,omitempty"`
    Metadata    map[string]interface{} `json:"metadata,omitempty"`
}

func NewLogCollector(db *sql.DB) *LogCollector {
    return &LogCollector{
        db:            db,
        batchSize:     1000,
        flushInterval: 5 * time.Second,
        stopCh:        make(chan struct{}),
    }
}

func (lc *LogCollector) Start() {
    ticker := time.NewTicker(lc.flushInterval)
    defer ticker.Stop()
    
    for {
        select {
        case <-ticker.C:
            lc.flush()
        case <-lc.stopCh:
            lc.flush() // 最后一次刷新
            return
        }
    }
}

func (lc *LogCollector) Stop() {
    close(lc.stopCh)
}

// 批量写入访问日志
func (lc *LogCollector) WriteAccessLog(log AccessLog) {
    lc.mutex.Lock()
    defer lc.mutex.Unlock()
    
    lc.logBuffer = append(lc.logBuffer, log)
    
    if len(lc.logBuffer) >= lc.batchSize {
        go lc.flushAccessLogs()
    }
}

// 批量写入错误日志
func (lc *LogCollector) WriteErrorLog(log ErrorLog) {
    lc.mutex.Lock()
    defer lc.mutex.Unlock()
    
    lc.errorBuffer = append(lc.errorBuffer, log)
    
    if len(lc.errorBuffer) >= lc.batchSize {
        go lc.flushErrorLogs()
    }
}

func (lc *LogCollector) flush() {
    lc.flushAccessLogs()
    lc.flushErrorLogs()
}

func (lc *LogCollector) flushAccessLogs() {
    lc.mutex.Lock()
    if len(lc.logBuffer) == 0 {
        lc.mutex.Unlock()
        return
    }
    
    logs := make([]AccessLog, len(lc.logBuffer))
    copy(logs, lc.logBuffer)
    lc.logBuffer = lc.logBuffer[:0] // 清空缓冲区
    lc.mutex.Unlock()
    
    // 使用COPY进行批量插入
    ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
    defer cancel()
    
    tx, err := lc.db.BeginTx(ctx, nil)
    if err != nil {
        fmt.Printf("Failed to begin transaction: %v\n", err)
        return
    }
    defer tx.Rollback()
    
    stmt, err := tx.PrepareContext(ctx, pq.CopyIn(
        "access_logs",
        "timestamp", "ip_address", "user_agent", "request_method",
        "request_path", "status_code", "response_time_ms", "bytes_sent",
        "referer", "user_id", "session_id", "geo_country", "geo_city",
    ))
    if err != nil {
        fmt.Printf("Failed to prepare COPY statement: %v\n", err)
        return
    }
    defer stmt.Close()
    
    for _, log := range logs {
        _, err = stmt.ExecContext(ctx,
            log.Timestamp, log.IPAddress, log.UserAgent, log.RequestMethod,
            log.RequestPath, log.StatusCode, log.ResponseTimeMs, log.BytesSent,
            log.Referer, log.UserID, log.SessionID, log.GeoCountry, log.GeoCity,
        )
        if err != nil {
            fmt.Printf("Failed to exec COPY: %v\n", err)
            return
        }
    }
    
    _, err = stmt.ExecContext(ctx)
    if err != nil {
        fmt.Printf("Failed to finalize COPY: %v\n", err)
        return
    }
    
    if err = tx.Commit(); err != nil {
        fmt.Printf("Failed to commit transaction: %v\n", err)
        return
    }
    
    fmt.Printf("Successfully inserted %d access logs\n", len(logs))
}

func (lc *LogCollector) flushErrorLogs() {
    lc.mutex.Lock()
    if len(lc.errorBuffer) == 0 {
        lc.mutex.Unlock()
        return
    }
    
    logs := make([]ErrorLog, len(lc.errorBuffer))
    copy(logs, lc.errorBuffer)
    lc.errorBuffer = lc.errorBuffer[:0]
    lc.mutex.Unlock()
    
    ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
    defer cancel()
    
    tx, err := lc.db.BeginTx(ctx, nil)
    if err != nil {
        fmt.Printf("Failed to begin transaction: %v\n", err)
        return
    }
    defer tx.Rollback()
    
    stmt, err := tx.PrepareContext(ctx, pq.CopyIn(
        "error_logs",
        "timestamp", "level", "service_name", "message",
        "stack_trace", "request_id", "user_id", "metadata",
    ))
    if err != nil {
        fmt.Printf("Failed to prepare COPY statement: %v\n", err)
        return
    }
    defer stmt.Close()
    
    for _, log := range logs {
        var metadataJSON []byte
        if log.Metadata != nil {
            metadataJSON, _ = json.Marshal(log.Metadata)
        }
        
        _, err = stmt.ExecContext(ctx,
            log.Timestamp, log.Level, log.ServiceName, log.Message,
            log.StackTrace, log.RequestID, log.UserID, metadataJSON,
        )
        if err != nil {
            fmt.Printf("Failed to exec COPY: %v\n", err)
            return
        }
    }
    
    _, err = stmt.ExecContext(ctx)
    if err != nil {
        fmt.Printf("Failed to finalize COPY: %v\n", err)
        return
    }
    
    if err = tx.Commit(); err != nil {
        fmt.Printf("Failed to commit transaction: %v\n", err)
        return
    }
    
    fmt.Printf("Successfully inserted %d error logs\n", len(logs))
}
```

#### 3. 日志分析服务

```go
type LogAnalyzer struct {
    db *sql.DB
}

// 获取访问统计
func (la *LogAnalyzer) GetAccessStats(ctx context.Context, startTime, endTime time.Time) (*AccessStats, error) {
    query := `
        SELECT 
            COUNT(*) as total_requests,
            COUNT(DISTINCT ip_address) as unique_visitors,
            AVG(response_time_ms) as avg_response_time,
            SUM(bytes_sent) as total_bytes_sent,
            COUNT(*) FILTER (WHERE status_code >= 400) as error_count
        FROM access_logs
        WHERE timestamp >= $1 AND timestamp < $2
    `
    
    var stats AccessStats
    err := la.db.QueryRowContext(ctx, query, startTime, endTime).Scan(
        &stats.TotalRequests,
        &stats.UniqueVisitors,
        &stats.AvgResponseTime,
        &stats.TotalBytesSent,
        &stats.ErrorCount,
    )
    
    return &stats, err
}

// 获取热门页面
func (la *LogAnalyzer) GetTopPages(ctx context.Context, startTime, endTime time.Time, limit int) ([]PageStats, error) {
    query := `
        SELECT 
            request_path,
            COUNT(*) as request_count,
            AVG(response_time_ms) as avg_response_time,
            COUNT(*) FILTER (WHERE status_code >= 400) as error_count
        FROM access_logs
        WHERE timestamp >= $1 AND timestamp < $2
        GROUP BY request_path
        ORDER BY request_count DESC
        LIMIT $3
    `
    
    rows, err := la.db.QueryContext(ctx, query, startTime, endTime, limit)
    if err != nil {
        return nil, err
    }
    defer rows.Close()
    
    var pages []PageStats
    for rows.Next() {
        var page PageStats
        err := rows.Scan(
            &page.Path,
            &page.RequestCount,
            &page.AvgResponseTime,
            &page.ErrorCount,
        )
        if err != nil {
            return nil, err
        }
        pages = append(pages, page)
    }
    
    return pages, nil
}

// 获取错误统计
func (la *LogAnalyzer) GetErrorStats(ctx context.Context, startTime, endTime time.Time) ([]ErrorStats, error) {
    query := `
        SELECT 
            service_name,
            level,
            COUNT(*) as error_count,
            COUNT(DISTINCT user_id) as affected_users
        FROM error_logs
        WHERE timestamp >= $1 AND timestamp < $2
        GROUP BY service_name, level
        ORDER BY error_count DESC
    `
    
    rows, err := la.db.QueryContext(ctx, query, startTime, endTime)
    if err != nil {
        return nil, err
    }
    defer rows.Close()
    
    var stats []ErrorStats
    for rows.Next() {
        var stat ErrorStats
        err := rows.Scan(
            &stat.ServiceName,
            &stat.Level,
            &stat.ErrorCount,
            &stat.AffectedUsers,
        )
        if err != nil {
            return nil, err
        }
        stats = append(stats, stat)
    }
    
    return stats, nil
}
```

#### 4. 数据生命周期管理

```sql
-- 自动分区管理函数
CREATE OR REPLACE FUNCTION create_hourly_partition(
    table_name TEXT,
    start_time TIMESTAMPTZ
) RETURNS VOID AS $$
DECLARE
    partition_name TEXT;
    end_time TIMESTAMPTZ;
BEGIN
    partition_name := table_name || '_' || to_char(start_time, 'YYYY_MM_DD_HH24');
    end_time := start_time + INTERVAL '1 hour';
    
    EXECUTE format(
        'CREATE TABLE %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
        partition_name, table_name, start_time, end_time
    );
    
    -- 创建索引
    EXECUTE format(
        'CREATE INDEX idx_%s_timestamp ON %I(timestamp DESC)',
        partition_name, partition_name
    );
END;
$$ LANGUAGE plpgsql;

-- 删除旧分区函数
CREATE OR REPLACE FUNCTION drop_old_partitions(
    table_name TEXT,
    retention_days INTEGER
) RETURNS INTEGER AS $$
DECLARE
    partition_record RECORD;
    dropped_count INTEGER := 0;
BEGIN
    FOR partition_record IN
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE tablename LIKE table_name || '_%'
        AND tablename < table_name || '_' || to_char(NOW() - (retention_days || ' days')::INTERVAL, 'YYYY_MM_DD_HH24')
    LOOP
        EXECUTE format('DROP TABLE %I.%I', partition_record.schemaname, partition_record.tablename);
        dropped_count := dropped_count + 1;
    END LOOP;
    
    RETURN dropped_count;
END;
$$ LANGUAGE plpgsql;

-- 定期执行清理任务
SELECT drop_old_partitions('access_logs', 30);  -- 保留30天
SELECT drop_old_partitions('error_logs', 90);   -- 保留90天
```

### 性能优化结果

1. **写入性能**：从10万TPS提升到100万TPS
2. **查询响应时间**：复杂分析查询从分钟级降低到秒级
3. **存储空间**：通过分区和压缩节省60%存储空间
4. **运维效率**：自动化分区管理，减少90%人工操作

## 4. 分布式金融系统实践
### 4.1 场景描述
某银行核心交易系统需要支持每秒万级交易，同时保证ACID特性

### 4.2 技术方案
- 使用Citus扩展实现分库分表：
  ```sql
  -- 创建分布表
  SELECT create_distributed_table('transactions', 'account_id');
  -- 创建参考表
  SELECT create_reference_table('accounts');
  ```
- 采用强一致性事务：
  - 跨分片操作使用2PC协议
  - 设置default_transaction_isolation为'read committed'

### 4.3 遇到的问题
- 热点账户问题：通过流水号+余额分离设计解决
- 跨分片查询：创建物化视图预计算汇总数据
- 高可用切换：Patroni+etcd实现自动故障转移

## 总结

通过这些实战案例，我们可以看到PostgreSQL在不同场景下的应用策略：

### 关键技术点

1. **事务管理**：根据业务需求选择合适的隔离级别
2. **并发控制**：乐观锁vs悲观锁的选择
3. **分区策略**：时间分区、范围分区的应用
4. **索引优化**：复合索引、部分索引、GIN索引的使用
5. **批量操作**：COPY命令提升写入性能
6. **连接池管理**：合理配置连接池参数

### 最佳实践

1. **设计阶段**：充分考虑数据增长和查询模式
2. **开发阶段**：使用预编译语句，避免SQL注入
3. **测试阶段**：进行压力测试，验证并发性能
4. **运维阶段**：监控关键指标，及时优化
5. **扩展阶段**：考虑读写分离、分库分表策略

这些案例展示了PostgreSQL在企业级应用中的强大能力，为Go高级开发工程师面试提供了丰富的实战经验参考。