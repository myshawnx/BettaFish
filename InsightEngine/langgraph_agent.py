"""
LangGraph版本的InsightEngine Agent
使用StateGraph实现可checkpoint的执行流程

主要改进:
1. 声明式图结构替代命令式调用
2. SqliteSaver checkpoint支持断点续传
3. TypedDict + Reducer模式管理状态
4. 保留现有tools/prompts/llms
"""

import os
import sqlite3
from typing import Dict, Any, List, Literal, Optional
from datetime import datetime
from loguru import logger

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from AgentRuntime import build_langgraph_payload, finish_run, record_event, start_run
from utils.retry_helper import is_recoverable_api_error

from .langgraph_state import (
    InsightGraphState,
    create_initial_state,
    add_paragraph,
    update_paragraph_summary,
    add_search_to_paragraph,
    increment_reflection,
    mark_paragraph_completed,
    add_message,
    add_error,
    SearchResult
)

# 复用现有模块
from .llms import LLMClient
from .nodes import (
    ReportStructureNode,
    FirstSearchNode,
    FirstSummaryNode,
    ReflectionNode,
    ReflectionSummaryNode,
    ReportFormattingNode
)
from .tools import MediaCrawlerDB, keyword_optimizer, multilingual_sentiment_analyzer
from .utils import format_search_results_for_prompt
from .utils.config import Settings, settings


