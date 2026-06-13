# BettaFish-new Portfolio Delivery Checklist

本文档描述当前仓库已经交付的 Python Agent 作品集能力，以及面试/CI 场景下应验证的边界。它不再把 MCP 或 AgentRuntime 写成未来规划；这些能力已经在当前代码中落地。

## 当前交付状态

| 模块 | 状态 | 当前能力 |
|------|------|----------|
| InsightEngine LangGraph | 已完成 | `InsightEngine/langgraph_state.py`、`InsightEngine/langgraph_agent.py`、`SingleEngineApp/insight_engine_langgraph_streamlit_app.py`，支持 StateGraph、SqliteSaver checkpoint、`resume_research()` |
| MediaEngine LangGraph | 已完成 | `MediaEngine/langgraph_state.py`、`MediaEngine/langgraph_agent.py`、`SingleEngineApp/media_engine_langgraph_streamlit_app.py`，支持 Anspire/Bocha 后端选择与 checkpoint |
| QueryEngine LangGraph | 已完成 | `QueryEngine/langgraph_state.py`、`QueryEngine/langgraph_agent.py`、`SingleEngineApp/query_engine_langgraph_streamlit_app.py`，支持 Tavily 搜索封装与 checkpoint |
| Flask 主控制台 | 已完成 | `app.py` 默认启动三个 LangGraph Streamlit iframe 子应用，并提供 system/forum/report 状态接口 |
| AgentRuntime | 已完成 | `AgentRuntime/registry.py` 提供 JSONL run/event registry，LangGraph 节点写入结构化事件 |
| ForumEngine | 已完成 | `ForumEngine/monitor.py` 优先消费 AgentRuntime 事件，再回退日志解析；`ForumEngine/llm_host.py` 支持无 key 规则 fallback moderator verdict |
| MCPServer | 已完成 | `MCPServer/tools.py` 与 `MCPServer/server.py` 提供可单测工具和 stdio MCP server |
| Postgres seed demo | 已完成 | `sample_data/portfolio_insight_seed.json` 与 `scripts/seed_portfolio_data.py` 提供确定性样例数据 |
| no-key CI | 已完成 | `.github/workflows/ci.yml` 覆盖 compileall、Forum、MCP、AgentRuntime、LangGraph import、前端 smoke、seed 数据、Query guard |
| live crawlers | 可选增强 | MindSpider / MediaCrawler 保留，但默认 `ENABLE_LIVE_CRAWLERS=false` |

## 作品集演示路径

| 路径 | 目标 | 必需条件 | 验收标准 |
|------|------|----------|----------|
| no-key smoke | 证明作品集基线不依赖真实 key、爬虫账号或外部数据库 | Python 3.11、项目依赖 | compileall、no-key pytest 子集、`python -m MCPServer.server --list` 全部通过 |
| Postgres seed demo | 展示确定性 Insight 数据检索与主控制台体验 | Docker/Postgres、seed 数据 | `scripts.seed_portfolio_data --reset` 可写入样例数据，主控制台可启动三个 LangGraph 子应用 |
| full API-key demo | 展示真实 LLM/Search API 和可选 live crawler 集成 | LLM key、Tavily key、Anspire/Bocha key，必要时 Playwright/爬虫账号 | 三引擎能执行真实研究任务，失败时不影响 no-key 基线 |

## no-key 验收命令

这些命令对应当前 CI，不需要 API key、Postgres、Playwright 或 live crawler：

```bash
PORTFOLIO_DEMO_MODE=true ENABLE_LIVE_CRAWLERS=false FORUM_HOST_API_KEY= python -m compileall -q \
  app.py \
  InsightEngine \
  MediaEngine \
  QueryEngine \
  ForumEngine \
  AgentRuntime \
  MindSpider/schema \
  SingleEngineApp \
  tests \
  MCPServer

PORTFOLIO_DEMO_MODE=true ENABLE_LIVE_CRAWLERS=false FORUM_HOST_API_KEY= python -m pytest \
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

PORTFOLIO_DEMO_MODE=true ENABLE_LIVE_CRAWLERS=false FORUM_HOST_API_KEY= python -m MCPServer.server --list
```

## MCP 工具验收

当前 MCP 工具注册表位于 `MCPServer/tools.py`，并由 `tests/test_mcp_server.py` 和 `tests/test_documented_commands.py` 覆盖：

- `portfolio_agent_runtime_status`
- `portfolio_agent_runs`
- `portfolio_agent_events`
- `portfolio_system_status`
- `portfolio_forum_status`
- `portfolio_search_insights`
- `portfolio_demo_topics`

命令行快速检查：

```bash
python -m MCPServer.server --list
python -m MCPServer.server --call portfolio_demo_topics
python -m MCPServer.server --call portfolio_agent_runtime_status
```

## Forum Moderator 验收

Forum Host 有两条路径：

- 配置 `FORUM_HOST_API_KEY` 时，使用 OpenAI-compatible LLM 生成主持人发言。
- 不配置 key 时，走规则 fallback，仍返回结构化 verdict。

只读接口：

```bash
curl http://127.0.0.1:5000/api/forum/moderator/status
```

核心测试：

- `tests/test_forum_moderator.py`
- `tests/test_monitor.py`
- `tests/test_agent_runtime.py`
- `tests/test_mcp_server.py`

## 交付保护规则

- 不让 no-key CI 依赖真实 API key、外部数据库、Playwright 浏览器或 crawler 账号。
- 不提交 `.env`、真实 key、运行日志、checkpoint 或数据库文件。
- 文档中的 no-key 命令必须与 `.github/workflows/ci.yml` 保持一致。
- 涉及 `app.py` 或前端状态接口时跑 `tests/test_frontend_smoke.py`。
- 涉及 MCP 工具时跑 `tests/test_mcp_server.py` 和 `tests/test_documented_commands.py`。
- 实时爬虫和 full API-key demo 是增强路径，不能破坏 `PORTFOLIO_DEMO_MODE=true` / `ENABLE_LIVE_CRAWLERS=false` 的默认体验。

## 后续增强方向

当前最有价值的后续工作不是重新规划 MCP，而是在已有作品集基线上增强：

1. 完善 Postgres seed demo 的本地脚本化体验。
2. 为 full API-key demo 增加更清晰的失败提示和 key 检测。
3. 在 AgentRuntime 基础上补充可视化运行时间线。
4. 按需评估 RAG / hybrid retrieval，但保持 no-key CI 不变。

**交付状态**: 当前作品集基线已完成，后续工作属于增强项。
