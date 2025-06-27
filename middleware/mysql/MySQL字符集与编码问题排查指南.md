# MySQL字符集与编码问题排查指南

## 1. 字符集问题识别与诊断

### 1.1 常见症状

#### 数据显示异常
```sql
-- 常见的乱码现象
-- 中文显示为问号
SELECT name FROM users WHERE id = 1;
-- 结果: ??????

-- 中文显示为其他字符
SELECT description FROM products WHERE id = 100;
-- 结果: ä¸­æ–‡

-- 插入中文失败
INSERT INTO articles (title, content) VALUES ('测试标题', '测试内容');
-- ERROR 1366 (HY000): Incorrect string value: '\xE6\xB5\x8B\xE8\xAF\x95...' for column 'title'
```

#### 字符集检查命令
```sql
-- 查看系统字符集设置
SHOW VARIABLES LIKE 'character_set%';
SHOW VARIABLES LIKE 'collation%';

-- 查看数据库字符集
SELECT 
    SCHEMA_NAME as '数据库',
    DEFAULT_CHARACTER_SET_NAME as '字符集',
    DEFAULT_COLLATION_NAME as '排序规则'
FROM information_schema.SCHEMATA;

-- 查看表字符集
SELECT 
    TABLE_SCHEMA as '数据库',
    TABLE_NAME as '表名',
    TABLE_COLLATION as '排序规则'
FROM information_schema.TABLES 
WHERE TABLE_SCHEMA NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys');

-- 查看列字符集
SELECT 
    TABLE_SCHEMA as '数据库',
    TABLE_NAME as '表名',
    COLUMN_NAME as '列名',
    CHARACTER_SET_NAME as '字符集',
    COLLATION_NAME as '排序规则',
    DATA_TYPE as '数据类型'
FROM information_schema.COLUMNS 
WHERE CHARACTER_SET_NAME IS NOT NULL
AND TABLE_SCHEMA = 'your_database';
```

### 1.2 字符集诊断脚本

