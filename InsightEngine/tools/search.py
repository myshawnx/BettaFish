"""
专为 AI Agent 设计的本地舆情数据库查询工具集 (MediaCrawlerDB)

版本: 3.0
最后更新: 2025-08-23

此脚本将复杂的本地MySQL数据库查询功能封装成一系列目标明确、参数清晰的独立工具，
专为AI Agent调用而设计。Agent只需根据任务意图（如搜索热点、全局搜索话题、
按时间范围分析、获取评论）选择合适的工具，无需编写复杂的SQL语句。

V3.0 核心更新:
- 智能热度计算: `search_hot_content`不再需要`sort_by`参数，改为内部使用统一的加权热度算法，
  综合点赞、评论、分享、观看等数据计算热度分值，使结果更智能、更符合综合热度。
- 新增平台精搜工具: 新增 `search_topic_on_platform` 工具，作为特例，
  允许Agent在特定平台（B站、微博等七大平台）上对某一话题进行精确搜索，并支持时间筛选。
- 结构优化: 调整了数据结构与函数文档，以适应新功能。

主要工具:
- search_hot_content: 查找指定时间范围内的综合热度最高的内容。
- search_topic_globally: 在整个数据库中全局搜索与特定话题相关的所有内容和评论。
- search_topic_by_date: 在指定的历史日期范围内搜索与特定话题相关的内容。
- get_comments_for_topic: 专门提取公众对于某一特定话题的评论数据。
- search_topic_on_platform: 在指定的单个社交媒体平台上搜索特定话题。
"""

import os
import json
from loguru import logger
import asyncio
from typing import List, Dict, Any, Optional, Literal
from dataclasses import dataclass, field
from ..utils.db import fetch_all
from datetime import datetime, timedelta, date
from InsightEngine.utils.config import settings

# --- 1. 数据结构定义 ---

@dataclass
class QueryResult:
    """统一的数据库查询结果数据类"""
    platform: str
    content_type: str
    title_or_content: str
    author_nickname: Optional[str] = None
    url: Optional[str] = None
    publish_time: Optional[datetime] = None
    engagement: Dict[str, int] = field(default_factory=dict)
    source_keyword: Optional[str] = None
    hotness_score: float = 0.0
    source_table: str = ""

@dataclass
class DBResponse:
    """封装工具的完整返回结果"""
    tool_name: str
    parameters: Dict[str, Any]
    results: List[QueryResult] = field(default_factory=list)
    results_count: int = 0
    error_message: Optional[str] = None

# --- 2. 核心客户端与专用工具集 ---

