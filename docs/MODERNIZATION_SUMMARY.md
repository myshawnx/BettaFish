# BettaFish-new Modernization Summary

本文档记录当前真实代码状态。早期路线图中的 LangGraph 改造、MCP 工具化和 Forum fallback 已经进入主线；当前默认叙事是 Python Agent 面试作品集，而不是实时爬虫系统。

## 当前定位

BettaFish-new 保留原 BettaFish 的多 Agent 舆情分析语境，但默认运行路径已经收敛为：

```bash
PORTFOLIO_DEMO_MODE=true
ENABLE_LIVE_CRAWLERS=false
```

默认演示通过 Postgres seed 数据、LangGraph 编排、AgentRuntime 结构化事件、Forum moderator fallback 和 MCP 工具展示工程能力。MindSpider / MediaCrawler 实时爬虫仍在仓库中，但属于 optional integration。

## 已完成能力

### 1. 三个 LangGraph 子应用

InsightEngine、MediaEngine、QueryEngine 均已有独立 LangGraph 版本：

- `*/langgraph_state.py`
- `*/langgraph_agent.py`
- `SingleEngineApp/*_langgraph_streamlit_app.py`

共同能力：

- StateGraph 声明式节点编排
- SqliteSaver checkpoint
- `resume_research(thread_id=...)`
- 节点级错误记录
- 保留旧版 `agent.py`，便于对照和兼容

### 2. 主控制台 LangGraph 化

`app.py` 默认启动三个 LangGraph Streamlit 子应用：

- `SingleEngineApp/insight_engine_langgraph_streamlit_app.py`
- `SingleEngineApp/media_engine_langgraph_streamlit_app.py`
- `SingleEngineApp/query_engine_langgraph_streamlit_app.py`

实时爬虫入口被 `ENABLE_LIVE_CRAWLERS` 控制。默认关闭时，主控制台会跳过 MindSpider / MediaCrawler 初始化。

### 3. AgentRuntime JSONL registry

`AgentRuntime/registry.py` 提供轻量级 run/event registry：

- `start_run(engine, query, thread_id, checkpoint_path=...)`
- `record_event(engine, run_id, thread_id, event_type, node=..., payload=...)`
- `finish_run(run_id, status, final_report_path=..., error_summary=...)`
- `list_runs(...)`
- `list_events(...)`
- `get_runtime_status(...)`
- `build_langgraph_payload(...)`

三条 LangGraph agent 已接入该 registry。运行记录默认写入 `logs/agent_runs.jsonl` 和 `logs/agent_events.jsonl`，也可通过 `AGENT_RUNTIME_LOG_DIR` 重定向到测试目录。

### 4. ForumEngine 结构化消费与 fallback

ForumEngine 当前有两层输入：

1. 优先消费 AgentRuntime 结构化事件。
2. 如果没有事件，再回退解析传统日志文本。

Forum Host 当前有两层主持人路径：

1. 配置 `FORUM_HOST_API_KEY` 时使用 OpenAI-compatible LLM。
2. 无 key 或 LLM 失败时使用规则 fallback。

fallback 仍返回结构化 verdict：

- `topic`
- `risk_level`
- `action`
- `rationale`
- `suggested_host_message`
- `source_count`
- `llm_enabled`

主控制台只读接口：

```bash
GET /api/forum/moderator/status
```

### 5. MCPServer 已经落地

`MCPServer` 不是未来 Phase 2，而是当前默认能力。工具函数在 `MCPServer/tools.py` 中保持无 SDK 依赖，`MCPServer/server.py` 负责适配 MCP SDK 和 CLI。

当前工具：

- `portfolio_agent_runtime_status`
- `portfolio_agent_runs`
- `portfolio_agent_events`
- `portfolio_system_status`
- `portfolio_forum_status`
- `portfolio_search_insights`
- `portfolio_demo_topics`

快速验证：

```bash
python -m MCPServer.server --list
python -m MCPServer.server --call portfolio_demo_topics
python -m MCPServer.server --call portfolio_agent_runtime_status
```

### 6. Postgres seed demo

确定性样例数据位于：

- `sample_data/portfolio_insight_seed.json`

写入脚本：

- `scripts/seed_portfolio_data.py`

样例数据用于避免空库时由 LLM 编造结论，也让面试演示能复现相同主题、平台、观点和时间戳。

### 7. no-key CI

`.github/workflows/ci.yml` 当前验证：

- core packages compileall
- Forum monitor / moderator fallback
- ReportEngine sanitization
- Postgres seed shape 和 dry-run
- LangGraph imports
- frontend smoke
- AgentRuntime registry
- MCP tools 和 CLI list path
- Query/LangGraph guard tests
- 文档命令与 CI/MCP registry 一致性

## 三条演示路径

| 路径 | 当前用途 | 依赖 | 保护要求 |
|------|----------|------|----------|
| no-key smoke | CI 和面试预检 | Python 3.11、项目依赖 | 不需要 API key、Postgres、Playwright、外部服务 |
| Postgres seed demo | 主控制台与 Insight 确定性数据演示 | Docker/Postgres、seed 数据 | 不启动实时爬虫，不要求搜索 API key |
| full API-key demo | 真实 LLM/Search API 与可选 crawler 集成 | LLM/Tavily/Anspire/Bocha key，可选 Playwright/账号 | 只能增强，不得破坏 no-key 基线 |

## 当前风险与约束

- MediaEngine / QueryEngine 真实研究仍需要搜索 API key；no-key CI 只验证可导入、guard 和 fallback。
- `.checkpoints/`、logs、数据库文件和真实 `.env` 不应提交。
- Pydantic Settings 必须允许无 key 导入，真实执行时再由 LLM/search client 校验 key。
- 文档中的 no-key 命令必须可在本地和 CI 中执行。

## 推荐后续增强

1. 给 Postgres seed demo 增加一键本地脚本，减少面试现场手动步骤。
2. 给 full API-key demo 增加配置自检和缺 key 友好错误。
3. 基于 AgentRuntime 事件做前端 timeline 或 MCP 观察面板。
4. 如需提升 Insight 召回，可在 seed/no-key 基线之外评估 RAG 或 hybrid retrieval。

## 快速验收命令

```bash
python -m compileall -q app.py InsightEngine MediaEngine QueryEngine ForumEngine AgentRuntime MindSpider/schema SingleEngineApp tests MCPServer

python -m pytest \
  tests/test_monitor.py \
  tests/test_report_engine_sanitization.py \
  tests/test_portfolio_seed.py \
  tests/test_langgraph_imports.py \
  tests/test_frontend_smoke.py \
  tests/test_forum_moderator.py \
  tests/test_agent_runtime.py \
  tests/test_mcp_server.py \
  tests/test_query_engine_guards.py \
  tests/test_documented_commands.py \
  -q

python -m MCPServer.server --list
```

**当前结论**: LangGraph、AgentRuntime、Forum fallback、MCPServer 和 no-key CI 均已落地。下一阶段应围绕演示体验、full API-key 自检和运行可观测性继续增强。