```python
#!/usr/bin/env python3
# charset_diagnostic.py

import pymysql
import sys
import json
from collections import defaultdict

class CharsetDiagnostic:
    def __init__(self, host='localhost', user='root', password='password', database=None):
        self.connection = pymysql.connect(
            host=host, user=user, password=password, database=database,
            charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor
        )
    
    def check_system_charset(self):
        """检查系统字符集配置"""
        with self.connection.cursor() as cursor:
            cursor.execute("SHOW VARIABLES LIKE 'character_set%'")
            charset_vars = {row['Variable_name']: row['Value'] for row in cursor.fetchall()}
            
            cursor.execute("SHOW VARIABLES LIKE 'collation%'")
            collation_vars = {row['Variable_name']: row['Value'] for row in cursor.fetchall()}
            
            return {
                'charset_variables': charset_vars,
                'collation_variables': collation_vars
            }
    
    def check_database_charset(self):
        """检查数据库字符集"""
        with self.connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    SCHEMA_NAME,
                    DEFAULT_CHARACTER_SET_NAME,
                    DEFAULT_COLLATION_NAME
                FROM information_schema.SCHEMATA
                WHERE SCHEMA_NAME NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
            """)
            return cursor.fetchall()
    
    def check_table_charset(self, database_name=None):
        """检查表字符集"""
        with self.connection.cursor() as cursor:
            sql = """
                SELECT 
                    TABLE_SCHEMA,
                    TABLE_NAME,
                    TABLE_COLLATION,
                    ENGINE
                FROM information_schema.TABLES 
                WHERE TABLE_SCHEMA NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
            """
            
            if database_name:
                sql += " AND TABLE_SCHEMA = %s"
                cursor.execute(sql, (database_name,))
            else:
                cursor.execute(sql)
            
            return cursor.fetchall()
    
    def check_column_charset(self, database_name=None):
        """检查列字符集"""
        with self.connection.cursor() as cursor:
            sql = """
                SELECT 
                    TABLE_SCHEMA,
                    TABLE_NAME,
                    COLUMN_NAME,
                    CHARACTER_SET_NAME,
                    COLLATION_NAME,
                    DATA_TYPE,
                    IS_NULLABLE,
                    COLUMN_DEFAULT
                FROM information_schema.COLUMNS 
                WHERE CHARACTER_SET_NAME IS NOT NULL
                AND TABLE_SCHEMA NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
            """
            
            if database_name:
                sql += " AND TABLE_SCHEMA = %s"
                cursor.execute(sql, (database_name,))
            else:
                cursor.execute(sql)
            
            return cursor.fetchall()
    
    def detect_charset_inconsistency(self, database_name=None):
        """检测字符集不一致问题"""
        issues = []
        
        # 检查系统级字符集
        system_charset = self.check_system_charset()
        charset_vars = system_charset['charset_variables']
        
        # 检查关键字符集变量是否一致
        key_charsets = [
            'character_set_client',
            'character_set_connection', 
            'character_set_results',
            'character_set_server'
        ]
        
        charset_values = [charset_vars.get(var, 'unknown') for var in key_charsets]
        if len(set(charset_values)) > 1:
            issues.append({
                'type': 'system_charset_inconsistency',
                'description': '系统字符集变量不一致',
                'details': {var: charset_vars.get(var) for var in key_charsets}
            })
        
        # 检查数据库字符集
        databases = self.check_database_charset()
        db_charsets = defaultdict(list)
        for db in databases:
            charset = db['DEFAULT_CHARACTER_SET_NAME']
            db_charsets[charset].append(db['SCHEMA_NAME'])
        
        if len(db_charsets) > 1:
            issues.append({
                'type': 'database_charset_inconsistency',
                'description': '数据库字符集不一致',
                'details': dict(db_charsets)
            })
        
        # 检查表字符集
        tables = self.check_table_charset(database_name)
        table_charsets = defaultdict(list)
        for table in tables:
            collation = table['TABLE_COLLATION']
            charset = collation.split('_')[0] if collation else 'unknown'
            table_charsets[charset].append(f"{table['TABLE_SCHEMA']}.{table['TABLE_NAME']}")
        
        if len(table_charsets) > 1:
            issues.append({
                'type': 'table_charset_inconsistency',
                'description': '表字符集不一致',
                'details': dict(table_charsets)
            })
        
        # 检查列字符集
        columns = self.check_column_charset(database_name)
        column_charsets = defaultdict(list)
        for column in columns:
            charset = column['CHARACTER_SET_NAME']
            column_charsets[charset].append(
                f"{column['TABLE_SCHEMA']}.{column['TABLE_NAME']}.{column['COLUMN_NAME']}"
            )
        
        if len(column_charsets) > 1:
            issues.append({
                'type': 'column_charset_inconsistency',
                'description': '列字符集不一致',
                'details': dict(column_charsets)
            })
        
        return issues
    
    def test_charset_support(self):
        """测试字符集支持"""
        test_strings = {
            'chinese': '中文测试',
            'japanese': '日本語テスト',
            'korean': '한국어 테스트',
            'emoji': '😀🎉🚀',
            'special': '©®™€£¥'
        }
        
        results = {}
        
        with self.connection.cursor() as cursor:
            # 创建测试表
            cursor.execute("""
                CREATE TEMPORARY TABLE charset_test (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    test_type VARCHAR(20),
                    original_text TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
                    stored_text TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """)
            
            for test_type, test_string in test_strings.items():
                try:
                    # 插入测试数据
                    cursor.execute(
                        "INSERT INTO charset_test (test_type, original_text) VALUES (%s, %s)",
                        (test_type, test_string)
                    )
                    
                    # 读取数据
                    cursor.execute(
                        "SELECT original_text FROM charset_test WHERE test_type = %s",
                        (test_type,)
                    )
                    result = cursor.fetchone()
                    stored_text = result['original_text'] if result else None
                    
                    # 更新存储的文本
                    cursor.execute(
                        "UPDATE charset_test SET stored_text = %s WHERE test_type = %s",
                        (stored_text, test_type)
                    )
                    
                    results[test_type] = {
                        'original': test_string,
                        'stored': stored_text,
                        'success': test_string == stored_text,
                        'length_original': len(test_string),
                        'length_stored': len(stored_text) if stored_text else 0
                    }
                    
                except Exception as e:
                    results[test_type] = {
                        'original': test_string,
                        'stored': None,
                        'success': False,
                        'error': str(e)
                    }
        
        return results
    
    def generate_report(self, database_name=None):
        """生成完整的字符集诊断报告"""
        report = {
            'timestamp': pymysql.Date.today().isoformat(),
            'database_name': database_name,
            'system_charset': self.check_system_charset(),
            'database_charset': self.check_database_charset(),
            'table_charset': self.check_table_charset(database_name),
            'column_charset': self.check_column_charset(database_name),
            'inconsistency_issues': self.detect_charset_inconsistency(database_name),
            'charset_test_results': self.test_charset_support()
        }
        
        return report

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python charset_diagnostic.py <database_name>")
        sys.exit(1)
    
    database_name = sys.argv[1]
    
    try:
        diagnostic = CharsetDiagnostic(database=database_name)
        report = diagnostic.generate_report(database_name)
        
        print("=== MySQL字符集诊断报告 ===")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        
        # 检查是否有问题
        if report['inconsistency_issues']:
            print("\n⚠️  发现字符集问题:")
            for issue in report['inconsistency_issues']:
                print(f"  - {issue['description']}")
        
        # 检查字符集测试结果
        test_results = report['charset_test_results']
        failed_tests = [k for k, v in test_results.items() if not v['success']]
        if failed_tests:
            print(f"\n❌ 字符集测试失败: {', '.join(failed_tests)}")
        else:
            print("\n✅ 所有字符集测试通过")
            
    except Exception as e:
        print(f"诊断失败: {e}")
        sys.exit(1)
```

## 2. 字符集问题解决方案

### 2.1 系统级字符集配置

