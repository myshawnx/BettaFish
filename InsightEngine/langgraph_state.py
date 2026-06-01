"""
LangGraph状态定义 - 使用TypedDict和Reducer模式
支持checkpoint和状态回溯
"""

from typing import TypedDict, Annotated, List, Dict, Any, Optional
from datetime import datetime
from operator import add
from dataclasses import dataclass, field


# ============ 数据类定义 ============

@dataclass
class SearchResult:
    """单个搜索结果"""
    query: str
    tool_name: str
    results: List[Dict[str, Any]]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ParagraphState:
    """段落状态"""
    title: str
    content: str
    order: int
    latest_summary: str = ""
    search_history: List[SearchResult] = field(default_factory=list)
    reflection_count: int = 0
    is_completed: bool = False


# ============ LangGraph状态 (TypedDict) ============

class InsightGraphState(TypedDict):
    """
    LangGraph主状态 - 使用TypedDict确保类型安全

    Reducer模式说明:
    - messages: 使用add reducer累积消息历史
    - paragraphs: 使用add reducer累积段落
    - errors: 使用add reducer累积错误
    """

    # 输入
    query: str                                    # 用户查询

    # 报告结构
    report_title: str                             # 报告标题
    # 段落列表: 使用默认覆盖语义(last-write-wins), 不能用add reducer!
    # 节点会返回完整的paragraphs列表以原地更新某个段落(如latest_summary),
    # add reducer会把整个列表重复追加导致段落翻倍, 因此必须用覆盖语义.
    paragraphs: List[Dict]

    # 当前处理状态
    current_paragraph_index: int                  # 当前处理的段落索引
    current_reflection_count: int                 # 当前反思次数

    # 搜索和总结
    current_search_query: str                     # 当前搜索查询
    current_search_tool: str                      # 当前使用的工具
    current_search_results: List[Dict]            # 当前搜索结果
    current_summary: str                          # 当前总结

    # 配置
    max_reflections: int                          # 最大反思次数
    max_paragraphs: int                           # 最大段落数

    # 最终输出
    final_report: str                             # 最终报告

    # 元数据
    messages: Annotated[List[str], add]          # 消息历史 (使用add reducer)
    errors: Annotated[List[str], add]            # 错误列表 (使用add reducer)
    created_at: str                               # 创建时间
    updated_at: str                               # 更新时间
    is_completed: bool                            # 是否完成


# ============ 状态初始化函数 ============

def create_initial_state(query: str, max_reflections: int = 3, max_paragraphs: int = 6) -> InsightGraphState:
    """
    创建初始状态

    Args:
        query: 用户查询
        max_reflections: 最大反思次数
        max_paragraphs: 最大段落数

    Returns:
        初始化的状态字典
    """
    now = datetime.now().isoformat()

    return InsightGraphState(
        # 输入
        query=query,

        # 报告结构
        report_title="",
        paragraphs=[],

        # 当前处理状态
        current_paragraph_index=0,
        current_reflection_count=0,

        # 搜索和总结
        current_search_query="",
        current_search_tool="",
        current_search_results=[],
        current_summary="",

        # 配置
        max_reflections=max_reflections,
        max_paragraphs=max_paragraphs,

        # 最终输出
        final_report="",

        # 元数据
        messages=[],
        errors=[],
        created_at=now,
        updated_at=now,
        is_completed=False
    )


# ============ 状态转换辅助函数 ============

def add_paragraph(state: InsightGraphState, title: str, content: str) -> Dict:
    """
    添加段落到状态 (返回更新字典)

    Args:
        state: 当前状态
        title: 段落标题
        content: 段落内容

    Returns:
        状态更新字典
    """
    new_paragraph = {
        "title": title,
        "content": content,
        "order": len(state["paragraphs"]),
        "latest_summary": "",
        "search_history": [],
        "reflection_count": 0,
        "is_completed": False
    }

    return {
        "paragraphs": [new_paragraph],  # add reducer会自动累积
        "updated_at": datetime.now().isoformat()
    }


def update_paragraph_summary(state: InsightGraphState, paragraph_index: int, summary: str) -> Dict:
    """
    更新段落总结

    Args:
        state: 当前状态
        paragraph_index: 段落索引
        summary: 新的总结内容

    Returns:
        状态更新字典
    """
    # 创建段落副本并更新
    paragraphs = state["paragraphs"].copy()
    if 0 <= paragraph_index < len(paragraphs):
        paragraphs[paragraph_index] = {
            **paragraphs[paragraph_index],
            "latest_summary": summary,
            "updated_at": datetime.now().isoformat()
        }

    return {
        "paragraphs": paragraphs,
        "current_summary": summary,
        "updated_at": datetime.now().isoformat()
    }


def add_search_to_paragraph(
    state: InsightGraphState,
    paragraph_index: int,
    search_result: SearchResult
) -> Dict:
    """
    添加搜索记录到段落

    Args:
        state: 当前状态
        paragraph_index: 段落索引
        search_result: 搜索结果

    Returns:
        状态更新字典
    """
    paragraphs = state["paragraphs"].copy()
    if 0 <= paragraph_index < len(paragraphs):
        paragraph = paragraphs[paragraph_index].copy()
        search_history = paragraph.get("search_history", []).copy()
        search_history.append({
            "query": search_result.query,
            "tool_name": search_result.tool_name,
            "results": search_result.results,
            "timestamp": search_result.timestamp
        })
        paragraph["search_history"] = search_history
        paragraphs[paragraph_index] = paragraph

    return {
        "paragraphs": paragraphs,
        "updated_at": datetime.now().isoformat()
    }


def increment_reflection(state: InsightGraphState, paragraph_index: int) -> Dict:
    """
    增加反思计数

    Args:
        state: 当前状态
        paragraph_index: 段落索引

    Returns:
        状态更新字典
    """
    paragraphs = state["paragraphs"].copy()
    if 0 <= paragraph_index < len(paragraphs):
        paragraph = paragraphs[paragraph_index].copy()
        paragraph["reflection_count"] = paragraph.get("reflection_count", 0) + 1
        paragraphs[paragraph_index] = paragraph

    return {
        "paragraphs": paragraphs,
        "current_reflection_count": state["current_reflection_count"] + 1,
        "updated_at": datetime.now().isoformat()
    }


def mark_paragraph_completed(state: InsightGraphState, paragraph_index: int) -> Dict:
    """
    标记段落完成

    Args:
        state: 当前状态
        paragraph_index: 段落索引

    Returns:
        状态更新字典
    """
    paragraphs = state["paragraphs"].copy()
    if 0 <= paragraph_index < len(paragraphs):
        paragraph = paragraphs[paragraph_index].copy()
        paragraph["is_completed"] = True
        paragraphs[paragraph_index] = paragraph

    return {
        "paragraphs": paragraphs,
        "updated_at": datetime.now().isoformat()
    }


def add_message(state: InsightGraphState, message: str) -> Dict:
    """
    添加消息到历史

    Args:
        state: 当前状态
        message: 消息内容

    Returns:
        状态更新字典
    """
    return {
        "messages": [f"[{datetime.now().isoformat()}] {message}"],  # add reducer会累积
        "updated_at": datetime.now().isoformat()
    }


def add_error(state: InsightGraphState, error: str) -> Dict:
    """
    添加错误到列表

    Args:
        state: 当前状态
        error: 错误信息

    Returns:
        状态更新字典
    """
    return {
        "errors": [f"[{datetime.now().isoformat()}] {error}"],  # add reducer会累积
        "updated_at": datetime.now().isoformat()
    }
