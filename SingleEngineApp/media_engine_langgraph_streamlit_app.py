"""
Streamlit Web界面 (LangGraph版)
为 Media Agent 提供友好的 Web 界面 —— 作为 app.py 主控制台的 media 子应用被 iframe 嵌入。

与原版 media_engine_streamlit_app.py 保持相同的"嵌入契约":
- 从 URL 读取 ?query=...&auto_search=true, 由主页搜索框驱动
- 配置硬编码, 从全局 settings 读取 (无侧边栏手动输入)
- 依据 SEARCH_TOOL_TYPE 选择 Bocha / Anspire 搜索后端
- 只读查询展示 + error_with_issue_link 错误处理

区别仅在引擎: 使用 create_langgraph_agent (StateGraph + SqliteSaver checkpoint),
而非旧的 DeepSearchAgent / AnspireSearchAgent。流程: 结构 -> 逐段多模态搜索/总结
-> 反思循环 -> 推进段落 -> 最终报告。
"""

import os
import sys
import streamlit as st
from datetime import datetime
import locale
from loguru import logger

# 设置UTF-8编码环境
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['PYTHONUTF8'] = '1'

# 设置系统编码
try:
    locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
except locale.Error:
    try:
        locale.setlocale(locale.LC_ALL, 'C.UTF-8')
    except locale.Error:
        pass

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from MediaEngine.langgraph_agent import create_langgraph_agent
from MediaEngine.langgraph_state import create_initial_state
from MediaEngine.utils.config import Settings
from AgentRuntime import finish_run, start_run
from config import settings
from SingleEngineApp.langgraph_recovery import (
    is_recoverable_api_error,
    normalize_error_text,
    render_api_recovery_form,
)
from utils.github_issues import error_with_issue_link


# 节点 -> 中文进度描述 (与图节点名一一对应)
NODE_DESC = {
    "generate_structure": "正在生成报告结构...",
    "search_paragraph": "正在进行多模态搜索...",
    "summarize_paragraph": "正在总结段落...",
    "reflect_paragraph": "正在反思并补充检索...",
    "update_summary": "正在更新段落总结...",
    "advance_paragraph": "推进到下一段落...",
    "format_report": "正在生成最终报告...",
}

# 段落内各阶段的进度占比 (用于估算总进度条)
STAGE_FRACTION = {
    "search_paragraph": 0.2,
    "summarize_paragraph": 0.5,
    "reflect_paragraph": 0.65,
    "update_summary": 0.8,
    "advance_paragraph": 1.0,
}

RECOVERY_STATE_KEY = "media_langgraph_api_recovery"


def _setting_value(values: dict | None, key: str, default=None):
    if values and key in values:
        return values[key]
    return getattr(settings, key, default)


def build_media_config(values: dict | None = None) -> Settings:
    """Build a MediaEngine Settings object from submitted values plus current settings."""
    search_tool_type = _setting_value(values, "SEARCH_TOOL_TYPE") or settings.SEARCH_TOOL_TYPE
    return Settings(
        MEDIA_ENGINE_API_KEY=_setting_value(values, "MEDIA_ENGINE_API_KEY"),
        MEDIA_ENGINE_BASE_URL=_setting_value(values, "MEDIA_ENGINE_BASE_URL"),
        MEDIA_ENGINE_MODEL_NAME=_setting_value(values, "MEDIA_ENGINE_MODEL_NAME") or "gemini-2.5-pro",
        SEARCH_TOOL_TYPE=search_tool_type,
        BOCHA_BASE_URL=_setting_value(values, "BOCHA_BASE_URL"),
        BOCHA_WEB_SEARCH_API_KEY=_setting_value(values, "BOCHA_WEB_SEARCH_API_KEY"),
        ANSPIRE_BASE_URL=_setting_value(values, "ANSPIRE_BASE_URL"),
        ANSPIRE_API_KEY=_setting_value(values, "ANSPIRE_API_KEY"),
        MAX_REFLECTIONS=2,
        SEARCH_CONTENT_MAX_LENGTH=20000,
        OUTPUT_DIR="media_engine_streamlit_reports",
    )