#### MySQL配置文件优化
```ini
# /etc/mysql/my.cnf 或 /etc/my.cnf
[client]
default-character-set = utf8mb4

[mysql]
default-character-set = utf8mb4

[mysqld]
# 服务器字符集
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci

# 初始化连接字符集
init_connect = 'SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci'

# 跳过字符集检查（谨慎使用）
# skip-character-set-client-handshake

[mysqldump]
default-character-set = utf8mb4
```

#### 动态设置字符集
```sql
-- 设置会话级字符集
SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 或者分别设置
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

-- 设置全局字符集（重启后失效）
SET GLOBAL character_set_server = utf8mb4;
SET GLOBAL collation_server = utf8mb4_unicode_ci;
```

### 2.2 数据库和表级字符集修复

#### 数据库字符集修改
```sql
-- 修改数据库字符集
ALTER DATABASE your_database 
CHARACTER SET utf8mb4 
COLLATE utf8mb4_unicode_ci;

-- 创建新数据库时指定字符集
CREATE DATABASE new_database 
CHARACTER SET utf8mb4 
COLLATE utf8mb4_unicode_ci;
```

#### 表字符集批量修改脚本
```sql
-- 生成修改表字符集的SQL
SELECT CONCAT(
    'ALTER TABLE ', TABLE_SCHEMA, '.', TABLE_NAME, 
    ' CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;'
) AS alter_sql
FROM information_schema.TABLES 
WHERE TABLE_SCHEMA = 'your_database'
AND TABLE_TYPE = 'BASE TABLE';

-- 生成修改列字符集的SQL
SELECT CONCAT(
    'ALTER TABLE ', TABLE_SCHEMA, '.', TABLE_NAME,
    ' MODIFY COLUMN ', COLUMN_NAME, ' ', DATA_TYPE,
    CASE 
        WHEN CHARACTER_MAXIMUM_LENGTH IS NOT NULL 
        THEN CONCAT('(', CHARACTER_MAXIMUM_LENGTH, ')')
        ELSE ''
    END,
    ' CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci',
    CASE WHEN IS_NULLABLE = 'NO' THEN ' NOT NULL' ELSE '' END,
    CASE 
        WHEN COLUMN_DEFAULT IS NOT NULL 
        THEN CONCAT(' DEFAULT \'', COLUMN_DEFAULT, '\'')
        ELSE ''
    END,
    ';'
) AS alter_sql
FROM information_schema.COLUMNS 
WHERE TABLE_SCHEMA = 'your_database'
AND CHARACTER_SET_NAME IS NOT NULL
AND CHARACTER_SET_NAME != 'utf8mb4';
```

#### 安全的字符集转换脚本
```python
#!/usr/bin/env python3
# charset_converter.py

import pymysql
import sys
import time
import logging
from datetime import datetime

class CharsetConverter:
    def __init__(self, host='localhost', user='root', password='password'):
        self.connection = pymysql.connect(
            host=host, user=user, password=password,
            charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor
        )
        self.logger = logging.getLogger(__name__)
        
    def backup_table(self, database, table):
        """备份表"""
        backup_name = f"{table}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        with self.connection.cursor() as cursor:
            cursor.execute(f"USE {database}")
            cursor.execute(f"CREATE TABLE {backup_name} AS SELECT * FROM {table}")
            
        return backup_name
    
    def convert_table_charset(self, database, table, target_charset='utf8mb4', target_collation='utf8mb4_unicode_ci'):
        """转换表字符集"""
        try:
            # 1. 备份表
            backup_name = self.backup_table(database, table)
            self.logger.info(f"已备份表 {table} 为 {backup_name}")
            
            # 2. 获取表结构
            with self.connection.cursor() as cursor:
                cursor.execute(f"USE {database}")
                cursor.execute(f"SHOW CREATE TABLE {table}")
                create_sql = cursor.fetchone()['Create Table']
            
            # 3. 转换字符集
            with self.connection.cursor() as cursor:
                # 方法1：CONVERT TO（推荐，会转换数据）
                convert_sql = f"""
                    ALTER TABLE {table} 
                    CONVERT TO CHARACTER SET {target_charset} 
                    COLLATE {target_collation}
                """
                cursor.execute(convert_sql)
                
                # 方法2：仅修改表定义（不转换现有数据）
                # modify_sql = f"""
                #     ALTER TABLE {table} 
                #     DEFAULT CHARACTER SET {target_charset} 
                #     COLLATE {target_collation}
                # """
                # cursor.execute(modify_sql)
            
            self.logger.info(f"表 {table} 字符集转换完成")
            return True
            
        except Exception as e:
            self.logger.error(f"转换表 {table} 字符集失败: {e}")
            return False
    
    def convert_database_charset(self, database, target_charset='utf8mb4', target_collation='utf8mb4_unicode_ci'):
        """转换整个数据库字符集"""
        try:
            # 1. 获取所有表
            with self.connection.cursor() as cursor:
                cursor.execute(f"USE {database}")
                cursor.execute("SHOW TABLES")
                tables = [row[f'Tables_in_{database}'] for row in cursor.fetchall()]
            
            # 2. 转换数据库字符集
            with self.connection.cursor() as cursor:
                cursor.execute(f"""
                    ALTER DATABASE {database} 
                    CHARACTER SET {target_charset} 
                    COLLATE {target_collation}
                """)
            
            # 3. 转换所有表
            success_count = 0
            for table in tables:
                if self.convert_table_charset(database, table, target_charset, target_collation):
                    success_count += 1
                time.sleep(0.1)  # 短暂休眠
            
            self.logger.info(f"数据库 {database} 字符集转换完成，成功转换 {success_count}/{len(tables)} 个表")
            return success_count == len(tables)
            
        except Exception as e:
            self.logger.error(f"转换数据库 {database} 字符集失败: {e}")
            return False
    
    def fix_corrupted_data(self, database, table, column, source_charset='latin1', target_charset='utf8mb4'):
        """修复损坏的字符数据"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(f"USE {database}")
                
                # 备份原始数据
                backup_name = f"{table}_{column}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                cursor.execute(f"""
                    CREATE TABLE {backup_name} AS 
                    SELECT id, {column} as original_{column} FROM {table}
                """)
                
                # 修复数据：先转换为二进制，再转换为目标字符集
                cursor.execute(f"""
                    UPDATE {table} 
                    SET {column} = CONVERT(
                        CONVERT(
                            CONVERT({column} USING {source_charset}) 
                            USING binary
                        ) 
                        USING {target_charset}
                    )
                    WHERE {column} IS NOT NULL
                """)
                
                affected_rows = cursor.rowcount
                self.logger.info(f"修复了 {affected_rows} 行数据")
                
                return affected_rows
                
        except Exception as e:
            self.logger.error(f"修复数据失败: {e}")
            return 0

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    if len(sys.argv) < 3:
        print("使用方法: python charset_converter.py <database> <action> [table]")
        print("action: convert_db | convert_table | fix_data")
        sys.exit(1)
    
    database = sys.argv[1]
    action = sys.argv[2]
    
    converter = CharsetConverter()
    
    if action == 'convert_db':
        success = converter.convert_database_charset(database)
        print(f"数据库转换{'成功' if success else '失败'}")
    
    elif action == 'convert_table' and len(sys.argv) >= 4:
        table = sys.argv[3]
        success = converter.convert_table_charset(database, table)
        print(f"表转换{'成功' if success else '失败'}")
    
    elif action == 'fix_data' and len(sys.argv) >= 5:
        table = sys.argv[3]
        column = sys.argv[4]
        affected = converter.fix_corrupted_data(database, table, column)
        print(f"修复了 {affected} 行数据")
    
    else:
        print("参数错误")
        sys.exit(1)
```

