# 阿里云DashScope配置指南

## 📋 概述

本指南帮助你使用阿里云DashScope（通义千问）配置BettaFish项目的所有LLM服务。

---

## 🔑 获取API Key

### 1. 注册阿里云账号
访问: https://www.aliyun.com/product/bailian

### 2. 开通百炼服务
1. 登录阿里云控制台
2. 搜索"百炼"或"DashScope"
3. 开通服务（有免费额度）

### 3. 创建API Key
1. 进入百炼控制台
2. 点击"API-KEY管理"
3. 创建新的API Key
4. **复制并保存**（只显示一次）

---

## ⚙️ 配置步骤

### 方式1: 使用提供的模板（推荐）

```bash
# 1. 复制模板文件
cp .env.template.aliyun .env

# 2. 编辑.env文件，替换以下内容：
# - your_dashscope_api_key_here → 你的阿里云API Key
# - your_tavily_api_key_here → 你的Tavily API Key（如果有）
# - your_anspire_api_key_here → 你的Anspire API Key（如果有）
# - your_password_here → 你的数据库密码
```

### 方式2: 手动配置

创建 `.env` 文件，添加以下内容：

```bash
# ====================== 数据库配置 ======================
DB_HOST=localhost
DB_PORT=5432
DB_USER=bettafish
DB_PASSWORD=你的数据库密码
DB_NAME=bettafish
DB_CHARSET=utf8mb4
DB_DIALECT=postgresql

# ======================= LLM 相关 =======================
# 所有Agent使用相同的阿里云配置
INSIGHT_ENGINE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
INSIGHT_ENGINE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
INSIGHT_ENGINE_MODEL_NAME=qwen-plus

MEDIA_ENGINE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
MEDIA_ENGINE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MEDIA_ENGINE_MODEL_NAME=qwen-max

QUERY_ENGINE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
QUERY_ENGINE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QUERY_ENGINE_MODEL_NAME=qwen-plus

REPORT_ENGINE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
REPORT_ENGINE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
REPORT_ENGINE_MODEL_NAME=qwen-max

MINDSPIDER_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
MINDSPIDER_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MINDSPIDER_MODEL_NAME=qwen-turbo

FORUM_HOST_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
FORUM_HOST_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
FORUM_HOST_MODEL_NAME=qwen-plus

KEYWORD_OPTIMIZER_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
KEYWORD_OPTIMIZER_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
KEYWORD_OPTIMIZER_MODEL_NAME=qwen-plus

# ================== 网络工具配置 ====================
TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxxxxxxxxxx
ANSPIRE_API_KEY=your_anspire_key_here
SEARCH_TOOL_TYPE=AnspireAPI
ANSPIRE_BASE_URL=https://plugin.anspire.cn/api/ntsearch/search
```

---

## 🎯 模型选择建议

### 阿里云DashScope可用模型

| 模型 | 特点 | 适用场景 | 价格 |
|------|------|----------|------|
| **qwen-turbo** | 快速响应 | 简单任务、爬虫 | 💰 |
| **qwen-plus** | 性价比高 | 大部分场景 | 💰💰 |
| **qwen-max** | 最强能力 | 复杂推理、报告生成 | 💰💰💰 |
| **qwen-long** | 长文本 | 超长上下文 | 💰💰 |

### 推荐配置方案

#### 方案1: 经济型（推荐新手）
```bash
# 所有Agent都使用qwen-plus
INSIGHT_ENGINE_MODEL_NAME=qwen-plus
MEDIA_ENGINE_MODEL_NAME=qwen-plus
QUERY_ENGINE_MODEL_NAME=qwen-plus
REPORT_ENGINE_MODEL_NAME=qwen-plus
MINDSPIDER_MODEL_NAME=qwen-plus
FORUM_HOST_MODEL_NAME=qwen-plus
KEYWORD_OPTIMIZER_MODEL_NAME=qwen-plus
```

