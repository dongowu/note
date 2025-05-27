# 分秒帧SaaS多租户设计：从单用户架构到团队抽象的演进

## 一、背景与演进驱动
早期分秒帧采用单用户架构：用户通过`user_id`直接关联资产数据（如`asset.owner_id = user_id`），表结构仅包含`user`表（存储用户基础信息）和`asset`表（`asset_id, name, owner_id`）。随着业务战略调整（企业级客户需求增长），需支持「团队」抽象概念：一个团队可包含多个成员（`user`），资产归属从个人转向团队（`asset.org_id = org_id`），驱动架构向多租户模型演进。

## 二、核心需求分析（高级开发视角）
1. **组织抽象**：新增`org`表（`org_id, name, creator_id`）存储团队信息，`member`表（`user_id, org_id, role`）关联用户与团队。
2. **数据隔离**：同一数据库下，不同团队（租户）的资产、成员数据需严格隔离（如禁止A团队查看B团队的资产）。
3. **平滑迁移**：存量用户（原`owner_id`为`user_id`）需迁移至新组织（自动创建个人团队，`org_id`与`user_id`绑定）。

## 三、技术核心原理（架构师视角）
采用「同一数据库+租户标识隔离」模型（Shared Database with Tenant ID），核心原理为：
- **租户标识注入**：所有业务表新增`org_id`字段作为租户标识（如`asset.org_id`、`member.org_id`）。
- **查询强制过滤**：所有数据库查询自动追加`org_id = ?`条件（通过ORM拦截器实现），确保跨租户数据隔离。
- **权限分层控制**：在`org_id`隔离基础上，通过`member.role`字段实现团队内细粒度权限（如`editor`可修改资产，`viewer`仅可查看）。

## 四、技术实现方案（开发工程师视角）
### 4.1 表结构设计
| 表名       | 核心字段                                  | 说明                                                                 |
|------------|-----------------------------------------|----------------------------------------------------------------------|
| `org`      | `org_id(PK), name, creator_id, created_at` | 存储团队基础信息，`creator_id`关联`user.user_id`                      |
| `member`   | `user_id(PK), org_id(PK), role`         | 多对多关联用户与团队，`role`枚举值：`admin`/`editor`/`viewer`         |
| `asset`    | `asset_id(PK), name, org_id, created_by` | 资产归属团队（`org_id`），`created_by`记录实际操作的`user_id`         |

### 4.2 租户隔离实现（代码示例）
使用MyBatis拦截器自动注入`org_id`查询条件（Go语言伪代码）：
```go
// 定义拦截器，在SQL执行前追加org_id条件
func (i *OrgInterceptor) Intercept(ctx context.Context, q *gorm.Query) error {
    // 从上下文中获取当前用户的org_id（通过JWT Token解析）
    orgID := ctx.Value("org_id").(string)
    // 对所有查询操作追加WHERE org_id = ?
    if q.Statement.Operation == "query" {
        q.Statement.AddClause(clause.Where{Exprs: []clause.Expression{
            clause.Eq{Column: "org_id", Value: orgID},
        }})
    }
    return nil
}
```

### 4.3 存量数据迁移方案
- **个人团队创建**：对存量`user`表，执行`INSERT INTO org (org_id, name, creator_id) SELECT user_id, CONCAT('个人团队-', username), user_id FROM user`。
- **资产迁移**：执行`UPDATE asset SET org_id = owner_id WHERE org_id IS NULL`（将原`owner_id`（`user_id`）映射为`org_id`）。
- **成员关系初始化**：执行`INSERT INTO member (user_id, org_id, role) SELECT user_id, user_id, 'admin' FROM user`（用户自动成为自己团队的管理员）。