### 2.3 应用层字符集处理

#### Python连接配置
```python
# 正确的连接配置
import pymysql

# 方法1：连接时指定字符集
connection = pymysql.connect(
    host='localhost',
    user='username',
    password='password',
    database='database',
    charset='utf8mb4',  # 重要：使用utf8mb4
    cursorclass=pymysql.cursors.DictCursor
)

# 方法2：连接后设置字符集
connection = pymysql.connect(
    host='localhost',
    user='username',
    password='password',
    database='database'
)

with connection.cursor() as cursor:
    cursor.execute("SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci")

# 字符集测试函数
def test_charset_support(connection):
    test_data = {
        'chinese': '中文测试 🇨🇳',
        'japanese': '日本語テスト 🇯🇵',
        'korean': '한국어 테스트 🇰🇷',
        'emoji': '😀🎉🚀💯',
        'special': '©®™€£¥§'
    }
    
    with connection.cursor() as cursor:
        # 创建测试表
        cursor.execute("""
            CREATE TEMPORARY TABLE charset_test (
                id INT AUTO_INCREMENT PRIMARY KEY,
                test_type VARCHAR(20),
                content TEXT
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        
        # 测试插入和读取
        for test_type, content in test_data.items():
            try:
                cursor.execute(
                    "INSERT INTO charset_test (test_type, content) VALUES (%s, %s)",
                    (test_type, content)
                )
                
                cursor.execute(
                    "SELECT content FROM charset_test WHERE test_type = %s",
                    (test_type,)
                )
                result = cursor.fetchone()
                
                if result and result['content'] == content:
                    print(f"✅ {test_type}: 通过")
                else:
                    print(f"❌ {test_type}: 失败 - 期望: {content}, 实际: {result['content'] if result else None}")
                    
            except Exception as e:
                print(f"❌ {test_type}: 异常 - {e}")

# 使用示例
if __name__ == "__main__":
    try:
        conn = pymysql.connect(
            host='localhost',
            user='root',
            password='password',
            database='test',
            charset='utf8mb4'
        )
        
        print("=== 字符集支持测试 ===")
        test_charset_support(conn)
        
    except Exception as e:
        print(f"连接失败: {e}")
    finally:
        if 'conn' in locals():
            conn.close()
```