def _api_recovery_fields(values: dict | None = None):
    return [
        {
            "key": "MEDIA_ENGINE_API_KEY",
            "label": "Media LLM API Key",
            "value": _setting_value(values, "MEDIA_ENGINE_API_KEY"),
            "secret": True,
            "required": True,
        },
        {
            "key": "MEDIA_ENGINE_BASE_URL",
            "label": "Media LLM Base URL",
            "value": _setting_value(values, "MEDIA_ENGINE_BASE_URL"),
        },
        {
            "key": "MEDIA_ENGINE_MODEL_NAME",
            "label": "Media LLM Model",
            "value": _setting_value(values, "MEDIA_ENGINE_MODEL_NAME") or "gemini-2.5-pro",
            "required": True,
        },
        {
            "key": "SEARCH_TOOL_TYPE",
            "label": "Search Tool",
            "value": _setting_value(values, "SEARCH_TOOL_TYPE") or "AnspireAPI",
            "options": ["AnspireAPI", "BochaAPI"],
            "required": True,
        },
        {
            "key": "BOCHA_WEB_SEARCH_API_KEY",
            "label": "Bocha API Key",
            "value": _setting_value(values, "BOCHA_WEB_SEARCH_API_KEY"),
            "secret": True,
        },
        {
            "key": "BOCHA_BASE_URL",
            "label": "Bocha Base URL",
            "value": _setting_value(values, "BOCHA_BASE_URL"),
        },
        {
            "key": "ANSPIRE_API_KEY",
            "label": "Anspire API Key",
            "value": _setting_value(values, "ANSPIRE_API_KEY"),
            "secret": True,
        },
        {
            "key": "ANSPIRE_BASE_URL",
            "label": "Anspire Base URL",
            "value": _setting_value(values, "ANSPIRE_BASE_URL"),
        },
    ]


def _remember_api_recovery(query: str, thread_id: str | None, error, mode: str = "resume"):
    st.session_state[RECOVERY_STATE_KEY] = {
        "query": query,
        "thread_id": thread_id,
        "error": normalize_error_text(error),
        "mode": mode,
    }


def _clear_api_recovery():
    st.session_state.pop(RECOVERY_STATE_KEY, None)


def main():
    """主函数"""
    st.set_page_config(
        page_title="Media Agent (LangGraph)",
        page_icon="",
        layout="wide"
    )

    st.title("Media Agent · LangGraph")
    st.markdown("多模态研判 Agent · 支持 StateGraph checkpoint 断点恢复")
    st.markdown("面向作品集 demo 的网页与多模态信息补充，不依赖默认实时爬虫链路")

    # 检查URL参数 (主页通过 ?query=...&auto_search=true 驱动)
    try:
        # 尝试使用新版本的query_params
        query_params = st.query_params
        auto_query = query_params.get('query', '')
        auto_search = query_params.get('auto_search', 'false').lower() == 'true'
    except AttributeError:
        # 兼容旧版本
        query_params = st.experimental_get_query_params()
        auto_query = query_params.get('query', [''])[0]
        auto_search = query_params.get('auto_search', ['false'])[0].lower() == 'true'

    # 如果有自动查询，使用它作为默认值，否则显示占位符
    display_query = auto_query if auto_query else "等待从主页面接收分析内容..."

    # 只读的查询展示区域
    st.text_area(
        "当前查询",
        value=display_query,
        height=100,
        disabled=True,
        help="查询内容由主页面的搜索框控制",
        label_visibility="hidden"
    )

    # 自动搜索逻辑
    start_research = False
    query = auto_query

    if auto_search and auto_query and 'auto_search_executed' not in st.session_state:
        st.session_state.auto_search_executed = True
        start_research = True
    elif auto_query and not auto_search:
        st.warning("等待搜索启动信号...")

    # 验证配置
    if start_research:
        _clear_api_recovery()
        if not query.strip():
            st.error("请输入研究查询")
            logger.error("请输入研究查询")
            return

        missing = []
        if not settings.MEDIA_ENGINE_API_KEY:
            missing.append("MEDIA_ENGINE_API_KEY")
        if settings.SEARCH_TOOL_TYPE == "BochaAPI" and not settings.BOCHA_WEB_SEARCH_API_KEY:
            missing.append("BOCHA_WEB_SEARCH_API_KEY")
        elif settings.SEARCH_TOOL_TYPE == "AnspireAPI" and not settings.ANSPIRE_API_KEY:
            missing.append("ANSPIRE_API_KEY")

        if missing:
            message = "缺少必要 API 配置: " + ", ".join(missing)
            st.error(message)
            logger.error(message)
            _remember_api_recovery(query, None, message, mode="start")
        elif settings.SEARCH_TOOL_TYPE in {"BochaAPI", "AnspireAPI"}:
            logger.info(f"使用{settings.SEARCH_TOOL_TYPE}搜索API密钥")
            execute_research(query, build_media_config())
        else:
            message = f"未知的搜索工具类型: {settings.SEARCH_TOOL_TYPE}"
            st.error(message)
            logger.error(message)
            _remember_api_recovery(query, None, message, mode="start")

    render_pending_api_recovery()