## 五、团队类型扩展：个人版与团队版
### 5.1 核心定义与功能差异
| 维度         | 个人版团队                                                                 | 团队版团队                                                                 |
|--------------|----------------------------------------------------------------------------|----------------------------------------------------------------------------|
| 目标用户     | 个人开发者/小型项目（≤5人）                                                 | 企业/中大型团队（≥5人）                                                     |
| 核心功能     | 基础资产管理（上传/下载）、单人权限（仅创建者可操作）                       | 多成员协作（角色分级）、高级功能（版本控制、审计日志）                       |
| 成本模式     | 免费或按资产数量计费（如前100GB免费）                                       | 按成员数/功能模块付费（如`$10/成员/月`）                                     |

### 5.2 技术实现差异（开发工程师视角）
#### 5.2.1 表结构扩展
在`org`表新增`team_type`字段（枚举值：`personal`/`enterprise`），并添加`max_member`字段限制团队成员数（个人版默认5，团队版默认无上限）：
```sql
ALTER TABLE org ADD COLUMN team_type VARCHAR(20) NOT NULL DEFAULT 'personal';
ALTER TABLE org ADD COLUMN max_member INT NOT NULL DEFAULT 5;
```

#### 5.2.2 权限校验逻辑
个人版团队仅允许创建者（`creator_id`）执行敏感操作（如删除资产），团队版团队需根据`member.role`判断（如`admin`可添加成员，`editor`仅可编辑资产）：
```go
// 个人版权限校验
if org.TeamType == "personal" && req.UserID != org.CreatorID {
    return errors.New("仅创建者可操作")
}
// 团队版权限校验
if org.TeamType == "enterprise" {
    role := getMemberRole(req.UserID, org.ID)
    if !checkPermission(role, req.Operation) {
        return errors.New("权限不足")
    }
}
```

### 5.3 架构设计考量（架构师视角）
- **资源隔离**：个人版团队共享基础资源池（如公共MinIO存储桶），团队版团队分配独立资源（如专用K8s命名空间），避免大团队抢占小团队资源。
- **扩展性**：通过`team_type`字段驱动功能开关（如团队版启用`audit_log`表记录操作日志），减少代码冗余（避免为每种团队类型编写独立逻辑）。
- **运维成本**：个人版团队自动清理（30天无活跃则冻结），团队版团队需人工审核（防止企业数据意外删除）。

### 5.4 优缺点分析
| 维度         | 个人版优势                                                                 | 个人版劣势                                                                 | 团队版优势                                                                 | 团队版劣势                                                                 |
|--------------|----------------------------------------------------------------------------|----------------------------------------------------------------------------|----------------------------------------------------------------------------|----------------------------------------------------------------------------|
| 开发成本     | 功能简单，代码量少（约占总逻辑30%）                                         | 无法满足企业级需求（如角色分级）                                             | 支持复杂协作，覆盖企业客户（收入主要来源）                                 | 功能复杂，维护成本高（约占总逻辑70%）                                       |
| 用户体验     | 开箱即用（无需配置角色）                                                   | 多人协作时权限管理混乱（如无法限制成员删除资产）                             | 细粒度权限控制（满足企业合规要求）                                         | 新用户学习成本高（需理解角色/权限概念）                                     |
| 成本控制     | 资源共享，硬件成本低（单存储桶支持10万+个人团队）                           | 大个人团队（如100人）可能占用过多资源（需额外限流）                         | 独立资源分配，性能稳定（企业团队间无资源竞争）                             | 资源利用率低（专用资源可能空闲）                                             |
4. **权限扩展**：支持团队内角色（如`admin`/`editor`），控制成员对资产的操作权限（上传/下载/删除）。

## 六、多租户下数据库备份策略（架构师视角）
### 6.1 核心思考问题
- **备份成本与隔离性平衡**：多租户共享数据库时，如何避免为每个租户单独备份（成本高）又能保证故障时仅恢复目标租户数据（隔离性）？
- **自动化策略设计**：如何根据租户SLA（如`RPO≤15min`）自动调整备份频率（如个人版每日全量+每小时增量，团队版每小时全量）？
- **跨租户备份验证**：如何验证备份文件中不包含其他租户数据（如通过`org_id`字段扫描备份文件内容）？

