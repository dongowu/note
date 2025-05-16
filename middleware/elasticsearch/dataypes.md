# Elasticsearch 数据类型总结

Elasticsearch 数据类型用于定义索引中字段的存储和查询方式，合理选择类型能优化搜索性能、存储效率及查询准确性。以下是核心数据类型的详细说明：

---

## 一、文本类型（Text/Keyword）
### 1.1 概念
- **text**：用于存储长文本（如商品描述、日志内容），默认会通过分词器（如IK）拆分为词项，支持全文搜索。
- **keyword**：用于存储短字符串（如标签、URL、用户ID），不进行分词，支持精确匹配、排序及聚合。

### 1.2 使用场景
- text：全文搜索（如搜索"红色外套"匹配"红色加绒外套"）、高亮显示（Highlight）。
- keyword：精确匹配（如查询标签="促销"）、分组聚合（如统计各地区订单量）。

### 1.3 映射配置示例
```json
PUT /product_index
{
  "mappings": {
    "properties": {
      "name": {
        "type": "text",
        "analyzer": "ik_max_word",  // 使用IK分词器
        "fields": {
          "keyword": {  // 同时存储keyword子字段，支持精确查询
            "type": "keyword",
            "ignore_above": 256  // 超过256字符的内容不索引
          }
        }
      },
      "category": {
        "type": "keyword"  // 分类标签，用于精确匹配
      }
    }
  }
}
```

---

## 二、数值类型（Number）
### 2.1 常用类型
- long（长整型）、integer（整型）、short（短整型）、byte（字节型）、double（双精度浮点）、float（单精度浮点）、half_float（半精度浮点）、scaled_float（缩放浮点）。

### 2.2 使用场景
- 统计计算（如订单金额求和、平均用户年龄）、范围查询（如价格在100-500元之间）。
- scaled_float：适用于需高精度的场景（如金额，设置`scaling_factor=100`将0.01元存储为1）。

### 2.3 映射配置示例
```json
PUT /sales_index
{
  "mappings": {
    "properties": {
      "price": {
        "type": "scaled_float",
        "scaling_factor": 100  // 存储为整数，避免浮点精度丢失
      },
      "quantity": {
        "type": "integer"  // 库存数量，整型足够
      }
    }
  }
}
```

---

## 三、日期类型（Date）
### 3.1 特性
- 自动解析多种日期格式（如"2024-06-01", "2024/06/01 12:00:00"），存储为UTC时间戳（长整型）。
- 支持范围查询（如查询6月1日后的订单）、时间序列聚合（如按月统计销售额）。

### 3.2 映射配置示例
```json
PUT /logs_index
{
  "mappings": {
    "properties": {
      "timestamp": {
        "type": "date",
        "format": "yyyy-MM-dd HH:mm:ss||yyyy/MM/dd"
      }
    }
  }
}
```

---

## 四、使用注意事项
1. **避免类型混用**：text用于全文搜索，keyword用于精确匹配，需根据业务需求选择（如商品名称用text+keyword子字段）。
2. **关闭动态映射**：通过`"dynamic": "strict"`显式定义所有字段类型，避免因自动推断导致类型冲突（如`"123"`被推断为text，后续数值`123`导致类型错误）<mcfile name="problems.md" path="d:\ownCode\leetcode\middleware\elasticsearch\problems.md"></mcfile>。
3. **字段别名（ES7.6+）**：通过`aliases`为字段定义别名，灵活适配多类型查询需求（如为text字段添加keyword别名）<mcfile name="problems.md" path="d:\ownCode\leetcode\middleware\elasticsearch\problems.md"></mcfile>。
4. **组件模板优化**：将公共字段类型（如IK分词器配置）抽离为组件模板，通过`composed_of`引用，避免重复代码<mcfile name="es.md" path="d:\ownCode\leetcode\middleware\elasticsearch\es.md"></mcfile>。

---

**总结**：合理选择数据类型是Elasticsearch性能优化的基础，需结合业务场景（全文搜索/精确匹配/统计分析）、字段长度及查询需求（是否排序/聚合）综合决策。