class MediaCrawlerDB:
    """包含多种专用舆情数据库查询工具的客户端"""
    # 权重定义
    W_LIKE = 1.0
    W_COMMENT = 5.0
    W_SHARE = 10.0  # 分享/转发/收藏/投币等高价值互动
    W_VIEW = 0.1
    W_DANMAKU = 0.5

    TABLE_COLUMNS = {
        'bilibili_video': {'id', 'title', 'desc', 'source_keyword', 'create_time', 'nickname', 'video_url', 'liked_count', 'video_comment', 'video_share_count', 'video_favorite_count', 'video_coin_count', 'video_danmaku', 'video_play_count'},
        'bilibili_video_comment': {'id', 'content', 'nickname', 'create_time', 'like_count'},
        'douyin_aweme': {'id', 'title', 'desc', 'source_keyword', 'create_time', 'nickname', 'aweme_url', 'liked_count', 'comment_count', 'share_count', 'collected_count'},
        'douyin_aweme_comment': {'id', 'content', 'nickname', 'create_time', 'like_count'},
        'kuaishou_video': {'id', 'title', 'desc', 'source_keyword', 'create_time', 'nickname', 'video_url', 'liked_count', 'viewd_count'},
        'kuaishou_video_comment': {'id', 'content', 'nickname', 'create_time', 'sub_comment_count'},
        'weibo_note': {'id', 'content', 'source_keyword', 'create_time', 'create_date_time', 'nickname', 'note_url', 'liked_count', 'comments_count', 'shared_count'},
        'weibo_note_comment': {'id', 'content', 'nickname', 'create_time', 'create_date_time', 'comment_like_count', 'sub_comment_count'},
        'xhs_note': {'id', 'title', 'desc', 'tag_list', 'source_keyword', 'time', 'nickname', 'note_url', 'liked_count', 'collected_count', 'comment_count', 'share_count'},
        'xhs_note_comment': {'id', 'content', 'nickname', 'create_time', 'like_count', 'sub_comment_count'},
        'zhihu_content': {'id', 'title', 'desc', 'content_text', 'source_keyword', 'created_time', 'user_nickname', 'content_url', 'voteup_count', 'comment_count'},
        'zhihu_comment': {'id', 'content', 'user_nickname', 'publish_time', 'like_count', 'sub_comment_count'},
        'tieba_note': {'id', 'title', 'desc', 'source_keyword', 'publish_time', 'user_nickname', 'note_url', 'total_replay_num'},
        'tieba_comment': {'id', 'content', 'user_nickname', 'publish_time', 'sub_comment_count', 'note_url'},
        'daily_news': {'id', 'news_id', 'source_platform', 'title', 'url', 'description', 'extra_info', 'crawl_date', 'rank_position', 'add_ts', 'last_modify_ts'},
    }

    SEARCH_CONFIGS = {
        'bilibili_video': {'fields': ['title', 'desc', 'source_keyword'], 'type': 'video', 'time_col': 'create_time', 'time_type': 'sec'},
        'bilibili_video_comment': {'fields': ['content'], 'type': 'comment', 'time_col': 'create_time', 'time_type': 'sec'},
        'douyin_aweme': {'fields': ['title', 'desc', 'source_keyword'], 'type': 'video', 'time_col': 'create_time', 'time_type': 'ms'},
        'douyin_aweme_comment': {'fields': ['content'], 'type': 'comment', 'time_col': 'create_time', 'time_type': 'sec'},
        'kuaishou_video': {'fields': ['title', 'desc', 'source_keyword'], 'type': 'video', 'time_col': 'create_time', 'time_type': 'ms'},
        'kuaishou_video_comment': {'fields': ['content'], 'type': 'comment', 'time_col': 'create_time', 'time_type': 'sec'},
        'weibo_note': {'fields': ['content', 'source_keyword'], 'type': 'note', 'time_col': 'create_date_time', 'time_type': 'str'},
        'weibo_note_comment': {'fields': ['content'], 'type': 'comment', 'time_col': 'create_date_time', 'time_type': 'str'},
        'xhs_note': {'fields': ['title', 'desc', 'tag_list', 'source_keyword'], 'type': 'note', 'time_col': 'time', 'time_type': 'ms'},
        'xhs_note_comment': {'fields': ['content'], 'type': 'comment', 'time_col': 'create_time', 'time_type': 'sec'},
        'zhihu_content': {'fields': ['title', 'desc', 'content_text', 'source_keyword'], 'type': 'content', 'time_col': 'created_time', 'time_type': 'sec_str'},
        'zhihu_comment': {'fields': ['content'], 'type': 'comment', 'time_col': 'publish_time', 'time_type': 'sec_str'},
        'tieba_note': {'fields': ['title', 'desc', 'source_keyword'], 'type': 'note', 'time_col': 'publish_time', 'time_type': 'str'},
        'tieba_comment': {'fields': ['content'], 'type': 'comment', 'time_col': 'publish_time', 'time_type': 'str'},
        'daily_news': {'fields': ['title'], 'type': 'news', 'time_col': 'crawl_date', 'time_type': 'date'},
    }

    PLATFORM_CONFIGS = {
        'bilibili': ['bilibili_video', 'bilibili_video_comment'],
        'douyin': ['douyin_aweme', 'douyin_aweme_comment'],
        'kuaishou': ['kuaishou_video', 'kuaishou_video_comment'],
        'weibo': ['weibo_note', 'weibo_note_comment'],
        'xhs': ['xhs_note', 'xhs_note_comment'],
        'zhihu': ['zhihu_content', 'zhihu_comment'],
        'tieba': ['tieba_note', 'tieba_comment'],
    }

    HOT_CONTENT_CONFIGS = [
        {'table': 'bilibili_video', 'platform': 'bilibili', 'type': 'video', 'title': 'title', 'author': 'nickname', 'url': 'video_url', 'time_col': 'create_time', 'time_type': 'sec', 'metrics': [('liked_count', W_LIKE), ('video_comment', W_COMMENT), ('video_share_count', W_SHARE), ('video_favorite_count', W_SHARE), ('video_coin_count', W_SHARE), ('video_danmaku', W_DANMAKU), ('video_play_count', W_VIEW)]},
        {'table': 'douyin_aweme', 'platform': 'douyin', 'type': 'video', 'title': 'title', 'author': 'nickname', 'url': 'aweme_url', 'time_col': 'create_time', 'time_type': 'ms', 'metrics': [('liked_count', W_LIKE), ('comment_count', W_COMMENT), ('share_count', W_SHARE), ('collected_count', W_SHARE)]},
        {'table': 'weibo_note', 'platform': 'weibo', 'type': 'note', 'title': 'content', 'author': 'nickname', 'url': 'note_url', 'time_col': 'create_date_time', 'time_type': 'str', 'metrics': [('liked_count', W_LIKE), ('comments_count', W_COMMENT), ('shared_count', W_SHARE)]},
        {'table': 'xhs_note', 'platform': 'xhs', 'type': 'note', 'title': 'title', 'author': 'nickname', 'url': 'note_url', 'time_col': 'time', 'time_type': 'ms', 'metrics': [('liked_count', W_LIKE), ('comment_count', W_COMMENT), ('share_count', W_SHARE), ('collected_count', W_SHARE)]},
        {'table': 'kuaishou_video', 'platform': 'kuaishou', 'type': 'video', 'title': 'title', 'author': 'nickname', 'url': 'video_url', 'time_col': 'create_time', 'time_type': 'ms', 'metrics': [('liked_count', W_LIKE), ('viewd_count', W_VIEW)]},
        {'table': 'zhihu_content', 'platform': 'zhihu', 'type': 'content', 'title': 'title', 'author': 'user_nickname', 'url': 'content_url', 'time_col': 'created_time', 'time_type': 'sec_str', 'metrics': [('voteup_count', W_LIKE), ('comment_count', W_COMMENT)]},
    ]

    def __init__(self):
        """
        初始化客户端。
        """
        self._database_available: Optional[bool] = None
        self._last_error_message: Optional[str] = None
        
    def _execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        if self._database_available is False:
            self._last_error_message = self._last_error_message or "数据库不可用，已返回空结果。"
            return []
        try:
            # 获取或创建event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # 直接运行协程
            return loop.run_until_complete(fetch_all(query, params or {}))
        
        except Exception as e:
            message = str(e)
            self._last_error_message = f"数据库不可用或查询失败，已返回空结果: {message}"
            if self._is_connectivity_error(message):
                self._database_available = False
            logger.warning(self._last_error_message)
            return []

    @staticmethod
    def _is_connectivity_error(message: str) -> bool:
        lowered = message.lower()
        return any(
            token in lowered
            for token in [
                "connection refused",
                "connect call failed",
                "could not connect",
                "actively refused",
                "remote computer refused",
                "winerror 1225",
                "远程计算机拒绝",
            ]
        )

    def _empty_error(self, results: List[QueryResult]) -> Optional[str]:
        if results:
            return None
        if self._last_error_message:
            return self._last_error_message
        return None

    def _begin_tool_query(self) -> None:
        if self._database_available is not False:
            self._last_error_message = None

    @staticmethod
    def _to_datetime(ts: Any) -> Optional[datetime]:
        if not ts: return None
        try:
            if isinstance(ts, datetime): return ts
            if isinstance(ts, date): return datetime.combine(ts, datetime.min.time())
            if isinstance(ts, (int, float)) or str(ts).isdigit():
                val = float(ts)
                return datetime.fromtimestamp(val / 1000 if val > 1_000_000_000_000 else val)
            if isinstance(ts, str):
                return datetime.fromisoformat(ts.split('+')[0].strip())
        except (ValueError, TypeError): return None

    def _get_table_columns(self, table_name: str) -> List[str]:
        return sorted(self.TABLE_COLUMNS.get(table_name, set()))

    def _is_postgres(self) -> bool:
        return (settings.DB_DIALECT or "postgresql").lower() in {"postgresql", "postgres"}

    def _safe_limit(self, value: int, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(1, min(parsed, 1000))

    def _quote_table(self, table: str) -> str:
        if table not in self.TABLE_COLUMNS:
            raise ValueError(f"不允许查询的表: {table}")
        return f'"{table}"' if self._is_postgres() else f'`{table}`'

    def _quote_column(self, table: str, field: str) -> str:
        if field not in self.TABLE_COLUMNS.get(table, set()):
            raise ValueError(f"表 {table} 不允许查询字段: {field}")
        return f'"{field}"' if self._is_postgres() else f'`{field}`'

    def _text_expr(self, table: str, field: str) -> str:
        column = self._quote_column(table, field)
        return f"CAST({column} AS TEXT)" if self._is_postgres() else f"CAST({column} AS CHAR)"

    def _numeric_expr(self, table: str, field: str) -> str:
        column = self._quote_column(table, field)
        if self._is_postgres():
            return f"COALESCE(NULLIF(regexp_replace(CAST({column} AS TEXT), '[^0-9]', '', 'g'), '')::numeric, 0)"
        return f"COALESCE(CAST({column} AS DECIMAL(20, 2)), 0)"

    def _like_operator(self) -> str:
        return "ILIKE" if self._is_postgres() else "LIKE"

    def _build_search_clause(self, table: str, fields: List[str], params: Dict[str, Any], prefix: str, search_term: str) -> str:
        clauses = []
        for idx, field in enumerate(fields):
            pname = f"{prefix}_term_{idx}"
            clauses.append(f"{self._text_expr(table, field)} {self._like_operator()} :{pname}")
            params[pname] = search_term
        return " OR ".join(clauses)

    def _time_bounds(self, start_dt: datetime, end_dt: Optional[datetime], time_type: str) -> tuple[Any, Any]:
        end_dt = end_dt or (datetime.now() + timedelta(days=36500))
        if time_type == 'sec':
            return int(start_dt.timestamp()), int(end_dt.timestamp())
        if time_type in {'ms', 'ms_str'}:
            return int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)
        if time_type == 'sec_str':
            return str(int(start_dt.timestamp())), str(int(end_dt.timestamp()))
        if time_type == 'date':
            return start_dt.date(), end_dt.date()
        return start_dt.strftime('%Y-%m-%d'), end_dt.strftime('%Y-%m-%d')

    def _build_time_clause(
        self,
        table: str,
        config: Dict[str, Any],
        params: Dict[str, Any],
        prefix: str,
        start_dt: datetime,
        end_dt: Optional[datetime] = None,
    ) -> str:
        time_col = config.get('time_col')
        if not time_col:
            return ""
        time_type = config.get('time_type', 'str')
        start_value, end_value = self._time_bounds(start_dt, end_dt, time_type)
        params[f"{prefix}_start"] = start_value
        params[f"{prefix}_end"] = end_value
        expr = self._numeric_expr(table, time_col) if time_type in {'sec_str', 'ms_str'} else self._quote_column(table, time_col)
        return f"{expr} >= :{prefix}_start AND {expr} < :{prefix}_end"

    def _row_to_query_result(
        self,
        table: str,
        content_type: str,
        row: Dict[str, Any],
        platform: Optional[str] = None,
    ) -> QueryResult:
        content = row.get('title') or row.get('content') or row.get('desc') or row.get('content_text') or ''
        time_key = row.get('create_time') or row.get('time') or row.get('created_time') or row.get('publish_time') or row.get('create_date_time') or row.get('crawl_date')
        return QueryResult(
            platform=platform or row.get('source_platform') or table.split('_')[0],
            content_type=content_type,
            title_or_content=content,
            author_nickname=row.get('nickname') or row.get('user_nickname') or row.get('user_name'),
            url=row.get('video_url') or row.get('note_url') or row.get('content_url') or row.get('url') or row.get('aweme_url'),
            publish_time=self._to_datetime(time_key),
            engagement=self._extract_engagement(row),
            source_keyword=row.get('source_keyword') or row.get('source_platform'),
            source_table=table
        )

    def _extract_engagement(self, row: Dict[str, Any]) -> Dict[str, int]:
        """从数据行中提取并统一互动指标"""
        engagement = {}
        mapping = { 'likes': ['liked_count', 'like_count', 'voteup_count', 'comment_like_count'], 'comments': ['video_comment', 'comments_count', 'comment_count', 'total_replay_num', 'sub_comment_count'], 'shares': ['video_share_count', 'shared_count', 'share_count', 'total_forwards'], 'views': ['video_play_count', 'viewd_count'], 'favorites': ['video_favorite_count', 'collected_count'], 'coins': ['video_coin_count'], 'danmaku': ['video_danmaku'], }
        for key, potential_cols in mapping.items():
            for col in potential_cols:
                if col in row and row[col] is not None:
                    try:
                        engagement[key] = int(float(str(row[col]).strip()))
                    except (ValueError, TypeError):
                        engagement[key] = 0
                    break
        return engagement

    def search_hot_content(
        self,
        time_period: Literal['24h', 'week', 'year'] = 'week',
        limit: int = 50
    ) -> DBResponse:
        """
        【工具】查找热点内容: 获取最近一段时间内综合热度最高的内容。

        Args:
            time_period (Literal['24h', 'week', 'year']): 时间范围，默认为 'week'。
            limit (int): 返回结果的最大数量，默认为 50。

        Returns:
            DBResponse: 包含按综合热度排序后的内容列表。
        """
        params_for_log = {'time_period': time_period, 'limit': limit}
        logger.info(f"--- TOOL: 查找热点内容 (params: {params_for_log}) ---")
        self._begin_tool_query()
        
        now = datetime.now()
        start_time = now - timedelta(days={'24h': 1, 'week': 7}.get(time_period, 365))

        safe_limit = self._safe_limit(limit, settings.DEFAULT_SEARCH_HOT_CONTENT_LIMIT)
        formatted_results = []
        for idx, config in enumerate(self.HOT_CONTENT_CONFIGS):
            table = config['table']
            params = {'limit': safe_limit}
            time_clause = self._build_time_clause(table, config, params, f"hot_{idx}", start_time, now)
            formula = " + ".join(
                f"({self._numeric_expr(table, field)} * {weight})"
                for field, weight in config['metrics']
            ) or "0"
            source_expr = self._text_expr(table, 'source_keyword') if 'source_keyword' in self.TABLE_COLUMNS[table] else "NULL"
            query = (
                f"SELECT *, {self._text_expr(table, config['title'])} AS result_title, "
                f"{self._text_expr(table, config['author'])} AS result_author, "
                f"{self._text_expr(table, config['url'])} AS result_url, "
                f"{self._text_expr(table, config['time_col'])} AS result_ts, "
                f"{source_expr} AS result_source_keyword, "
                f"({formula}) AS hotness_score "
                f"FROM {self._quote_table(table)} "
                f"WHERE {time_clause} "
                f"ORDER BY hotness_score DESC LIMIT :limit"
            )
            for row in self._execute_query(query, params):
                formatted_results.append(QueryResult(
                    platform=config['platform'],
                    content_type=config['type'],
                    title_or_content=row.get('result_title') or '',
                    author_nickname=row.get('result_author'),
                    url=row.get('result_url'),
                    publish_time=self._to_datetime(row.get('result_ts')),
                    engagement=self._extract_engagement(row),
                    hotness_score=float(row.get('hotness_score') or 0.0),
                    source_keyword=row.get('result_source_keyword'),
                    source_table=table
                ))

        formatted_results.sort(key=lambda item: item.hotness_score, reverse=True)
        formatted_results = formatted_results[:safe_limit]
        return DBResponse("search_hot_content", params_for_log, results=formatted_results, results_count=len(formatted_results), error_message=self._empty_error(formatted_results))

    def search_topic_globally(self, topic: str, limit_per_table: int = 100) -> DBResponse:
        """
        【工具】全局话题搜索: 在数据库中（内容、评论、标签、来源关键字）全面搜索指定话题。

        Args:
            topic (str): 要搜索的话题关键词。
            limit_per_table (int): 从每个相关表中返回的最大记录数，默认为 100。

        Returns:
            DBResponse: 包含所有匹配结果的聚合列表。
        """
        params_for_log = {'topic': topic, 'limit_per_table': limit_per_table}
        logger.info(f"--- TOOL: 全局话题搜索 (params: {params_for_log}) ---")
        self._begin_tool_query()
        
        search_term, all_results = f"%{topic}%", []
        safe_limit = self._safe_limit(limit_per_table, settings.DEFAULT_SEARCH_TOPIC_GLOBALLY_LIMIT_PER_TABLE)
        for idx, (table, config) in enumerate(self.SEARCH_CONFIGS.items()):
            params = {'limit': safe_limit}
            where_clause = self._build_search_clause(table, config['fields'], params, f"global_{idx}", search_term)
            query = (
                f"SELECT * FROM {self._quote_table(table)} "
                f"WHERE {where_clause} "
                f"ORDER BY {self._quote_column(table, 'id')} DESC LIMIT :limit"
            )
            for row in self._execute_query(query, params):
                all_results.append(self._row_to_query_result(table, config['type'], row))
        return DBResponse("search_topic_globally", params_for_log, results=all_results, results_count=len(all_results), error_message=self._empty_error(all_results))

    def search_topic_by_date(self, topic: str, start_date: str, end_date: str, limit_per_table: int = 100) -> DBResponse:
        """
        【工具】按日期搜索话题: 在明确的历史时间段内，搜索与特定话题相关的内容。

        Args:
            topic (str): 要搜索的话题关键词。
            start_date (str): 开始日期，格式 'YYYY-MM-DD'。
            end_date (str): 结束日期，格式 'YYYY-MM-DD'。
            limit_per_table (int): 从每个相关表中返回的最大记录数，默认为 100。

        Returns:
            DBResponse: 包含在指定日期范围内找到的结果的聚合列表。
        """
        params_for_log = {'topic': topic, 'start_date': start_date, 'end_date': end_date, 'limit_per_table': limit_per_table}
        logger.info(f"--- TOOL: 按日期搜索话题 (params: {params_for_log}) ---")
        self._begin_tool_query()
        
        try:
            start_dt, end_dt = datetime.strptime(start_date, '%Y-%m-%d'), datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
        except ValueError:
            return DBResponse("search_topic_by_date", params_for_log, error_message="日期格式错误，请使用 'YYYY-MM-DD' 格式。")
        
        search_term, all_results = f"%{topic}%", []
        safe_limit = self._safe_limit(limit_per_table, settings.DEFAULT_SEARCH_TOPIC_BY_DATE_LIMIT_PER_TABLE)
        for idx, (table, config) in enumerate(self.SEARCH_CONFIGS.items()):
            params = {'limit': safe_limit}
            topic_clause = self._build_search_clause(table, config['fields'], params, f"date_{idx}", search_term)
            time_clause = self._build_time_clause(table, config, params, f"date_{idx}", start_dt, end_dt)
            where_clause = f"({topic_clause}) AND ({time_clause})" if time_clause else topic_clause
            query = (
                f"SELECT * FROM {self._quote_table(table)} "
                f"WHERE {where_clause} "
                f"ORDER BY {self._quote_column(table, 'id')} DESC LIMIT :limit"
            )
            for row in self._execute_query(query, params):
                all_results.append(self._row_to_query_result(table, config['type'], row))
        return DBResponse("search_topic_by_date", params_for_log, results=all_results, results_count=len(all_results), error_message=self._empty_error(all_results))
        
    def get_comments_for_topic(self, topic: str, limit: int = 500) -> DBResponse:
        """
        【工具】获取话题评论: 专门搜索并返回所有平台中与特定话题相关的公众评论数据。

        Args:
            topic (str): 要搜索的话题关键词。
            limit (int): 返回评论的总数量上限，默认为 500。

        Returns:
            DBResponse: 包含匹配的评论列表。
        """
        params_for_log = {'topic': topic, 'limit': limit}
        logger.info(f"--- TOOL: 获取话题评论 (params: {params_for_log}) ---")
        self._begin_tool_query()
        
        search_term = f"%{topic}%"
        safe_limit = self._safe_limit(limit, settings.DEFAULT_GET_COMMENTS_FOR_TOPIC_LIMIT)
        comment_tables = ['bilibili_video_comment', 'douyin_aweme_comment', 'kuaishou_video_comment', 'weibo_note_comment', 'xhs_note_comment', 'zhihu_comment', 'tieba_comment']
        formatted = []

        for idx, table in enumerate(comment_tables):
            cols = self._get_table_columns(table)
            author_col = 'user_nickname' if 'user_nickname' in cols else 'nickname'
            like_col = 'comment_like_count' if 'comment_like_count' in cols else 'like_count' if 'like_count' in cols else None
            time_col = 'publish_time' if 'publish_time' in cols else 'create_date_time' if 'create_date_time' in cols else 'create_time'
            like_select = self._text_expr(table, like_col) if like_col else "'0'"
            params = {f"comment_{idx}_term": search_term, 'limit': safe_limit}
            query = (
                f"SELECT {self._text_expr(table, 'content')} AS result_content, "
                f"{self._text_expr(table, author_col)} AS result_author, "
                f"{self._text_expr(table, time_col)} AS result_ts, "
                f"{like_select} AS result_likes "
                f"FROM {self._quote_table(table)} "
                f"WHERE {self._text_expr(table, 'content')} {self._like_operator()} :comment_{idx}_term "
                f"ORDER BY {self._quote_column(table, 'id')} DESC LIMIT :limit"
            )
            for row in self._execute_query(query, params):
                try:
                    likes = int(float(str(row.get('result_likes') or 0)))
                except (TypeError, ValueError):
                    likes = 0
                formatted.append(QueryResult(
                    platform=table.split('_')[0],
                    content_type='comment',
                    title_or_content=row.get('result_content') or '',
                    author_nickname=row.get('result_author'),
                    publish_time=self._to_datetime(row.get('result_ts')),
                    engagement={'likes': likes},
                    source_table=table
                ))

        formatted.sort(key=lambda item: item.publish_time or datetime.min, reverse=True)
        formatted = formatted[:safe_limit]
        return DBResponse("get_comments_for_topic", params_for_log, results=formatted, results_count=len(formatted), error_message=self._empty_error(formatted))

    def search_topic_on_platform(
        self,
        platform: Literal['bilibili', 'weibo', 'douyin', 'kuaishou', 'xhs', 'zhihu', 'tieba'],
        topic: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 20
    ) -> DBResponse:
        """
        【工具】平台定向搜索: (新增) 在指定的单个社交媒体平台上搜索特定话题。

        Args:
            platform (Literal['bilibili', ...]): 要搜索的平台，必须是七个支持的平台之一。
            topic (str): 要搜索的话题关键词。
            start_date (Optional[str]): 开始日期，格式 'YYYY-MM-DD'。默认为None。
            end_date (Optional[str]): 结束日期，格式 'YYYY-MM-DD'。默认为None。
            limit (int): 返回结果的最大数量，默认为 20。

        Returns:
            DBResponse: 包含在该平台找到的结果列表。
        """
        params_for_log = {'platform': platform, 'topic': topic, 'start_date': start_date, 'end_date': end_date, 'limit': limit}
        logger.info(f"--- TOOL: 平台定向搜索 (params: {params_for_log}) ---")
        self._begin_tool_query()

        if platform not in self.PLATFORM_CONFIGS:
            return DBResponse("search_topic_on_platform", params_for_log, error_message=f"不支持的平台: {platform}")

        search_term, all_results = f"%{topic}%", []
        safe_limit = self._safe_limit(limit, settings.DEFAULT_SEARCH_TOPIC_ON_PLATFORM_LIMIT)
        if start_date and end_date:
            try:
                start_dt, end_dt = datetime.strptime(start_date, '%Y-%m-%d'), datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            except ValueError:
                return DBResponse("search_topic_on_platform", params_for_log, error_message="日期格式错误，请使用 'YYYY-MM-DD' 格式。")
        else:
            start_dt, end_dt = None, None

        for idx, table in enumerate(self.PLATFORM_CONFIGS[platform]):
            config = self.SEARCH_CONFIGS[table]
            params = {'limit': safe_limit}
            topic_clause = self._build_search_clause(table, config['fields'], params, f"platform_{idx}", search_term)
            where_clause = topic_clause

            if start_dt and end_dt:
                time_clause = self._build_time_clause(table, config, params, f"platform_{idx}", start_dt, end_dt)
                if time_clause:
                    where_clause = f"({topic_clause}) AND ({time_clause})"

            query = (
                f"SELECT * FROM {self._quote_table(table)} "
                f"WHERE {where_clause} "
                f"ORDER BY {self._quote_column(table, 'id')} DESC LIMIT :limit"
            )
            for row in self._execute_query(query, params):
                all_results.append(self._row_to_query_result(table, config['type'], row, platform=platform))
        
        return DBResponse("search_topic_on_platform", params_for_log, results=all_results, results_count=len(all_results), error_message=self._empty_error(all_results))