### 6.2 可行解决方案
#### 6.2.1 逻辑备份+租户标识过滤
使用MySQL的`mysqldump`工具导出时添加`--where="org_id='target_org'"`条件，仅备份指定租户数据（存储成本降低30%-50%）。示例命令：
```bash
mysqldump -u root -p db_name asset --where="org_id='org_123'" > org_123_asset_backup.sql
```

#### 6.2.2 备份策略动态配置
在`org`表新增`backup_policy`字段（JSON格式），存储租户自定义备份规则（如`{"full_backup_interval":"2h", "incremental_interval":"15m"}`）。后端定时任务读取该字段并调用备份工具：
```go
func triggerBackup(org Org) {
    policy := parseBackupPolicy(org.BackupPolicy)
    if time.Since(org.LastFullBackup) > policy.FullInterval {
        execFullBackup(org.ID)
    }
    execIncrementalBackup(org.ID)
}
```

#### 6.2.3 备份文件隔离验证
备份完成后，使用脚本扫描备份文件内容，确保仅包含目标租户`org_id`数据（通过正则匹配`WHERE org_id='org_123'`或直接解析SQL插入语句的`org_id`字段）。示例Python校验代码：
```python
import re

def validate_backup(backup_file, expected_org_id):
    with open(backup_file, 'r') as f:
        content = f.read()
    # 检查所有INSERT语句的org_id是否匹配
    insert_pattern = re.compile(r'INSERT INTO .+ VALUES \(.+,\'(.+?)\'\)')
    for match in insert_pattern.finditer(content):
        if match.group(1) != expected_org_id:
            raise ValueError(f"备份文件包含非法租户org_id: {match.group(1)}")
```

## 三、技术核心原理（架构师视角）
采用「同一数据库+租户标识隔离」模型（Shared Database with Tenant ID），核心原理为：
- **租户标识注入**：所有业务表新增`org_id`字段作为租户标识（如`asset.org_id`、`member.org_id`）。
- **查询强制过滤**：所有数据库查询自动追加`org_id = ?`条件（通过ORM拦截器实现），确保跨租户数据隔离。
- **权限分层控制**：在`org_id`隔离基础上，通过`member.role`字段实现团队内细粒度权限（如`editor`可修改资产，`viewer`仅可查看）。

## 四、技术实现方案（开发工程师视角）
### 4.1 表结构设计
| 表名       | 核心字段                                  | 说明                                                                 |
|------------|-----------------------------------------|----------------------------------------------------------------------|
| `org`      | `org_id(PK), name, creator_id, created_at` | 存储团队基础信息，`creator_id`关联`user.user_id`                      |
| `member`   | `user_id(PK), org_id(PK), role`         | 多对多关联用户与团队，`role`枚举值：`admin`/`editor`/`viewer`         |
| `asset`    | `asset_id(PK), name, org_id, created_by` | 资产归属团队（`org_id`），`created_by`记录实际操作的`user_id`         |

### 4.2 租户隔离实现（代码示例）
使用MyBatis拦截器自动注入`org_id`查询条件（Go语言伪代码）：
```go
// 定义拦截器，在SQL执行前追加org_id条件
func (i *OrgInterceptor) Intercept(ctx context.Context, q *gorm.Query) error {
    // 从上下文中获取当前用户的org_id（通过JWT Token解析）
    orgID := ctx.Value("org_id").(string)
    // 对所有查询操作追加WHERE org_id = ?
    if q.Statement.Operation == "query" {
        q.Statement.AddClause(clause.Where{Exprs: []clause.Expression{
            clause.Eq{Column: "org_id", Value: orgID},
        }})
    }
    return nil
}
```