#### Java连接配置
```java
// JDBC连接字符集配置
public class MySQLCharsetConfig {
    
    // 方法1：URL参数配置
    public static Connection getConnection1() throws SQLException {
        String url = "jdbc:mysql://localhost:3306/database?" +
                    "useUnicode=true&" +
                    "characterEncoding=utf8mb4&" +
                    "useSSL=false&" +
                    "serverTimezone=Asia/Shanghai";
        
        return DriverManager.getConnection(url, "username", "password");
    }
    
    // 方法2：连接后设置
    public static Connection getConnection2() throws SQLException {
        String url = "jdbc:mysql://localhost:3306/database";
        Connection conn = DriverManager.getConnection(url, "username", "password");
        
        try (Statement stmt = conn.createStatement()) {
            stmt.execute("SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci");
        }
        
        return conn;
    }
    
    // 字符集测试
    public static void testCharsetSupport(Connection conn) {
        Map<String, String> testData = new HashMap<>();
        testData.put("chinese", "中文测试 🇨🇳");
        testData.put("japanese", "日本語テスト 🇯🇵");
        testData.put("korean", "한국어 테스트 🇰🇷");
        testData.put("emoji", "😀🎉🚀💯");
        
        try {
            // 创建测试表
            try (Statement stmt = conn.createStatement()) {
                stmt.execute("""
                    CREATE TEMPORARY TABLE charset_test (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        test_type VARCHAR(20),
                        content TEXT
                    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                """);
            }
            
            // 测试插入和读取
            String insertSQL = "INSERT INTO charset_test (test_type, content) VALUES (?, ?)";
            String selectSQL = "SELECT content FROM charset_test WHERE test_type = ?";
            
            for (Map.Entry<String, String> entry : testData.entrySet()) {
                String testType = entry.getKey();
                String content = entry.getValue();
                
                try {
                    // 插入数据
                    try (PreparedStatement pstmt = conn.prepareStatement(insertSQL)) {
                        pstmt.setString(1, testType);
                        pstmt.setString(2, content);
                        pstmt.executeUpdate();
                    }
                    
                    // 读取数据
                    try (PreparedStatement pstmt = conn.prepareStatement(selectSQL)) {
                        pstmt.setString(1, testType);
                        try (ResultSet rs = pstmt.executeQuery()) {
                            if (rs.next()) {
                                String result = rs.getString("content");
                                if (content.equals(result)) {
                                    System.out.println("✅ " + testType + ": 通过");
                                } else {
                                    System.out.println("❌ " + testType + ": 失败 - 期望: " + content + ", 实际: " + result);
                                }
                            }
                        }
                    }
                    
                } catch (SQLException e) {
                    System.out.println("❌ " + testType + ": 异常 - " + e.getMessage());
                }
            }
            
        } catch (SQLException e) {
            System.err.println("测试失败: " + e.getMessage());
        }
    }
    
    public static void main(String[] args) {
        try (Connection conn = getConnection1()) {
            System.out.println("=== 字符集支持测试 ===");
            testCharsetSupport(conn);
        } catch (SQLException e) {
            System.err.println("连接失败: " + e.getMessage());
        }
    }
}
```

## 3. 编码问题处理

### 3.1 常见编码问题

#### 双重编码问题
```sql
-- 问题：数据被双重编码
-- 原始数据：中文
-- 第一次编码：UTF-8 -> 中文变成 \xE4\xB8\xAD\xE6\x96\x87
-- 第二次编码：再次UTF-8编码
-- 结果：显示为乱码

-- 检测双重编码
SELECT 
    id,
    name,
    HEX(name) as hex_value,
    CHAR_LENGTH(name) as char_length,
    LENGTH(name) as byte_length
FROM users 
WHERE name REGEXP '[\x80-\xFF]'  -- 包含非ASCII字符
LIMIT 10;

-- 修复双重编码（谨慎使用）
UPDATE users 
SET name = CONVERT(CONVERT(CONVERT(name USING latin1) USING binary) USING utf8mb4)
WHERE id = 1;
```