def _missing_media_search_key(values: dict) -> str | None:
    search_tool = values.get("SEARCH_TOOL_TYPE") or settings.SEARCH_TOOL_TYPE
    if search_tool == "BochaAPI" and not values.get("BOCHA_WEB_SEARCH_API_KEY"):
        return "BOCHA_WEB_SEARCH_API_KEY"
    if search_tool == "AnspireAPI" and not values.get("ANSPIRE_API_KEY"):
        return "ANSPIRE_API_KEY"
    return None


def render_pending_api_recovery():
    recovery = st.session_state.get(RECOVERY_STATE_KEY)
    if not recovery:
        return

    mode = recovery.get("mode", "resume")
    submit_label = "保存配置并继续研究" if mode == "resume" else "保存配置并开始研究"
    merged_values = render_api_recovery_form(
        form_key="media_api_recovery_form",
        engine_label="Media Agent",
        fields=_api_recovery_fields(),
        error_text=recovery.get("error", ""),
        thread_id=recovery.get("thread_id"),
        submit_label=submit_label,
    )
    if merged_values is None:
        return

    missing_search_key = _missing_media_search_key(merged_values)
    if missing_search_key:
        st.error(f"请补全配置: {missing_search_key}")
        return

    query = recovery.get("query") or ""
    thread_id = recovery.get("thread_id")
    config = build_media_config(merged_values)
    _clear_api_recovery()
    if mode == "resume" and thread_id:
        completed = resume_research(query, thread_id, config)
    else:
        completed = execute_research(query, config)
    if completed:
        _clear_api_recovery()


def _stream_graph(agent, graph_config: dict, initial_state, progress_bar, status_text) -> dict:
    """Stream LangGraph updates and return the accumulated final state."""
    total_paragraphs = 1
    current_idx = 0
    for chunk in agent.graph.stream(initial_state, graph_config, stream_mode="updates"):
        for node_name, node_update in chunk.items():
            if node_name == "generate_structure":
                paras = (node_update or {}).get("paragraphs", [])
                if paras:
                    total_paragraphs = len(paras)
                status_text.text(NODE_DESC.get(node_name, node_name))
                progress_bar.progress(10)
            elif node_name == "advance_paragraph":
                current_idx = (node_update or {}).get("current_paragraph_index", current_idx + 1)
                status_text.text(NODE_DESC.get(node_name, node_name))
            elif node_name == "format_report":
                status_text.text(NODE_DESC.get(node_name, node_name))
                progress_bar.progress(99)
            else:
                frac = STAGE_FRACTION.get(node_name, 0.0)
                overall = 10 + int(85 * (current_idx + frac) / max(total_paragraphs, 1))
                progress_bar.progress(min(max(overall, 10), 98))
                status_text.text(
                    f"{NODE_DESC.get(node_name, node_name)} (段落 {current_idx + 1}/{total_paragraphs})"
                )

    return agent.graph.get_state(graph_config).values


def execute_research(query: str, config: Settings) -> bool:
    """执行研究 (流式驱动 LangGraph, 实时更新进度)"""
    return _run_research(query, config, thread_id=None, resume=False)


def resume_research(query: str, thread_id: str, config: Settings) -> bool:
    """从已有 checkpoint 继续研究。"""
    return _run_research(query, config, thread_id=thread_id, resume=True)