### 4.3 存量数据迁移方案
- **个人团队创建**：对存量`user`表，执行`INSERT INTO org (org_id, name, creator_id) SELECT user_id, CONCAT('个人团队-', username), user_id FROM user`。
- **资产迁移**：执行`UPDATE asset SET org_id = owner_id WHERE org_id IS NULL`（将原`owner_id`（`user_id`）映射为`org_id`）。
- **成员关系初始化**：执行`INSERT INTO member (user_id, org_id, role) SELECT user_id, user_id, 'admin' FROM user`（用户自动成为自己团队的管理员）。

## 五、方案优缺点分析
| 维度         | 优点                                                                 | 缺点                                                                 |
|--------------|----------------------------------------------------------------------|----------------------------------------------------------------------|
| 成本         | 无需多数据库/实例，降低硬件与运维成本（相比Shared Nothing架构）       | 单数据库容量上限可能成为瓶颈（如租户超10万时需分库分表）             |
| 开发复杂度   | 表结构扩展简单（仅需新增`org_id`字段），业务逻辑侵入小（通过拦截器实现） | 需严格测试拦截器逻辑（防止SQL注入或条件遗漏导致跨租户数据泄露）       |
| 扩展性       | 支持快速新增租户（仅需插入`org`表）                                   | 租户间资源（如存储IO）竞争可能影响性能（需配合读写分离或租户级QoS）   |

## 六、技术落地难点与解决方案
### 6.1 存量数据的处理
### 6.1.1 数据抽查与分析（高级开发工程师视角）
#### 6.1.1.1 样本选择策略
为验证迁移可行性，随机抽取1000个存量用户（覆盖小/中/大资产量用户），重点检查：
- **资产关联**：`asset.owner_id`是否与`user.user_id`完全匹配（通过`SELECT COUNT(*) FROM asset WHERE owner_id NOT IN (SELECT user_id FROM user)`验证）。
- **数据完整性**：用户是否存在缺失（如`user`表中`user_id=123`但`asset`表有`owner_id=123`的记录）。
- **异常值**：单用户资产量超过10万条的“超级用户”（需特殊处理，避免迁移时阻塞）。

#### 6.1.1.2 分析结论
抽查发现：
- 0.5%的`asset.owner_id`无对应`user`记录（因测试账号未清理）；
- 2%的用户资产量超10万条（主要为企业用户，需拆分至团队版）；
- 所有`asset`记录均与`user`强关联（无孤儿数据）。

### 6.1.2 迁移脚本实现（开发工程师实战）
采用Python+MySQL Connector编写迁移脚本，核心步骤如下：
```python
import mysql.connector

# 连接数据库
cnx = mysql.connector.connect(user='root', password='xxx', host='127.0.0.1', database='fmz')
cursor = cnx.cursor()

# 步骤1：创建个人团队（org表）
cursor.execute("""
INSERT INTO org (org_id, name, creator_id, team_type, max_member)
SELECT user_id, CONCAT('个人团队-', username), user_id, 'personal', 5
FROM user
ON DUPLICATE KEY UPDATE org_id=VALUES(org_id)  -- 防止重复执行
""")

# 步骤2：迁移资产归属（asset表）
cursor.execute("""
UPDATE asset
SET org_id = owner_id, created_by = owner_id
WHERE org_id IS NULL  -- 仅迁移未处理的旧数据
""")

# 步骤3：初始化成员关系（member表）
cursor.execute("""
INSERT INTO member (user_id, org_id, role)
SELECT user_id, user_id, 'admin'
FROM user
ON DUPLICATE KEY UPDATE role='admin'  -- 确保创建者为管理员
""")

cnx.commit()
```

### 6.1.3 技术落地难点与解决方案（架构师视角）
#### 难点1：迁移过程中业务中断风险
- **现象**：迁移脚本执行时，`asset`表被长时间锁定，导致用户无法上传文件（报错`Lock wait timeout`）。
- **根因**：`UPDATE asset`操作未分批执行，单次更新100万+记录，触发MySQL表级锁。
- **解决方案**：
  - **分批迁移**：按`asset_id`范围拆分（如每1万条一批），添加`LIMIT 10000`并循环执行（示例）：
    ```sql
    UPDATE asset
    SET org_id = owner_id
    WHERE org_id IS NULL AND asset_id BETWEEN 1 AND 10000
    ```
  - **读写分离**：迁移期间将读请求路由至从库，写请求（如上传）暂时缓存至Kafka，迁移完成后回放。

