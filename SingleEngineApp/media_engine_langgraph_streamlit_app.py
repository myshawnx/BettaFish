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
from config import settings
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


def main():
    """主函数"""
    st.set_page_config(
        page_title="Media Agent (LangGraph)",
        page_icon="",
        layout="wide"
    )

    st.title("Media Agent · LangGraph")
    st.markdown("具备强大多模态能力的AI代理 · 支持 checkpoint 断点恢复")
    st.markdown("突破传统文本交流限制，广泛的浏览抖音、快手、小红书的视频、图文、直播")
    st.markdown("使用现代化搜索引擎提供的诸如日历卡、天气卡、股票卡等多模态结构化信息进一步增强能力")

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

    # ----- 配置被硬编码 (与原版一致, 从全局 settings 读取) -----
    model_name = settings.MEDIA_ENGINE_MODEL_NAME or "gemini-2.5-pro"
    max_reflections = 2
    max_content_length = 20000

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
        if not query.strip():
            st.error("请输入研究查询")
            logger.error("请输入研究查询")
            return

        # 检查LLM密钥
        if not settings.MEDIA_ENGINE_API_KEY:
            st.error("请在您的环境变量中设置MEDIA_ENGINE_API_KEY")
            logger.error("请在您的环境变量中设置MEDIA_ENGINE_API_KEY")
            return

        engine_key = settings.MEDIA_ENGINE_API_KEY
        bocha_key = settings.BOCHA_WEB_SEARCH_API_KEY
        anspire_key = settings.ANSPIRE_API_KEY

        # 构建 Settings (依据 SEARCH_TOOL_TYPE 选择搜索后端; create_langgraph_agent 据此分发)
        if settings.SEARCH_TOOL_TYPE == "BochaAPI":
            if not bocha_key:
                st.error("请在您的环境变量中设置BOCHA_WEB_SEARCH_API_KEY")
                logger.error("请在您的环境变量中设置BOCHA_WEB_SEARCH_API_KEY")
                return
            logger.info("使用Bocha搜索API密钥")
            config = Settings(
                MEDIA_ENGINE_API_KEY=engine_key,
                MEDIA_ENGINE_BASE_URL=settings.MEDIA_ENGINE_BASE_URL,
                MEDIA_ENGINE_MODEL_NAME=model_name,
                SEARCH_TOOL_TYPE="BochaAPI",
                BOCHA_WEB_SEARCH_API_KEY=bocha_key,
                MAX_REFLECTIONS=max_reflections,
                SEARCH_CONTENT_MAX_LENGTH=max_content_length,
                OUTPUT_DIR="media_engine_streamlit_reports",
            )
        elif settings.SEARCH_TOOL_TYPE == "AnspireAPI":
            if not anspire_key:
                st.error("请在您的环境变量中设置ANSPIRE_API_KEY")
                logger.error("请在您的环境变量中设置ANSPIRE_API_KEY")
                return
            logger.info("使用Anspire搜索API密钥")
            config = Settings(
                MEDIA_ENGINE_API_KEY=engine_key,
                MEDIA_ENGINE_BASE_URL=settings.MEDIA_ENGINE_BASE_URL,
                MEDIA_ENGINE_MODEL_NAME=model_name,
                SEARCH_TOOL_TYPE="AnspireAPI",
                ANSPIRE_API_KEY=anspire_key,
                MAX_REFLECTIONS=max_reflections,
                SEARCH_CONTENT_MAX_LENGTH=max_content_length,
                OUTPUT_DIR="media_engine_streamlit_reports",
            )
        else:
            st.error(f"未知的搜索工具类型: {settings.SEARCH_TOOL_TYPE}")
            logger.error(f"未知的搜索工具类型: {settings.SEARCH_TOOL_TYPE}")
            return

        # 执行研究
        execute_research(query, config)


def execute_research(query: str, config: Settings):
    """执行研究 (流式驱动 LangGraph, 实时更新进度)"""
    try:
        # 创建进度条
        progress_bar = st.progress(0)
        status_text = st.empty()

        # 初始化Agent (依据 SEARCH_TOOL_TYPE 选择 Bocha / Anspire 后端)
        status_text.text("正在初始化 LangGraph Agent...")
        agent = create_langgraph_agent(config=config, checkpoint_dir=".checkpoints")
        progress_bar.progress(5)

        # 生成 thread_id (支持后续断点恢复)
        thread_id = f"media_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        st.session_state.langgraph_thread_id = thread_id
        st.caption(f"Thread ID: `{thread_id}` (checkpoint 已自动保存, 可用于断点恢复)")

        # 结构节点由 LLM 决定段落数(常 4-7 段), 每段约需 (2*反思次数+4) 步;
        # LangGraph 默认 recursion_limit=25 在多段落时会中途抛 RecursionError, 这里给足余量。
        recursion_limit = (2 * config.MAX_REFLECTIONS + 4) * 15 + 10
        graph_config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
        initial_state = create_initial_state(
            query=query,
            max_reflections=config.MAX_REFLECTIONS,
            max_paragraphs=config.MAX_PARAGRAPHS,
        )

        # 流式驱动图 (stream_mode="updates": 每步返回 {节点名: 更新})
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

        # 提取最终累积状态
        final_state = agent.graph.get_state(graph_config).values
        final_report = final_state.get("final_report", "")

        progress_bar.progress(100)
        status_text.text("研究完成！")

        if not final_report or not final_report.strip():
            st.error("未生成最终报告 (final_report 为空)")
            logger.error("未生成最终报告")
            return

        # 保存报告
        agent._save_report(query, final_report, thread_id)

        # 显示结果
        display_results(final_state, final_report)

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