# --- 3. 测试与使用示例 ---
def print_response_summary(response: DBResponse):
    """简化的打印函数，用于展示测试结果"""
    if response.error_message:
        logger.info(f"工具 '{response.tool_name}' 执行出错: {response.error_message}")
        return

    params_str = ", ".join(f"{k}='{v}'" for k, v in response.parameters.items())
    logger.info(f"查询: 工具='{response.tool_name}', 参数=[{params_str}]")
    logger.info(f"找到 {response.results_count} 条相关记录。")
    
    # 统一为一个消息输出
    output_lines = []
    output_lines.append("==== 查询结果预览（最多前5条） ====")
    if response.results and len(response.results) > 0:
        for idx, res in enumerate(response.results[:5], 1):
            content_preview = (res.title_or_content.replace('\n', ' ')[:70] + '...') if res.title_or_content and len(res.title_or_content) > 70 else (res.title_or_content or '')
            author_str = res.author_nickname or "N/A"
            publish_time_str = res.publish_time.strftime('%Y-%m-%d %H:%M') if res.publish_time else "N/A"
            hotness_str = f", hotness: {res.hotness_score:.2f}" if getattr(res, "hotness_score", 0) > 0 else ""
            engagement_dict = getattr(res, "engagement", {}) or {}
            engagement_str = ", ".join(f"{k}: {v}" for k, v in engagement_dict.items() if v)
            output_lines.append(
                f"{idx}. [{res.platform.upper()}/{res.content_type}] {content_preview}\n"
                f"   作者: {author_str} | 时间: {publish_time_str}"
                f"{hotness_str} | 源关键词: '{res.source_keyword or 'N/A'}'\n"
                f"   链接: {res.url or 'N/A'}\n"
                f"   互动数据: {{{engagement_str}}}"
            )
    else:
        output_lines.append("暂无相关内容。")
    output_lines.append("=" * 60)
    logger.info('\n'.join(output_lines))