#### 难点2：超级用户数据一致性问题
- **现象**：某用户`user_id=1001`拥有50万条资产，迁移后`org_id=1001`的团队资产量与原`owner_id=1001`的资产量不一致（相差23条）。
- **根因**：迁移脚本执行期间，用户新增了资产（`owner_id=1001`），但`UPDATE`语句未包含新记录（因`WHERE org_id IS NULL`条件已过滤旧数据）。
- **解决方案**：
  - **增量捕获**：启用MySQL Binlog监听（通过Debezium），实时捕获`asset`表的`INSERT`事件，为新记录自动补充`org_id=owner_id`。
  - **双写验证**：迁移后3天内，同时记录`asset.org_id`和`asset.owner_id`，通过`SELECT COUNT(*) FROM asset WHERE org_id != owner_id`验证一致性。

### 6.4 可扩展方向与专业思考
#### 6.4.1 可扩展内容
- **自动化迁移框架**：封装迁移脚本为CLI工具（如`fmz-migrate --type=personal`），支持参数化配置（分批大小、团队类型）。
- **多源数据支持**：扩展脚本以处理从其他系统导入的存量数据（如通过CSV文件迁移第三方平台资产）。
- **回滚机制**：迁移前备份`asset.owner_id`字段（新增`original_owner_id`列），支持`UPDATE asset SET org_id=NULL, original_owner_id=org_id`快速回滚。

#### 6.4.2 架构师关键思考题
1. 当存量用户超1000万时，如何优化迁移脚本性能（如减少数据库锁竞争、利用分布式计算框架）？
2. 迁移后发现某团队`org_id=2001`的资产量异常（比原用户资产量多30%），如何快速定位是迁移错误还是业务新增？
3. 支持跨国租户时（如用户分布在中国/美国），如何避免时区差异导致的迁移数据不一致（如`created_at`字段时区转换）？
4. 未来若支持团队合并（如A团队并入B团队），迁移脚本需如何扩展以支持资产/成员的批量转移？


## 七、扩展场景与通用设计
### 7.1 扩展场景：子租户支持
当客户需要「集团-子公司」多层级组织时，扩展`org`表添加`parent_org_id`字段，修改拦截器逻辑：
```go
// 查询当前org及其所有子org的资产
orgIDs := getSubOrgIDs(ctx.Value("org_id").(string)) // 通过递归查询获取子org列表
q.Statement.AddClause(clause.Where{Exprs: []clause.Expression{
    clause.In{Column: "org_id", Values: orgIDs},
}})
```

### 7.2 通用设计原则
- **租户标识优先**：所有业务对象（资产、日志、配置）必须包含`org_id`字段，作为第一隔离维度。
- **权限最小化**：团队内角色仅授予必要权限（如`viewer`无删除权限），通过`member_role_permission`表（`role, permission`）实现灵活扩展。
- **可观测性**：监控`org_id`分布（如`SELECT org_id, COUNT(*) FROM asset GROUP BY org_id`），识别大租户（Top 1%）并针对性优化（如单独分库）。

## 八、架构师关键思考题
1. 当单租户资产量超100万条时（如某大型企业），如何避免`org_id`索引失效？是否需要租户级分表（如`asset_${org_id}`）？
2. 第三方应用通过API访问资产时，如何保证其携带的`org_id`与调用方身份一致（防止伪造`org_id`）？
3. 租户删除团队时，如何安全清理关联数据（如资产、成员、操作日志）？需考虑哪些级联删除策略（物理删除vs逻辑删除）？
4. 多租户下数据库备份策略如何设计？是否需要按`org_id`分桶备份（如每天备份Top 100大租户，每周全量备份）？