#### 编码检测脚本
```python
#!/usr/bin/env python3
# encoding_detector.py

import pymysql
import chardet
import sys

class EncodingDetector:
    def __init__(self, host='localhost', user='root', password='password', database=None):
        self.connection = pymysql.connect(
            host=host, user=user, password=password, database=database,
            charset='latin1',  # 使用latin1读取原始字节
            cursorclass=pymysql.cursors.DictCursor
        )
    
    def detect_column_encoding(self, table, column, sample_size=100):
        """检测列的编码"""
        with self.connection.cursor() as cursor:
            cursor.execute(f"""
                SELECT {column} 
                FROM {table} 
                WHERE {column} IS NOT NULL 
                AND {column} != '' 
                LIMIT {sample_size}
            """)
            
            results = cursor.fetchall()
            
            encoding_stats = {}
            
            for row in results:
                text = row[column]
                if isinstance(text, str):
                    text_bytes = text.encode('latin1')  # 获取原始字节
                    
                    # 检测编码
                    detected = chardet.detect(text_bytes)
                    encoding = detected['encoding']
                    confidence = detected['confidence']
                    
                    if encoding not in encoding_stats:
                        encoding_stats[encoding] = {
                            'count': 0,
                            'confidence_sum': 0,
                            'samples': []
                        }
                    
                    encoding_stats[encoding]['count'] += 1
                    encoding_stats[encoding]['confidence_sum'] += confidence
                    
                    if len(encoding_stats[encoding]['samples']) < 3:
                        encoding_stats[encoding]['samples'].append({
                            'text': text[:50],  # 前50个字符
                            'confidence': confidence
                        })
            
            # 计算平均置信度
            for encoding, stats in encoding_stats.items():
                stats['avg_confidence'] = stats['confidence_sum'] / stats['count']
            
            return encoding_stats
    
    def fix_encoding_issues(self, table, column, source_encoding, target_encoding='utf8mb4'):
        """修复编码问题"""
        try:
            with self.connection.cursor() as cursor:
                # 备份原始数据
                backup_table = f"{table}_encoding_backup_{int(time.time())}"
                cursor.execute(f"""
                    CREATE TABLE {backup_table} AS 
                    SELECT * FROM {table}
                """)
                
                # 修复编码
                if source_encoding.lower() in ['utf-8', 'utf8']:
                    # UTF-8双重编码修复
                    cursor.execute(f"""
                        UPDATE {table} 
                        SET {column} = CONVERT(
                            CONVERT(
                                CONVERT({column} USING latin1) 
                                USING binary
                            ) 
                            USING {target_encoding}
                        )
                        WHERE {column} IS NOT NULL
                    """)
                elif source_encoding.lower() in ['gbk', 'gb2312']:
                    # GBK编码修复
                    cursor.execute(f"""
                        UPDATE {table} 
                        SET {column} = CONVERT(
                            CONVERT({column} USING gbk) 
                            USING {target_encoding}
                        )
                        WHERE {column} IS NOT NULL
                    """)
                else:
                    print(f"不支持的源编码: {source_encoding}")
                    return False
                
                affected_rows = cursor.rowcount
                print(f"修复了 {affected_rows} 行数据")
                return True
                
        except Exception as e:
            print(f"修复编码失败: {e}")
            return False

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("使用方法: python encoding_detector.py <database> <table> <column>")
        sys.exit(1)
    
    database = sys.argv[1]
    table = sys.argv[2]
    column = sys.argv[3]
    
    detector = EncodingDetector(database=database)
    
    print(f"=== 检测 {database}.{table}.{column} 的编码 ===")
    encoding_stats = detector.detect_column_encoding(table, column)
    
    for encoding, stats in sorted(encoding_stats.items(), key=lambda x: x[1]['count'], reverse=True):
        print(f"\n编码: {encoding}")
        print(f"  数量: {stats['count']}")
        print(f"  平均置信度: {stats['avg_confidence']:.2f}")
        print(f"  样本:")
        for sample in stats['samples']:
            print(f"    - {sample['text']} (置信度: {sample['confidence']:.2f})")
```

### 3.2 数据迁移中的编码处理

#### 安全的数据导出导入
```bash
#!/bin/bash
# charset_migration.sh

SOURCE_DB="old_database"
TARGET_DB="new_database"
MYSQL_USER="root"
MYSQL_PASS="password"

echo "=== MySQL字符集迁移脚本 ==="

# 1. 导出数据（指定字符集）
echo "导出数据..."
mysqldump \
    --user=$MYSQL_USER \
    --password=$MYSQL_PASS \
    --default-character-set=utf8mb4 \
    --single-transaction \
    --routines \
    --triggers \
    --events \
    --hex-blob \
    $SOURCE_DB > ${SOURCE_DB}_utf8mb4.sql

# 2. 创建目标数据库
echo "创建目标数据库..."
mysql --user=$MYSQL_USER --password=$MYSQL_PASS -e "
CREATE DATABASE IF NOT EXISTS $TARGET_DB 
CHARACTER SET utf8mb4 
COLLATE utf8mb4_unicode_ci;"

# 3. 修改导出文件中的字符集声明
echo "修改字符集声明..."
sed -i 's/CHARSET=utf8/CHARSET=utf8mb4/g' ${SOURCE_DB}_utf8mb4.sql
sed -i 's/COLLATE=utf8_/COLLATE=utf8mb4_/g' ${SOURCE_DB}_utf8mb4.sql

# 4. 导入数据
echo "导入数据..."
mysql \
    --user=$MYSQL_USER \
    --password=$MYSQL_PASS \
    --default-character-set=utf8mb4 \
    $TARGET_DB < ${SOURCE_DB}_utf8mb4.sql

# 5. 验证字符集
echo "验证字符集..."
mysql --user=$MYSQL_USER --password=$MYSQL_PASS -e "
USE $TARGET_DB;
SHOW VARIABLES LIKE 'character_set%';
SELECT 
    TABLE_NAME,
    TABLE_COLLATION
FROM information_schema.TABLES 
WHERE TABLE_SCHEMA = '$TARGET_DB';"

echo "迁移完成！"
```

