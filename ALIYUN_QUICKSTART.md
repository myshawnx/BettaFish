# 阿里云配置快速指南

## 🚀 三种配置方式

### 方式1: 自动配置向导（推荐）⭐

```bash
# 运行配置向导
python setup_aliyun_env.py

# 按提示输入:
# 1. 数据库配置
# 2. 阿里云API Key
# 3. 选择模型方案
# 4. 网络工具配置（可选）

# 自动生成 .env 文件
```

### 方式2: 使用模板文件

```bash
# 1. 复制模板
cp .env.template.aliyun .env

# 2. 编辑 .env 文件
# 替换以下内容:
# - your_dashscope_api_key_here → 你的API Key
# - your_password_here → 数据库密码
# - your_tavily_api_key_here → Tavily Key（可选）
# - your_anspire_api_key_here → Anspire Key（可选）

# 3. 保存文件
```

### 方式3: 手动创建

参考 `docs/ALIYUN_DASHSCOPE_SETUP.md` 中的详细说明。

---

## ✅ 验证配置

```bash
# 测试所有Agent连接
python test_aliyun_connection.py

# 预期输出:
# ✅ Insight Engine: 通过
# ✅ Media Engine: 通过
# ✅ Query Engine: 通过
# ✅ Report Engine: 通过
# ✅ MindSpider: 通过
# ✅ Forum Host: 通过
# ✅ Keyword Optimizer: 通过
# 
# 总计: 7/7 通过 (100.0%)
```

---

## 🎯 推荐配置

### 阿里云DashScope配置

```bash
# API配置
INSIGHT_ENGINE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
INSIGHT_ENGINE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# 模型选择（平衡型方案）
INSIGHT_ENGINE_MODEL_NAME=qwen-plus
MEDIA_ENGINE_MODEL_NAME=qwen-max      # 多模态需要强模型
QUERY_ENGINE_MODEL_NAME=qwen-plus
REPORT_ENGINE_MODEL_NAME=qwen-max     # 报告生成需要强模型
MINDSPIDER_MODEL_NAME=qwen-turbo      # 爬虫用轻量模型
FORUM_HOST_MODEL_NAME=qwen-plus
KEYWORD_OPTIMIZER_MODEL_NAME=qwen-plus
```

### 网络工具配置

```bash
# Tavily搜索（可选）
TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxxxxxxxxxx

# Anspire搜索（推荐）
ANSPIRE_API_KEY=your_anspire_key_here
SEARCH_TOOL_TYPE=AnspireAPI
ANSPIRE_BASE_URL=https://plugin.anspire.cn/api/ntsearch/search
```

---

## 📊 模型选择建议

| Agent | 推荐模型 | 原因 |
|-------|----------|------|
| Insight Engine | qwen-plus | 数据库分析，性价比高 |
| Media Engine | qwen-max | 多模态理解需要强模型 |
| Query Engine | qwen-plus | 网络搜索，性价比高 |
| Report Engine | qwen-max | 报告生成需要强模型 |
| MindSpider | qwen-turbo | 爬虫任务简单 |
| Forum Host | qwen-plus | 论坛主持，性价比高 |
| Keyword Optimizer | qwen-plus | 关键词优化，性价比高 |

---

## 💰 成本估算

### 单次研究任务（6段落，2次反思）

| 配置方案 | 预估成本 |
|----------|----------|
| 经济型（全qwen-plus） | ¥0.5-1 |
| 平衡型（推荐） | ¥1-2 |
| 性能型（全qwen-max） | ¥20-40 |

**免费额度**: 100万tokens/月（足够测试使用）

---

## 🐛 常见问题

### Q1: API Key无效
```bash
# 检查:
# 1. API Key是否正确复制（无空格）
# 2. 是否已开通百炼服务
# 3. 账号是否欠费
```

### Q2: 模型不存在
```bash
# 确认:
# 1. BASE_URL包含 /compatible-mode/v1
# 2. 模型名称: qwen-turbo, qwen-plus, qwen-max
```

### Q3: 连接超时
```bash
# 解决:
# 1. 检查网络连接
# 2. 使用更快的模型（qwen-turbo）
```

---

## 📚 相关文档

- **详细配置指南**: `docs/ALIYUN_DASHSCOPE_SETUP.md`
- **快速开始**: `docs/QUICKSTART.md`
- **LangGraph使用**: `LANGGRAPH_README.md`

---

## 🎉 配置完成后

### 启动LangGraph版本
```bash
streamlit run SingleEngineApp/insight_engine_langgraph_app.py --server.port 8504
```

### 启动原版本
```bash
python app.py
```

### 测试功能
在UI中输入查询，例如: "武汉大学舆情分析"

---

**快速配置完成！** 🚀

如有问题，请查看 `docs/ALIYUN_DASHSCOPE_SETUP.md` 获取详细帮助。