def _run_research(query: str, config: Settings, thread_id: str | None, resume: bool) -> bool:
    agent = None
    runtime_run = None
    try:
        # 创建进度条
        progress_bar = st.progress(0)
        status_text = st.empty()

        # 初始化Agent (依据 SEARCH_TOOL_TYPE 选择 Bocha / Anspire 后端)
        status_text.text("正在初始化 LangGraph Agent...")
        agent = create_langgraph_agent(config=config, checkpoint_dir=".checkpoints")
        progress_bar.progress(5)

        if resume:
            if not thread_id:
                raise ValueError("恢复研究需要 thread_id")
            st.caption(f"Thread ID: `{thread_id}` (正在从 checkpoint 恢复)")
        else:
            thread_id = f"media_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            st.caption(f"Thread ID: `{thread_id}` (checkpoint 已自动保存, 可用于断点恢复)")
        st.session_state.langgraph_thread_id = thread_id

        recursion_limit = agent._calculate_recursion_limit(
            config.MAX_REFLECTIONS,
            config.MAX_PARAGRAPHS,
        )
        graph_config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
        if resume and agent.checkpointer.get(graph_config) is None:
            raise ValueError(f"未找到 thread_id={thread_id} 的 checkpoint")

        runtime_run = start_run(
            "media",
            f"resume:{query}" if resume else query,
            thread_id,
            checkpoint_path=getattr(agent, "checkpoint_path", None),
        )
        agent._active_run_id = runtime_run.get("run_id")
        agent._active_thread_id = thread_id

        initial_state = None
        if not resume:
            initial_state = create_initial_state(
                query=query,
                max_reflections=config.MAX_REFLECTIONS,
                max_paragraphs=config.MAX_PARAGRAPHS,
            )

        final_state = _stream_graph(agent, graph_config, initial_state, progress_bar, status_text)
        final_report = final_state.get("final_report", "")

        progress_bar.progress(100)
        status_text.text("研究完成！")

        if not final_report or not final_report.strip():
            st.error("未生成最终报告 (final_report 为空)")
            logger.error("未生成最终报告")
            if runtime_run:
                finish_run(runtime_run.get("run_id"), "failed", error_summary="final_report is empty")
            return False

        # 保存报告
        report_query = final_state.get("query") or query
        report_path = agent._save_report(report_query, final_report, thread_id)
        finish_run(runtime_run.get("run_id") if runtime_run else None, "completed", final_report_path=report_path)

        # 显示结果
        display_results(final_state, final_report)
        return True

    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        error_display = error_with_issue_link(
            f"研究过程中发生错误: {str(e)}",
            error_traceback,
            app_name="Media Engine LangGraph Streamlit App"
        )
        st.error(error_display)
        logger.exception(f"研究过程中发生错误: {str(e)}")
        if runtime_run:
            finish_run(runtime_run.get("run_id"), "failed", error_summary=str(e))
        recovery_thread_id = thread_id or st.session_state.get("langgraph_thread_id")
        if is_recoverable_api_error(e):
            _remember_api_recovery(query, recovery_thread_id, e, mode="resume" if recovery_thread_id else "start")
            st.info("已保留当前进度。更新 API 配置后可以从 checkpoint 继续。")
        return False
    finally:
        if agent is not None:
            agent._active_run_id = None
            agent._active_thread_id = None


def display_results(final_state: dict, final_report: str):
    """显示研究结果"""
    st.header("工作结束")

    # 结果标签页
    tab1, tab2 = st.tabs(["研究小结", "段落详情"])

    with tab1:
        st.markdown(final_report)

    with tab2:
        paragraphs = final_state.get("paragraphs", [])

        # 段落详情
        st.subheader("段落详情")
        for i, paragraph in enumerate(paragraphs):
            title = paragraph.get("title", f"段落{i + 1}")
            with st.expander(f"段落 {i + 1}: {title}"):
                st.write("**预期内容:**", paragraph.get("content", ""))
                summary = paragraph.get("latest_summary", "") or ""
                preview = summary[:300] + "..." if len(summary) > 300 else summary
                st.write("**最终内容:**", preview)
                st.write("**反思次数:**", paragraph.get("reflection_count", 0))
                st.write("**搜索次数:**", len(paragraph.get("search_history", [])))

        # 搜索历史
        st.subheader("搜索历史")
        all_searches = []
        for paragraph in paragraphs:
            all_searches.extend(paragraph.get("search_history", []))

        if all_searches:
            for i, search in enumerate(all_searches):
                q = search.get("query", "")
                with st.expander(f"搜索 {i + 1}: {q}"):
                    st.write("**工具:**", search.get("tool_name", ""))
                    st.write("**结果数:**", len(search.get("results", [])))
                    st.write("**时间:**", search.get("timestamp", ""))
        else:
            st.info("本次研究未返回搜索结果。")


if __name__ == "__main__":
    main()