#### Python数据迁移脚本
```python
#!/usr/bin/env python3
# charset_migration.py

import pymysql
import sys
import time
from tqdm import tqdm

class CharsetMigration:
    def __init__(self, source_config, target_config):
        self.source_conn = pymysql.connect(**source_config)
        self.target_conn = pymysql.connect(**target_config)
    
    def migrate_table_data(self, table_name, batch_size=1000):
        """迁移表数据"""
        try:
            # 获取源表结构
            with self.source_conn.cursor() as cursor:
                cursor.execute(f"DESCRIBE {table_name}")
                columns = [row[0] for row in cursor.fetchall()]
                
                cursor.execute(f"SELECT COUNT(*) as count FROM {table_name}")
                total_rows = cursor.fetchone()[0]
            
            print(f"开始迁移表 {table_name}，总行数: {total_rows}")
            
            # 分批迁移数据
            offset = 0
            migrated_rows = 0
            
            with tqdm(total=total_rows, desc=f"迁移 {table_name}") as pbar:
                while offset < total_rows:
                    # 读取源数据
                    with self.source_conn.cursor(pymysql.cursors.DictCursor) as source_cursor:
                        source_cursor.execute(f"""
                            SELECT * FROM {table_name} 
                            LIMIT {batch_size} OFFSET {offset}
                        """)
                        rows = source_cursor.fetchall()
                    
                    if not rows:
                        break
                    
                    # 插入目标数据库
                    with self.target_conn.cursor() as target_cursor:
                        for row in rows:
                            # 构建插入SQL
                            placeholders = ', '.join(['%s'] * len(columns))
                            insert_sql = f"""
                                INSERT INTO {table_name} ({', '.join(columns)}) 
                                VALUES ({placeholders})
                            """
                            
                            values = [row[col] for col in columns]
                            target_cursor.execute(insert_sql, values)
                        
                        self.target_conn.commit()
                    
                    migrated_rows += len(rows)
                    offset += batch_size
                    pbar.update(len(rows))
                    
                    # 短暂休眠
                    time.sleep(0.01)
            
            print(f"表 {table_name} 迁移完成，迁移行数: {migrated_rows}")
            return True
            
        except Exception as e:
            print(f"迁移表 {table_name} 失败: {e}")
            return False
    
    def verify_migration(self, table_name, sample_size=100):
        """验证迁移结果"""
        try:
            # 比较行数
            with self.source_conn.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) as count FROM {table_name}")
                source_count = cursor.fetchone()[0]
            
            with self.target_conn.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) as count FROM {table_name}")
                target_count = cursor.fetchone()[0]
            
            print(f"行数比较 - 源: {source_count}, 目标: {target_count}")
            
            if source_count != target_count:
                print("❌ 行数不匹配")
                return False
            
            # 抽样比较数据
            with self.source_conn.cursor(pymysql.cursors.DictCursor) as source_cursor:
                source_cursor.execute(f"""
                    SELECT * FROM {table_name} 
                    ORDER BY RAND() 
                    LIMIT {sample_size}
                """)
                source_samples = source_cursor.fetchall()
            
            mismatch_count = 0
            for sample in source_samples:
                # 构建查询条件（假设有id字段）
                if 'id' in sample:
                    with self.target_conn.cursor(pymysql.cursors.DictCursor) as target_cursor:
                        target_cursor.execute(f"""
                            SELECT * FROM {table_name} WHERE id = %s
                        """, (sample['id'],))
                        target_row = target_cursor.fetchone()
                        
                        if target_row != sample:
                            mismatch_count += 1
            
            if mismatch_count == 0:
                print("✅ 数据验证通过")
                return True
            else:
                print(f"❌ 发现 {mismatch_count} 行数据不匹配")
                return False
                
        except Exception as e:
            print(f"验证失败: {e}")
            return False

if __name__ == "__main__":
    # 配置连接
    source_config = {
        'host': 'localhost',
        'user': 'root',
        'password': 'password',
        'database': 'old_database',
        'charset': 'latin1'  # 读取原始字节
    }
    
    target_config = {
        'host': 'localhost',
        'user': 'root',
        'password': 'password',
        'database': 'new_database',
        'charset': 'utf8mb4'  # 目标字符集
    }
    
    migration = CharsetMigration(source_config, target_config)
    
    # 获取要迁移的表列表
    tables = ['users', 'articles', 'comments']  # 根据实际情况修改
    
    for table in tables:
        success = migration.migrate_table_data(table)
        if success:
            migration.verify_migration(table)
        print("-" * 50)
```

## 4. 监控与预防

### 4.1 字符集监控脚本