class LangGraphInsightAgent:
    """
    基于LangGraph的InsightEngine Agent

    特性:
    - 自动checkpoint (SqliteSaver)
    - 可中断恢复
    - 状态版本控制
    - 声明式图结构
    """

    def __init__(self, config: Optional[Settings] = None, checkpoint_dir: str = ".checkpoints"):
        """
        初始化LangGraph Agent

        Args:
            config: 配置对象
            checkpoint_dir: checkpoint存储目录
        """
        self.config = config or settings
        self.checkpoint_dir = checkpoint_dir

        # 初始化LLM客户端
        self.llm_client = LLMClient(
            api_key=self.config.INSIGHT_ENGINE_API_KEY,
            model_name=self.config.INSIGHT_ENGINE_MODEL_NAME,
            base_url=self.config.INSIGHT_ENGINE_BASE_URL,
        )

        # 初始化工具
        self.search_agency = MediaCrawlerDB()
        self.sentiment_analyzer = multilingual_sentiment_analyzer

        # 初始化节点 (复用现有实现)
        self.structure_node_impl = ReportStructureNode(self.llm_client, "")
        self.first_search_node_impl = FirstSearchNode(self.llm_client)
        self.first_summary_node_impl = FirstSummaryNode(self.llm_client)
        self.reflection_node_impl = ReflectionNode(self.llm_client)
        self.reflection_summary_node_impl = ReflectionSummaryNode(self.llm_client)
        self.report_formatting_node_impl = ReportFormattingNode(self.llm_client)

        # 创建checkpoint saver
        # 注意: 直接构造sqlite连接, 而非使用from_conn_string()
        # from_conn_string()在新版本中返回上下文管理器, 且checkpointer需在Agent生命周期内持续存在
        # check_same_thread=False: Streamlit多线程环境下必需
        os.makedirs(checkpoint_dir, exist_ok=True)
        checkpoint_path = os.path.join(checkpoint_dir, "insight_checkpoints.db")
        self.engine_name = "insight"
        self.checkpoint_path = checkpoint_path
        self._active_run_id = None
        self._active_thread_id = None
        self._checkpoint_conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
        self.checkpointer = SqliteSaver(self._checkpoint_conn)

        # 构建图
        self.graph = self._build_graph()

        logger.info(f"LangGraph InsightEngine已初始化")
        logger.info(f"Checkpoint路径: {checkpoint_path}")

    @staticmethod
    def _calculate_recursion_limit(max_reflections: Any, max_paragraphs: Any) -> int:
        """Return a conservative LangGraph recursion limit for paragraph loops."""
        try:
            reflections = max(0, int(max_reflections))
        except (TypeError, ValueError):
            reflections = 2
        try:
            paragraphs = max(1, int(max_paragraphs))
        except (TypeError, ValueError):
            paragraphs = 5

        return max(200, (2 * reflections + 8) * paragraphs + 50)

    def _terminal_error_update(self, state: InsightGraphState, error: str) -> Dict:
        """Record an error and force the current paragraph loop to converge."""
        update = add_error(state, error)
        try:
            update["current_reflection_count"] = max(
                int(state.get("current_reflection_count", 0)),
                int(state.get("max_reflections", 0)),
            )
        except (TypeError, ValueError):
            update["current_reflection_count"] = state.get("current_reflection_count", 0)

        idx = state.get("current_paragraph_index", 0)
        paragraphs = state.get("paragraphs") or []
        has_summary = bool(state.get("current_summary"))
        if isinstance(idx, int) and 0 <= idx < len(paragraphs):
            has_summary = has_summary or bool(paragraphs[idx].get("latest_summary"))
            if not has_summary:
                fallback_summary = (
                    f"本段研究未能完成自动总结，已记录错误并跳过本段反思。\n\n"
                    f"错误信息: {error}"
                )
                updated_paragraphs = paragraphs.copy()
                updated_paragraphs[idx] = {
                    **updated_paragraphs[idx],
                    "latest_summary": fallback_summary,
                }
                update["paragraphs"] = updated_paragraphs
                update["current_summary"] = fallback_summary

        message = f"段落{idx + 1 if isinstance(idx, int) else ''}发生错误，停止本段反思并继续后续流程"
        update["messages"] = update.get("messages", []) + [message]
        return update

    def _traced_node(self, node_name: str, handler):
        """Wrap a LangGraph node with best-effort runtime event tracing."""
        def _wrapped(state):
            run_id = getattr(self, "_active_run_id", None)
            thread_id = getattr(self, "_active_thread_id", None)
            try:
                update = handler(state)
            except Exception as exc:
                if run_id:
                    record_event(
                        engine=self.engine_name,
                        run_id=run_id,
                        thread_id=thread_id,
                        event_type="node_failed",
                        node=node_name,
                        status="error",
                        message=str(exc),
                        payload=build_langgraph_payload(node_name, state, {"errors": [str(exc)]}),
                    )
                raise

            if run_id:
                errors = (update or {}).get("errors") if isinstance(update, dict) else None
                record_event(
                    engine=self.engine_name,
                    run_id=run_id,
                    thread_id=thread_id,
                    event_type="node_failed" if errors else "node_completed",
                    node=node_name,
                    status="error" if errors else "ok",
                    message=(errors[-1] if isinstance(errors, list) and errors else None),
                    payload=build_langgraph_payload(node_name, state, update),
                )
            return update

        return _wrapped

    def _build_graph(self) -> StateGraph:
        """
        构建LangGraph执行图

        图结构:
        START → generate_structure → paragraph_router
          → search_paragraph → summarize_paragraph → reflection_router
            → reflect_paragraph → update_summary → reflection_router
          → paragraph_router → format_report → END
        """
        # 创建StateGraph
        workflow = StateGraph(InsightGraphState)

        # 添加节点
        workflow.add_node("generate_structure", self._traced_node("generate_structure", self._generate_structure_node))
        workflow.add_node("search_paragraph", self._traced_node("search_paragraph", self._search_paragraph_node))
        workflow.add_node("summarize_paragraph", self._traced_node("summarize_paragraph", self._summarize_paragraph_node))
        workflow.add_node("reflect_paragraph", self._traced_node("reflect_paragraph", self._reflect_paragraph_node))
        workflow.add_node("update_summary", self._traced_node("update_summary", self._update_summary_node))
        workflow.add_node("advance_paragraph", self._traced_node("advance_paragraph", self._advance_paragraph_node))
        workflow.add_node("format_report", self._traced_node("format_report", self._format_report_node))

        # 设置入口点
        workflow.set_entry_point("generate_structure")

        # 添加边
        workflow.add_edge("generate_structure", "search_paragraph")
        workflow.add_edge("search_paragraph", "summarize_paragraph")
        workflow.add_edge("summarize_paragraph", "reflect_paragraph")

        # 条件路由: 反思循环
        workflow.add_conditional_edges(
            "reflect_paragraph",
            self._should_continue_reflection,
            {
                "continue": "update_summary",
                "next_paragraph": "advance_paragraph",
                "finish": "format_report"
            }
        )

        workflow.add_edge("update_summary", "reflect_paragraph")
        workflow.add_edge("advance_paragraph", "search_paragraph")
        workflow.add_edge("format_report", END)

        # 编译图 (带checkpoint)
        return workflow.compile(checkpointer=self.checkpointer)

    # ============ 节点实现 ============

    def _generate_structure_node(self, state: InsightGraphState) -> Dict:
        """
        生成报告结构节点

        Args:
            state: 当前状态

        Returns:
            状态更新字典
        """
        logger.info(f"\n[节点] 生成报告结构: {state['query']}")

        try:
            # 直接调用ReportStructureNode.run()获取结构列表(List[Dict[title,content]])
            # 不使用mutate_state(), 因为它依赖State数据类的add_paragraph方法
            self.structure_node_impl.query = state["query"]
            report_structure = self.structure_node_impl.run()
            max_paragraphs = state.get("max_paragraphs") or len(report_structure)
            if max_paragraphs > 0:
                report_structure = report_structure[:max_paragraphs]

            report_title = f"关于'{state['query']}'的深度研究报告"

            # 构建段落列表 (键名须与ParagraphState一致)
            paragraphs = []
            for order, p in enumerate(report_structure):
                paragraphs.append({
                    "title": p["title"],
                    "content": p["content"],
                    "order": order,
                    "latest_summary": "",
                    "search_history": [],
                    "reflection_count": 0,
                    "is_completed": False
                })

            if not paragraphs:
                raise ValueError("报告结构生成为空, 无可处理段落")

            logger.info(f"报告结构已生成: {len(paragraphs)}个段落")
            return {
                "report_title": report_title,
                "paragraphs": paragraphs,
                "messages": [f"生成报告结构: {len(paragraphs)}个段落"]
            }

        except Exception as e:
            logger.exception(f"生成报告结构失败: {e}")
            if is_recoverable_api_error(e):
                raise
            return add_error(state, f"生成报告结构失败: {str(e)}")

    def _search_paragraph_node(self, state: InsightGraphState) -> Dict:
        """
        搜索段落内容节点

        Args:
            state: 当前状态

        Returns:
            状态更新字典
        """
        idx = state["current_paragraph_index"]
        paragraphs = state["paragraphs"]

        if idx >= len(paragraphs):
            return {"messages": ["所有段落已处理完成"]}

        paragraph = paragraphs[idx]
        logger.info(f"\n[节点] 搜索段落 {idx + 1}/{len(paragraphs)}: {paragraph['title']}")

        try:
            # 生成搜索查询
            search_input = {
                "title": paragraph["title"],
                "content": paragraph["content"]
            }
            search_output = self.first_search_node_impl.run(search_input)

            search_query = search_output["search_query"]
            search_tool = search_output.get("search_tool", "search_topic_globally")

            logger.info(f"搜索查询: {search_query}")
            logger.info(f"使用工具: {search_tool}")

            # 执行搜索 (复用现有execute_search_tool逻辑)
            search_response = self._execute_search_tool(search_tool, search_query, {})

            # 转换结果
            search_results = self._convert_search_results(search_response)

            logger.info(f"找到 {len(search_results)} 个结果")

            return {
                "current_search_query": search_query,
                "current_search_tool": search_tool,
                "current_search_results": search_results,
                "messages": [f"段落{idx+1}搜索完成: {len(search_results)}个结果"]
            }

        except Exception as e:
            logger.exception(f"搜索段落失败: {e}")
            if is_recoverable_api_error(e):
                raise
            return add_error(state, f"搜索段落{idx+1}失败: {str(e)}")

    def _summarize_paragraph_node(self, state: InsightGraphState) -> Dict:
        """
        总结段落内容节点

        Args:
            state: 当前状态

        Returns:
            状态更新字典
        """
        idx = state["current_paragraph_index"]
        paragraph = state["paragraphs"][idx]

        logger.info(f"\n[节点] 总结段落 {idx + 1}: {paragraph['title']}")

        try:
            # 准备输入
            summary_input = {
                "title": paragraph["title"],
                "content": paragraph["content"],
                "search_query": state["current_search_query"],
                "search_results": format_search_results_for_prompt(
                    state["current_search_results"],
                    self.config.MAX_CONTENT_LENGTH
                )
            }

            # 生成总结
            summary = self.first_summary_node_impl.run(summary_input)

            # 更新段落
            paragraphs = state["paragraphs"].copy()
            paragraphs[idx] = {
                **paragraphs[idx],
                "latest_summary": summary,
                "search_history": paragraphs[idx].get("search_history", []) + [{
                    "query": state["current_search_query"],
                    "tool_name": state["current_search_tool"],
                    "results": state["current_search_results"],
                    "timestamp": datetime.now().isoformat()
                }]
            }

            logger.info(f"段落{idx+1}总结完成")

            return {
                "paragraphs": paragraphs,
                "current_summary": summary,
                "current_reflection_count": 0,  # 重置反思计数
                "messages": [f"段落{idx+1}初始总结完成"]
            }

        except Exception as e:
            logger.exception(f"总结段落失败: {e}")
            if is_recoverable_api_error(e):
                raise
            return add_error(state, f"总结段落{idx+1}失败: {str(e)}")

    def _reflect_paragraph_node(self, state: InsightGraphState) -> Dict:
        """
        反思段落节点

        Args:
            state: 当前状态

        Returns:
            状态更新字典
        """
        idx = state["current_paragraph_index"]
        paragraph = state["paragraphs"][idx]
        reflection_count = state["current_reflection_count"]

        logger.info(f"\n[节点] 反思段落 {idx + 1} (第{reflection_count + 1}次)")

        try:
            # 生成反思查询
            reflection_input = {
                "title": paragraph["title"],
                "content": paragraph["content"],
                "paragraph_latest_state": paragraph["latest_summary"]
            }

            reflection_output = self.reflection_node_impl.run(reflection_input)
            search_query = reflection_output["search_query"]
            search_tool = reflection_output.get("search_tool", "search_topic_globally")

            logger.info(f"反思查询: {search_query}")

            # 执行反思搜索
            search_response = self._execute_search_tool(search_tool, search_query, {})
            search_results = self._convert_search_results(search_response)

            logger.info(f"反思搜索找到 {len(search_results)} 个结果")

            return {
                "current_search_query": search_query,
                "current_search_tool": search_tool,
                "current_search_results": search_results,
                "messages": [f"段落{idx+1}反思{reflection_count+1}完成"]
            }

        except Exception as e:
            logger.exception(f"反思段落失败: {e}")
            if is_recoverable_api_error(e):
                raise
            return self._terminal_error_update(state, f"反思段落{idx+1}失败: {str(e)}")

    def _update_summary_node(self, state: InsightGraphState) -> Dict:
        """
        更新总结节点

        Args:
            state: 当前状态

        Returns:
            状态更新字典
        """
        idx = state["current_paragraph_index"]
        paragraph = state["paragraphs"][idx]

        logger.info(f"\n[节点] 更新段落 {idx + 1} 总结")

        try:
            # 准备输入
            reflection_summary_input = {
                "title": paragraph["title"],
                "content": paragraph["content"],
                "search_query": state["current_search_query"],
                "search_results": format_search_results_for_prompt(
                    state["current_search_results"],
                    self.config.MAX_CONTENT_LENGTH
                ),
                "paragraph_latest_state": paragraph["latest_summary"]
            }

            # 生成更新后的总结
            updated_summary = self.reflection_summary_node_impl.run(reflection_summary_input)

            # 更新段落
            paragraphs = state["paragraphs"].copy()
            paragraphs[idx] = {
                **paragraphs[idx],
                "latest_summary": updated_summary,
                "reflection_count": paragraphs[idx].get("reflection_count", 0) + 1,
                "search_history": paragraphs[idx].get("search_history", []) + [{
                    "query": state["current_search_query"],
                    "tool_name": state["current_search_tool"],
                    "results": state["current_search_results"],
                    "timestamp": datetime.now().isoformat()
                }]
            }

            logger.info(f"段落{idx+1}总结已更新")

            return {
                "paragraphs": paragraphs,
                "current_summary": updated_summary,
                "current_reflection_count": state["current_reflection_count"] + 1,
                "messages": [f"段落{idx+1}反思总结更新完成"]
            }

        except Exception as e:
            logger.exception(f"更新总结失败: {e}")
            if is_recoverable_api_error(e):
                raise
            return self._terminal_error_update(state, f"更新段落{idx+1}总结失败: {str(e)}")

    def _advance_paragraph_node(self, state: InsightGraphState) -> Dict:
        """
        推进到下一个段落节点

        将当前段落标记为完成, 段落索引+1, 并重置反思计数,
        以便对下一个段落重新开始 search -> summarize -> reflect 循环。
        此节点是反思循环能够正确收敛的关键: 没有它, current_paragraph_index
        永远停在0, 图会无限循环直到撞上 recursion limit。

        Args:
            state: 当前状态

        Returns:
            状态更新字典
        """
        idx = state["current_paragraph_index"]

        # 标记当前段落完成
        paragraphs = state["paragraphs"].copy()
        if 0 <= idx < len(paragraphs):
            paragraphs[idx] = {**paragraphs[idx], "is_completed": True}

        next_idx = idx + 1
        logger.info(f"\n[节点] 推进段落: {idx + 1} -> {next_idx + 1}/{len(paragraphs)}")

        return {
            "paragraphs": paragraphs,
            "current_paragraph_index": next_idx,
            "current_reflection_count": 0,  # 为下一段落重置反思计数
            "messages": [f"段落{idx+1}完成, 推进到段落{next_idx+1}"]
        }

    def _format_report_node(self, state: InsightGraphState) -> Dict:
        """
        格式化最终报告节点

        Args:
            state: 当前状态

        Returns:
            状态更新字典
        """
        logger.info(f"\n[节点] 格式化最终报告")

        try:
            # 准备报告数据
            report_data = []
            paragraph_limit = state.get("max_paragraphs") or len(state["paragraphs"])
            for p in state["paragraphs"][:paragraph_limit]:
                report_data.append({
                    "title": p["title"],
                    "paragraph_latest_state": p["latest_summary"]
                })

            # 格式化报告
            final_report = self.report_formatting_node_impl.run(report_data)

            logger.info("最终报告生成完成")

            return {
                "final_report": final_report,
                "is_completed": True,
                "messages": ["最终报告生成完成"]
            }

        except Exception as e:
            logger.exception(f"格式化报告失败: {e}")
            if is_recoverable_api_error(e):
                raise
            # 使用备用方法
            final_report = self.report_formatting_node_impl.format_report_manually(
                report_data, state["report_title"]
            )
            return {
                "final_report": final_report,
                "is_completed": True,
                "messages": ["最终报告生成完成(备用方法)"]
            }

    # ============ 条件路由 ============

    def _should_continue_reflection(self, state: InsightGraphState) -> Literal["continue", "next_paragraph", "finish"]:
        """
        判断是否继续反思

        Args:
            state: 当前状态

        Returns:
            路由决策: "continue" | "next_paragraph" | "finish"
        """
        idx = state["current_paragraph_index"]
        reflection_count = state["current_reflection_count"]
        max_reflections = state["max_reflections"]
        total_paragraphs = len(state["paragraphs"])
        paragraph_limit = state.get("max_paragraphs") or total_paragraphs
        processing_limit = min(total_paragraphs, paragraph_limit)
        if reflection_count >= max_reflections and idx + 1 >= processing_limit:
            logger.info("Configured paragraph limit reached; formatting final report")
            return "finish"

        # 检查是否达到最大反思次数
        if reflection_count >= max_reflections:
            # 标记当前段落完成
            logger.info(f"段落{idx+1}已完成所有反思")

            # 移动到下一个段落
            if idx + 1 < total_paragraphs:
                logger.info(f"移动到下一个段落: {idx + 2}/{total_paragraphs}")
                return "next_paragraph"
            else:
                logger.info("所有段落已完成，准备生成最终报告")
                return "finish"
        else:
            # 继续反思
            logger.info(f"继续反思段落{idx+1}: {reflection_count + 1}/{max_reflections}")
            return "continue"

    # ============ 辅助方法 ============

    def _execute_search_tool(self, tool_name: str, query: str, kwargs: Dict) -> Any:
        """
        执行搜索工具 (复用原有逻辑)

        Args:
            tool_name: 工具名称
            query: 搜索查询
            kwargs: 额外参数

        Returns:
            搜索响应
        """
        logger.info(f"执行搜索工具: {tool_name}")

        # 关键词优化
        if tool_name != "search_hot_content":
            optimized_response = keyword_optimizer.optimize_keywords(
                original_query=query,
                context=f"使用{tool_name}工具进行查询"
            )
            keywords = optimized_response.optimized_keywords
            logger.info(f"优化后关键词: {keywords}")
        else:
            keywords = [query]

        # 执行搜索
        all_results = []
        for keyword in keywords:
            try:
                if tool_name == "search_hot_content":
                    response = self.search_agency.search_hot_content(
                        time_period=kwargs.get("time_period", "week"),
                        limit=self.config.DEFAULT_SEARCH_HOT_CONTENT_LIMIT
                    )
                elif tool_name == "search_topic_globally":
                    response = self.search_agency.search_topic_globally(
                        topic=keyword,
                        limit_per_table=self.config.DEFAULT_SEARCH_TOPIC_GLOBALLY_LIMIT_PER_TABLE
                    )
                elif tool_name == "get_comments_for_topic":
                    response = self.search_agency.get_comments_for_topic(
                        topic=keyword,
                        limit=self.config.DEFAULT_GET_COMMENTS_FOR_TOPIC_LIMIT
                    )
                else:
                    response = self.search_agency.search_topic_globally(
                        topic=keyword,
                        limit_per_table=self.config.DEFAULT_SEARCH_TOPIC_GLOBALLY_LIMIT_PER_TABLE
                    )

                if response.results:
                    all_results.extend(response.results)

            except Exception as e:
                logger.error(f"搜索'{keyword}'失败: {e}")
                continue

        # 去重
        unique_results = self._deduplicate_results(all_results)

        # 构建响应
        from .tools import DBResponse
        return DBResponse(
            tool_name=tool_name,
            parameters={"query": query, **kwargs},
            results=unique_results,
            results_count=len(unique_results)
        )

    def _deduplicate_results(self, results: List) -> List:
        """去重搜索结果"""
        seen = set()
        unique = []
        for r in results:
            identifier = r.url if r.url else r.title_or_content[:100]
            if identifier not in seen:
                seen.add(identifier)
                unique.append(r)
        return unique

    def _convert_search_results(self, search_response) -> List[Dict]:
        """转换搜索结果为字典格式"""
        results = []
        if search_response and search_response.results:
            max_results = self.config.MAX_SEARCH_RESULTS_FOR_LLM or len(search_response.results)
            for result in search_response.results[:max_results]:
                results.append({
                    "title": result.title_or_content,
                    "url": result.url or "",
                    "content": result.title_or_content,
                    "score": result.hotness_score,
                    "platform": result.platform,
                    "content_type": result.content_type,
                    "author": result.author_nickname,
                    "published_date": result.publish_time.isoformat() if result.publish_time else None
                })
        return results

    # ============ 公共接口 ============

    def research(
        self,
        query: str,
        thread_id: Optional[str] = None,
        save_report: bool = True
    ) -> str:
        """
        执行研究 (支持checkpoint恢复)

        Args:
            query: 研究查询
            thread_id: 线程ID (用于checkpoint恢复)
            save_report: 是否保存报告

        Returns:
            最终报告内容
        """
        logger.info(f"\n{'=' * 60}")
        logger.info(f"开始LangGraph研究: {query}")
        logger.info(f"{'=' * 60}")

        # 生成thread_id
        if thread_id is None:
            thread_id = f"insight_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 结构节点由 LLM 决定段落数(常 4-7 段), 每段约需 (2*反思次数+4) 步;
        # LangGraph 默认 recursion_limit=25 在多段落时会中途抛 RecursionError, 这里给足余量。
        recursion_limit = self._calculate_recursion_limit(
            self.config.MAX_REFLECTIONS,
            self.config.MAX_PARAGRAPHS,
        )
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
        runtime_run = start_run(
            self.engine_name,
            query,
            thread_id,
            checkpoint_path=self.checkpoint_path,
        )
        self._active_run_id = runtime_run.get("run_id")
        self._active_thread_id = thread_id

        try:
            # 创建初始状态
            initial_state = create_initial_state(
                query=query,
                max_reflections=self.config.MAX_REFLECTIONS,
                max_paragraphs=self.config.MAX_PARAGRAPHS
            )

            # 执行图 (自动checkpoint)
            # stream_mode="values": 每步返回完整累积状态, 便于提取final_report
            final_state = None
            for state in self.graph.stream(initial_state, config, stream_mode="values"):
                # 实时输出进度
                if "messages" in state:
                    for msg in state.get("messages", []):
                        logger.info(f"进度: {msg}")
                final_state = state

            # 提取最终报告
            if final_state and "final_report" in final_state:
                final_report = final_state["final_report"]
            else:
                raise ValueError("未生成最终报告")

            # 保存报告
            report_path = None
            if save_report:
                report_path = self._save_report(query, final_report, thread_id)
            finish_run(self._active_run_id, "completed", final_report_path=report_path)

            logger.info("LangGraph研究完成！")
            return final_report

        except Exception as e:
            logger.exception(f"研究过程中发生错误: {e}")
            finish_run(self._active_run_id, "failed", error_summary=str(e))
            raise e
        finally:
            self._active_run_id = None
            self._active_thread_id = None

    def resume_research(self, thread_id: str) -> str:
        """
        从checkpoint恢复研究

        Args:
            thread_id: 线程ID

        Returns:
            最终报告内容
        """
        logger.info(f"从checkpoint恢复研究: {thread_id}")

        recursion_limit = self._calculate_recursion_limit(
            self.config.MAX_REFLECTIONS,
            self.config.MAX_PARAGRAPHS,
        )
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
        runtime_run = start_run(
            self.engine_name,
            f"resume:{thread_id}",
            thread_id,
            checkpoint_path=self.checkpoint_path,
        )
        self._active_run_id = runtime_run.get("run_id")
        self._active_thread_id = thread_id

        try:
            # 获取最新checkpoint
            checkpoint = self.checkpointer.get(config)
            if checkpoint is None:
                raise ValueError(f"未找到thread_id={thread_id}的checkpoint")

            logger.info(f"找到checkpoint，继续执行...")

            # 继续执行
            final_state = None
            for state in self.graph.stream(None, config, stream_mode="values"):
                if "messages" in state:
                    for msg in state.get("messages", []):
                        logger.info(f"进度: {msg}")
                final_state = state

            if final_state and "final_report" in final_state:
                finish_run(self._active_run_id, "completed")
                return final_state["final_report"]
            else:
                raise ValueError("未生成最终报告")

        except Exception as e:
            logger.exception(f"恢复研究失败: {e}")
            finish_run(self._active_run_id, "failed", error_summary=str(e))
            raise e
        finally:
            self._active_run_id = None
            self._active_thread_id = None

    def _save_report(self, query: str, report_content: str, thread_id: str):
        """保存报告到文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        query_safe = "".join(c for c in query if c.isalnum() or c in (" ", "-", "_")).rstrip()
        query_safe = query_safe.replace(" ", "_")[:30]

        filename = f"langgraph_report_{query_safe}_{timestamp}.md"
        filepath = os.path.join(self.config.OUTPUT_DIR, filename)

        os.makedirs(self.config.OUTPUT_DIR, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# {query}\n\n")
            f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"**Thread ID**: {thread_id}\n\n")
            f.write("---\n\n")
            f.write(report_content)

        logger.info(f"Report saved to: {filepath}")
        return filepath

        logger.info(f"报告已保存到: {filepath}")


def create_langgraph_agent(config_file: Optional[str] = None) -> LangGraphInsightAgent:
    """
    创建LangGraph Agent实例

    Args:
        config_file: 配置文件路径

    Returns:
        LangGraphInsightAgent实例
    """
    config = Settings()
    return LangGraphInsightAgent(config)