**优点**: 成本低，性能够用  
**缺点**: 报告质量可能略低

#### 方案2: 平衡型（推荐）
```bash
# 核心Agent使用qwen-max，其他使用qwen-plus
INSIGHT_ENGINE_MODEL_NAME=qwen-plus
MEDIA_ENGINE_MODEL_NAME=qwen-max      # 多模态需要强模型
QUERY_ENGINE_MODEL_NAME=qwen-plus
REPORT_ENGINE_MODEL_NAME=qwen-max     # 报告生成需要强模型
MINDSPIDER_MODEL_NAME=qwen-turbo      # 爬虫用轻量模型
FORUM_HOST_MODEL_NAME=qwen-plus
KEYWORD_OPTIMIZER_MODEL_NAME=qwen-plus
```

**优点**: 性价比最高  
**缺点**: 无

#### 方案3: 性能型
```bash
# 所有Agent都使用qwen-max
INSIGHT_ENGINE_MODEL_NAME=qwen-max
MEDIA_ENGINE_MODEL_NAME=qwen-max
QUERY_ENGINE_MODEL_NAME=qwen-max
REPORT_ENGINE_MODEL_NAME=qwen-max
MINDSPIDER_MODEL_NAME=qwen-max
FORUM_HOST_MODEL_NAME=qwen-max
KEYWORD_OPTIMIZER_MODEL_NAME=qwen-max
```

**优点**: 最佳质量  
**缺点**: 成本较高

---

## 🧪 验证配置

### 1. 测试API连接

```python
# test_aliyun_connection.py
import os
from openai import OpenAI

# 读取配置
api_key = os.getenv("INSIGHT_ENGINE_API_KEY")
base_url = os.getenv("INSIGHT_ENGINE_BASE_URL")
model = os.getenv("INSIGHT_ENGINE_MODEL_NAME")

# 创建客户端
client = OpenAI(
    api_key=api_key,
    base_url=base_url
)

# 测试调用
try:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": "你好，请用一句话介绍你自己"}
        ]
    )
    print("✅ 连接成功！")
    print(f"模型: {model}")
    print(f"响应: {response.choices[0].message.content}")
except Exception as e:
    print(f"❌ 连接失败: {e}")
```

运行测试：
```bash
python test_aliyun_connection.py
```

### 2. 测试LangGraph Agent

```bash
# 启动Streamlit UI
streamlit run SingleEngineApp/insight_engine_langgraph_app.py --server.port 8504

# 在UI中测试一个简单查询
```

---

## 💰 成本估算

### 阿里云DashScope定价（参考）

| 模型 | 输入价格 | 输出价格 | 免费额度 |
|------|----------|----------|----------|
| qwen-turbo | ¥0.3/百万tokens | ¥0.6/百万tokens | 100万tokens/月 |
| qwen-plus | ¥0.8/百万tokens | ¥2/百万tokens | 100万tokens/月 |
| qwen-max | ¥20/百万tokens | ¥60/百万tokens | 100万tokens/月 |

### 单次研究任务成本估算

**场景**: 6段落报告，每段落2次反思

| 配置方案 | 预估tokens | 预估成本 |
|----------|-----------|----------|
| 经济型（全qwen-plus） | ~500K | ¥0.5-1 |
| 平衡型（混合） | ~600K | ¥1-2 |
| 性能型（全qwen-max） | ~500K | ¥20-40 |

**注意**: 
- 实际成本取决于数据库内容量和搜索结果数量
- 免费额度可以支持较多测试

---

## 🔧 高级配置

### 1. 使用不同的API Key

如果你有多个API Key（例如不同的账号），可以分别配置：

```bash
# 主账号（大部分Agent）
INSIGHT_ENGINE_API_KEY=sk-account1-xxxxxxxxxx
QUERY_ENGINE_API_KEY=sk-account1-xxxxxxxxxx

# 备用账号（高成本Agent）
MEDIA_ENGINE_API_KEY=sk-account2-xxxxxxxxxx
REPORT_ENGINE_API_KEY=sk-account2-xxxxxxxxxx
```