```python
#!/usr/bin/env python3
# charset_monitor.py

import pymysql
import time
import json
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

class CharsetMonitor:
    def __init__(self, db_configs, alert_config=None):
        self.db_configs = db_configs
        self.alert_config = alert_config
    
    def check_charset_consistency(self, db_config):
        """检查字符集一致性"""
        try:
            connection = pymysql.connect(**db_config)
            issues = []
            
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                # 检查系统字符集变量
                cursor.execute("SHOW VARIABLES LIKE 'character_set%'")
                charset_vars = {row['Variable_name']: row['Value'] for row in cursor.fetchall()}
                
                # 检查关键变量是否一致
                key_vars = ['character_set_client', 'character_set_connection', 'character_set_results']
                charset_values = [charset_vars.get(var) for var in key_vars]
                
                if len(set(charset_values)) > 1:
                    issues.append({
                        'type': 'system_charset_mismatch',
                        'details': {var: charset_vars.get(var) for var in key_vars}
                    })
                
                # 检查数据库字符集
                cursor.execute("""
                    SELECT SCHEMA_NAME, DEFAULT_CHARACTER_SET_NAME 
                    FROM information_schema.SCHEMATA 
                    WHERE SCHEMA_NAME NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
                """)
                
                db_charsets = cursor.fetchall()
                non_utf8mb4_dbs = [db for db in db_charsets if db['DEFAULT_CHARACTER_SET_NAME'] != 'utf8mb4']
                
                if non_utf8mb4_dbs:
                    issues.append({
                        'type': 'non_utf8mb4_databases',
                        'details': non_utf8mb4_dbs
                    })
                
                # 检查表字符集
                cursor.execute("""
                    SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_COLLATION 
                    FROM information_schema.TABLES 
                    WHERE TABLE_SCHEMA NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
                    AND TABLE_COLLATION NOT LIKE 'utf8mb4%'
                """)
                
                non_utf8mb4_tables = cursor.fetchall()
                if non_utf8mb4_tables:
                    issues.append({
                        'type': 'non_utf8mb4_tables',
                        'details': non_utf8mb4_tables[:10]  # 只显示前10个
                    })
            
            connection.close()
            return issues
            
        except Exception as e:
            return [{'type': 'connection_error', 'details': str(e)}]
    
    def send_alert(self, issues, db_name):
        """发送告警"""
        if not self.alert_config or not issues:
            return
        
        subject = f"MySQL字符集告警 - {db_name}"
        body = f"发现字符集问题:\n\n"
        
        for issue in issues:
            body += f"类型: {issue['type']}\n"
            body += f"详情: {json.dumps(issue['details'], indent=2, ensure_ascii=False)}\n\n"
        
        try:
            msg = MIMEText(body, 'plain', 'utf-8')
            msg['Subject'] = subject
            msg['From'] = self.alert_config['from_email']
            msg['To'] = self.alert_config['to_email']
            
            server = smtplib.SMTP(self.alert_config['smtp_server'], self.alert_config['smtp_port'])
            server.starttls()
            server.login(self.alert_config['username'], self.alert_config['password'])
            server.send_message(msg)
            server.quit()
            
            print(f"告警邮件已发送: {subject}")
            
        except Exception as e:
            print(f"发送告警失败: {e}")
    
    def run_monitoring(self, interval_minutes=60):
        """运行监控"""
        print(f"开始字符集监控，检查间隔: {interval_minutes} 分钟")
        
        while True:
            try:
                for db_name, db_config in self.db_configs.items():
                    print(f"\n=== 检查数据库: {db_name} ===")
                    issues = self.check_charset_consistency(db_config)
                    
                    if issues:
                        print(f"发现 {len(issues)} 个问题:")
                        for issue in issues:
                            print(f"  - {issue['type']}")
                        
                        self.send_alert(issues, db_name)
                    else:
                        print("字符集检查通过")
                
                print(f"\n下次检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                time.sleep(interval_minutes * 60)
                
            except KeyboardInterrupt:
                print("\n监控已停止")
                break
            except Exception as e:
                print(f"监控异常: {e}")
                time.sleep(60)

if __name__ == "__main__":
    # 数据库配置
    db_configs = {
        'production': {
            'host': 'prod-mysql.example.com',
            'user': 'monitor',
            'password': 'password',
            'charset': 'utf8mb4'
        },
        'staging': {
            'host': 'staging-mysql.example.com',
            'user': 'monitor',
            'password': 'password',
            'charset': 'utf8mb4'
        }
    }
    
    # 告警配置
    alert_config = {
        'smtp_server': 'smtp.gmail.com',
        'smtp_port': 587,
        'username': 'alert@example.com',
        'password': 'app_password',
        'from_email': 'alert@example.com',
        'to_email': 'admin@example.com'
    }
    
    monitor = CharsetMonitor(db_configs, alert_config)
    monitor.run_monitoring(interval_minutes=30)
```

### 4.2 最佳实践总结

#### 开发阶段
1. **统一使用UTF-8MB4**：所有新项目都使用utf8mb4字符集
2. **连接配置**：确保应用程序连接时正确设置字符集
3. **代码审查**：检查字符集相关的配置和代码
4. **测试覆盖**：包含多语言和特殊字符的测试用例

#### 部署阶段
1. **配置文件**：在my.cnf中设置正确的默认字符集
2. **初始化脚本**：数据库初始化时指定字符集
3. **迁移脚本**：数据迁移时保持字符集一致性
4. **文档记录**：记录字符集配置和迁移过程

#### 运维阶段
1. **定期检查**：监控字符集配置的一致性
2. **备份验证**：确保备份恢复后字符集正确
3. **性能监控**：关注字符集转换对性能的影响
4. **应急预案**：制定字符集问题的处理流程

通过系统性的字符集管理和监控，可以有效避免和解决MySQL中的字符集与编码问题，确保数据的正确存储和显示。