if __name__ == "__main__":
    
    try:
        db_agent_tools = MediaCrawlerDB()
        logger.info("数据库工具初始化成功，开始执行测试场景...\n")
        
        # 场景1: (新) 查找过去一周综合热度最高的内容 (不再需要sort_by)
        response1 = db_agent_tools.search_hot_content(time_period='week', limit=5)
        print_response_summary(response1)

        # 场景2: 查找过去24小时内综合热度最高的内容
        response2 = db_agent_tools.search_hot_content(time_period='24h', limit=5)
        print_response_summary(response2)

        # 场景3: 全局搜索"罗永浩"
        response3 = db_agent_tools.search_topic_globally(topic="罗永浩", limit_per_table=2)
        print_response_summary(response3)

        # 场景4: (新增) 在B站上精确搜索"论文"
        response4 = db_agent_tools.search_topic_on_platform(platform='bilibili', topic="论文", limit=5)
        print_response_summary(response4)

        # 场景5: (新增) 在微博上精确搜索 "许凯" 在特定一天内的内容
        response5 = db_agent_tools.search_topic_on_platform(platform='weibo', topic="许凯", start_date='2025-08-22', end_date='2025-08-22', limit=5)
        print_response_summary(response5)

    except ValueError as e:
        logger.exception(f"初始化失败: {e}")
        logger.exception("请确保相关的数据库环境变量已正确设置, 或在代码中直接提供连接信息。")
    except Exception as e:
        logger.exception(f"测试过程中发生未知错误: {e}")