### 2. 配置请求参数

在 `InsightEngine/utils/config.py` 中可以调整：

```python
class Settings(BaseSettings):
    # LLM参数
    MAX_REFLECTIONS: int = 3              # 减少可降低成本
    MAX_PARAGRAPHS: int = 6               # 减少可降低成本
    MAX_CONTENT_LENGTH: int = 500000      # 控制输入长度
    MAX_SEARCH_RESULTS_FOR_LLM: int = 50  # 控制搜索结果数量
```

### 3. 启用请求缓存

```python
# 在agent初始化时启用缓存
from openai import OpenAI

client = OpenAI(
    api_key=api_key,
    base_url=base_url,
    default_headers={
        "X-DashScope-SSE": "enable"  # 启用流式响应
    }
)
```

---

## 🐛 常见问题

### Q1: API Key无效

**错误**: `AuthenticationError: Invalid API key`

**解决方案**:
1. 检查API Key是否正确复制（无多余空格）
2. 确认API Key未过期
3. 检查账号是否欠费
4. 确认已开通百炼服务

### Q2: 模型不存在

**错误**: `Model not found: qwen-xxx`

**解决方案**:
1. 检查模型名称拼写
2. 确认使用的是兼容模式URL: `https://dashscope.aliyuncs.com/compatible-mode/v1`
3. 可用模型列表: `qwen-turbo`, `qwen-plus`, `qwen-max`, `qwen-long`

### Q3: 请求超时

**错误**: `Timeout error`

**解决方案**:
1. 检查网络连接
2. 增加超时时间（在config.py中设置）
3. 使用更快的模型（qwen-turbo）

### Q4: 配额不足

**错误**: `Rate limit exceeded`

**解决方案**:
1. 等待配额恢复（通常每分钟重置）
2. 升级到付费版本
3. 使用多个API Key轮换

---

## 📊 监控和优化

### 1. 查看API使用情况

登录阿里云控制台 → 百炼 → 用量统计

### 2. 成本优化建议

1. **减少反思次数**: `MAX_REFLECTIONS = 2` (默认3)
2. **减少段落数**: `MAX_PARAGRAPHS = 4` (默认6)
3. **限制搜索结果**: `MAX_SEARCH_RESULTS_FOR_LLM = 30` (默认50)
4. **使用轻量模型**: 非关键Agent使用qwen-turbo

### 3. 性能优化建议

1. **启用checkpoint**: 避免重复计算
2. **批量处理**: 一次处理多个任务
3. **缓存结果**: 相似查询复用结果

---

## ✅ 配置检查清单

完成配置后，请检查：

- [ ] `.env` 文件已创建
- [ ] 所有 `your_xxx_here` 已替换为实际值
- [ ] API Key格式正确（sk-开头）
- [ ] BASE_URL正确（包含/compatible-mode/v1）
- [ ] 模型名称正确（qwen-turbo/plus/max）
- [ ] 数据库配置正确
- [ ] Tavily API Key已配置（如果使用）
- [ ] Anspire API Key已配置（如果使用）
- [ ] 运行测试脚本验证连接

---

## 🎉 完成！

配置完成后，你可以：

1. **启动LangGraph版本**:
   ```bash
   streamlit run SingleEngineApp/insight_engine_langgraph_app.py --server.port 8504
   ```

2. **启动原版本**:
   ```bash
   python app.py
   ```

3. **运行测试**:
   ```bash
   python test_langgraph_implementation.py
   ```

---

## 📞 获取帮助

如有问题：
- 查看主文档: `docs/QUICKSTART.md`
- 阿里云文档: https://help.aliyun.com/zh/dashscope/
- GitHub Issues: https://github.com/666ghj/BettaFish/issues

---

**文档版本**: v1.0  
**最后更新**: 2026-05-31  
**适用于**: BettaFish + 阿里云DashScope
