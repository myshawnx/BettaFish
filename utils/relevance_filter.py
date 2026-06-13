"""
搜索相关性约束工具 (Search Relevance Guard)

用于抑制 live search 模式下的"搜索幻觉"：反思阶段 query 漂移到相邻热点、
召回无关结果、LLM 把同名人物的其他事件当成主线证据写进报告。

四个能力（被三个引擎和 Forum 复用）：
1. extract_core_entities(topic)   —— 用 jieba 从原始 topic 提取核心实体（人名/事件/品牌）
2. enforce_core_entities(query, topic) —— 确定性地把核心实体重新锚定进 query（L1 治本）
3. filter_search_results(results, topic) —— 过滤标题/摘要不含核心实体的结果（L2，含安全阀）
4. validate_summary_relevance(summary, topic) —— 校验总结是否仍贴着原始 topic（监控用）

设计原则（与用户选择一致：宽松 + 日志告警 + 安全阀）：
- 默认 min_match=1（命中任意一个核心实体即保留），不轻易丢结果
- 安全阀：若过滤后保留率低于 safety_floor，则放弃过滤、原样返回并告警，
  避免实体提取失误（或合理关联背景如"李行亮回应"）被误杀导致段落无证据
- 全部能力可通过环境变量 ENABLE_RELEVANCE_FILTER 关闭，零侵入回滚
"""

import os
import re
from typing import List, Dict, Any, Tuple, Optional

from loguru import logger

try:  # jieba 已在 requirements.txt 中；缺失时优雅降级到 n-gram
    import jieba
    jieba.setLogLevel("ERROR")  # 静默 "Building prefix dict" 提示
    _JIEBA_AVAILABLE = True
except Exception:  # pragma: no cover - 仅在无 jieba 环境触发
    _JIEBA_AVAILABLE = False


# 通用停用词：这些词出现在几乎所有 topic 里，不能当作"核心实体"做锚定/过滤
_STOPWORDS = {
    "分析", "研究", "报告", "舆情", "事件", "热点", "话题", "讨论", "舆论",
    "最新", "深度", "全面", "综合", "专题", "解析", "评价", "评论", "观点",
    "如何", "怎么", "什么", "为何", "为什么", "哪些", "怎样", "发展", "趋势",
    "相关", "主要", "重要", "关键", "核心", "问题", "情况", "方面", "影响",
    "网络", "社会", "公众", "民众", "网友", "网民", "情感", "情绪", "传播",
    "的", "了", "和", "与", "及", "或", "在", "对", "关于", "进行",
}


def _normalize(text: str) -> str:
    return (text or "").strip()


class RelevanceFilter:
    """搜索相关性约束器（实体提取 + query 锚定 + 结果过滤 + 总结校验）"""

    def __init__(self, enable: Optional[bool] = None):
        if enable is None:
            enable = os.getenv("ENABLE_RELEVANCE_FILTER", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.enable = enable
        if not self.enable:
            logger.warning("相关性约束器已禁用 (ENABLE_RELEVANCE_FILTER=false)")

    # ---------- 1. 实体提取 ----------

    def extract_core_entities(self, topic: str, max_entities: int = 6) -> List[str]:
        """
        从原始 topic 提取核心实体。

        优先用 jieba 分词（能正确切出"麦琳/李行亮/再见爱人/熏鸡"），
        过滤停用词与单字，并把相邻保留词拼成 2-gram 以保留"再见爱人"这类多词实体。
        无 jieba 时退化为标点切分 + 中文 2-4gram。

        Returns:
            去重后的核心实体列表（按出现顺序）
        """
        topic = _normalize(topic)
        if not topic:
            return []

        tokens: List[str] = []
        if _JIEBA_AVAILABLE:
            raw = [t.strip() for t in jieba.lcut(topic) if t.strip()]
            kept = [t for t in raw if t not in _STOPWORDS and len(t) >= 2 and not t.isdigit()]
            tokens.extend(kept)
            # 把分词结果里相邻的保留词，按它们在原串里紧邻出现的情况拼成 bigram
            # 例如 "再见"+"爱人" → "再见爱人"，提升对节目名/组织名的命中率
            for i in range(len(kept) - 1):
                bigram = kept[i] + kept[i + 1]
                if bigram in topic:
                    tokens.append(bigram)
        else:  # pragma: no cover
            parts = re.split(r"[，。！？、；：“”‘’（）《》【】\s,.!?;:()\[\]]+", topic)
            for part in parts:
                part = part.strip()
                if 2 <= len(part) <= 8 and part not in _STOPWORDS:
                    tokens.append(part)
            tokens.extend(re.findall(r"[一-鿿]{2,4}", topic))

        # 单字英文/数字组合也保留（如型号、缩写），但过滤纯停用词
        entities: List[str] = []
        for tok in tokens:
            if tok in _STOPWORDS or len(tok) < 2 or tok.isdigit():
                continue
            entities.append(tok)

        # 去重保序
        seen = set()
        unique = []
        for e in entities:
            if e not in seen:
                seen.add(e)
                unique.append(e)

        result = unique[:max_entities]
        logger.info(f"[relevance] 核心实体 (topic='{topic}'): {result}")
        return result

    # ---------- 2. query 确定性锚定 (L1 治本) ----------

    def enforce_core_entities(
        self,
        query: str,
        topic: str,
        core_entities: Optional[List[str]] = None,
    ) -> Tuple[str, bool]:
        """
        确定性地保证 search query 含有原始 topic 的核心实体。

        这是抑制 query 漂移的"治本"手段：即使 LLM 反思时生成了
        "胡彦斌 黑脸 冥顽不灵"，这里也会把它纠正回
        "麦琳 再见爱人 胡彦斌 黑脸 冥顽不灵"，把搜索重新拉回原始主题。

        策略（宽松）：
        - 若 query 已含至少一个核心实体 → 原样返回（不破坏 LLM 的合理细化）
        - 若一个都不含 → 在 query 前缀拼上最重要的 1-2 个核心实体

        Returns:
            (anchored_query, was_modified)
        """
        if not self.enable:
            return query, False

        query = _normalize(query)
        if core_entities is None:
            core_entities = self.extract_core_entities(topic)
        if not core_entities or not query:
            return query, False

        # 已含任意核心实体 → 不动
        if any(ent in query for ent in core_entities):
            return query, False

        # 一个都不含：query 已漂移，前缀注入最主要的核心实体（取前2个）
        anchor = " ".join(core_entities[:2])
        anchored = f"{anchor} {query}"
        logger.warning(
            f"[relevance] query 已漂移，强制锚定核心实体: '{query}' → '{anchored}'"
        )
        return anchored, True

    # ---------- 3. 搜索结果过滤 (L2 拦截，含安全阀) ----------

    def filter_search_results(
        self,
        results: List[Any],
        topic: str,
        min_match: int = 1,
        safety_floor: float = 0.34,
        core_entities: Optional[List[str]] = None,
        text_fields: Optional[List[str]] = None,
    ) -> Tuple[List[Any], Dict[str, Any]]:
        """
        过滤掉标题/摘要完全不含任何核心实体的搜索结果。

        宽松策略 + 安全阀：
        - min_match=1：命中任意一个核心实体即保留
        - 安全阀 safety_floor：若过滤后保留率 < safety_floor（默认 34%），
          认为很可能是实体提取失误或本来就是宽召回，**放弃过滤、原样返回**并告警。
          这保证本层永远不会让某段落彻底失去证据（防误杀优先于防漂移）。

        Returns:
            (kept_results, stats)
        """
        stats: Dict[str, Any] = {"filtered": False}
        if not self.enable or not results:
            stats["reason"] = "disabled" if not self.enable else "empty_input"
            return results, stats

        if core_entities is None:
            core_entities = self.extract_core_entities(topic)
        if not core_entities:
            stats["reason"] = "no_entities"
            return results, stats

        if text_fields is None:
            text_fields = self._detect_text_fields(results[0])

        kept, dropped = [], []
        for r in results:
            text = self._extract_text(r, text_fields)
            matched = [e for e in core_entities if e in text]
            if len(matched) >= min_match:
                self._attach_score(r, len(matched) / len(core_entities), len(matched))
                kept.append(r)
            else:
                dropped.append({"preview": text[:80], "matched": 0})

        retention = len(kept) / len(results) if results else 0.0
        stats.update({
            "topic": topic,
            "core_entities": core_entities,
            "input_count": len(results),
            "kept_count": len(kept),
            "dropped_count": len(dropped),
            "retention_rate": round(retention, 3),
            "dropped_samples": dropped[:3],
        })

        # 安全阀：保留率过低 → 放弃过滤，原样返回（防误杀）
        if kept and retention < safety_floor:
            logger.warning(
                f"[relevance] 保留率 {retention*100:.0f}% < 安全阀 {safety_floor*100:.0f}%，"
                f"放弃过滤、原样返回 {len(results)} 条（可能实体提取偏差或宽召回）"
            )
            stats["filtered"] = False
            stats["reason"] = "safety_floor_triggered"
            return results, stats

        # 全部被过滤掉也触发安全阀（绝不让段落无证据）
        if not kept:
            logger.warning(
                f"[relevance] 全部 {len(results)} 条均不含核心实体，触发安全阀原样返回 "
                f"(实体={core_entities})，请检查 query 是否严重漂移"
            )
            stats["reason"] = "all_dropped_safety"
            return results, stats

        stats["filtered"] = True
        logger.info(
            f"[relevance] 结果过滤: {len(results)}→{len(kept)} 条 "
            f"(保留率 {retention*100:.0f}%, 实体={core_entities})"
        )
        return kept, stats

    # ---------- 4. 总结相关性校验 (监控) ----------

    def validate_summary_relevance(
        self,
        summary: str,
        topic: str,
        min_entity_mentions: int = 1,
        core_entities: Optional[List[str]] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """校验 LLM 生成的段落是否仍提及原始 topic 的核心实体（仅告警，不阻断）。"""
        if core_entities is None:
            core_entities = self.extract_core_entities(topic)

        mentioned = [e for e in core_entities if e in (summary or "")]
        is_relevant = len(mentioned) >= min_entity_mentions
        report = {
            "is_relevant": is_relevant,
            "mentioned_entities": mentioned,
            "missing_entities": [e for e in core_entities if e not in mentioned],
            "entity_coverage": round(len(mentioned) / len(core_entities), 3) if core_entities else 0.0,
        }
        if core_entities and not is_relevant:
            logger.warning(
                f"[relevance] 段落疑似偏题: 未提及任何核心实体 {core_entities}，"
                f"可能掺入了无关热点"
            )
        return is_relevant, report

    # ---------- 内部工具 ----------

    @staticmethod
    def _detect_text_fields(sample: Any) -> List[str]:
        candidates = [
            "title", "name", "snippet", "content", "description", "summary",
            "text", "body", "abstract", "title_or_content",
        ]
        found = []
        if isinstance(sample, dict):
            for f in candidates:
                if sample.get(f):
                    found.append(f)
        elif hasattr(sample, "__dict__"):
            for f in candidates:
                if getattr(sample, f, None):
                    found.append(f)
        return found

    @staticmethod
    def _extract_text(result: Any, text_fields: List[str]) -> str:
        if not text_fields:
            return str(result)
        parts = []
        if isinstance(result, dict):
            for f in text_fields:
                v = result.get(f)
                if v:
                    parts.append(str(v))
        elif hasattr(result, "__dict__"):
            for f in text_fields:
                v = getattr(result, f, None)
                if v:
                    parts.append(str(v))
        return " ".join(parts)

    @staticmethod
    def _attach_score(result: Any, score: float, matched: int) -> None:
        if isinstance(result, dict):
            result["_relevance_score"] = round(score, 3)
            result["_matched_entities"] = matched
        elif hasattr(result, "__dict__"):
            try:
                result.relevance_score = round(score, 3)
                result.matched_entities = matched
            except Exception:
                pass


# ---------- 全局单例 + 便捷函数 ----------

_global_filter: Optional[RelevanceFilter] = None


def get_relevance_filter() -> RelevanceFilter:
    global _global_filter
    if _global_filter is None:
        _global_filter = RelevanceFilter()
    return _global_filter


def extract_core_entities(topic: str, **kwargs) -> List[str]:
    return get_relevance_filter().extract_core_entities(topic, **kwargs)


def enforce_core_entities(query: str, topic: str, **kwargs) -> Tuple[str, bool]:
    return get_relevance_filter().enforce_core_entities(query, topic, **kwargs)


def filter_results(results: List[Any], topic: str, **kwargs) -> Tuple[List[Any], Dict[str, Any]]:
    return get_relevance_filter().filter_search_results(results, topic, **kwargs)


def validate_summary(summary: str, topic: str, **kwargs) -> Tuple[bool, Dict[str, Any]]:
    return get_relevance_filter().validate_summary_relevance(summary, topic, **kwargs)


if __name__ == "__main__":
    from dataclasses import dataclass

    @dataclass
    class MockResult:
        title: str
        snippet: str

    topic = "再见爱人麦琳熏鸡事件舆情分析"
    print("=" * 60, "\n核心实体提取:")
    ents = extract_core_entities(topic)
    print("  ", ents)

    print("=" * 60, "\nL1 query 锚定:")
    for q in ["麦琳 熏鸡 评价", "胡彦斌 黑脸 冥顽不灵 2026", "再见爱人4 收视"]:
        anchored, mod = enforce_core_entities(q, topic, core_entities=ents)
        flag = "🔧改写" if mod else "✓保留"
        print(f"   {flag}: '{q}' → '{anchored}'")

    print("=" * 60, "\nL2 结果过滤:")
    results = [
        MockResult("麦琳熏鸡事件持续发酵", "麦琳在再见爱人节目中的熏鸡言论引发争议"),
        MockResult("李行亮回应妻子争议", "李行亮首次对麦琳的言论做出回应"),  # 含"麦琳"+"李行亮"
        MockResult("胡彦斌黑脸事件分析", "胡彦斌在歌手2026中因张碧晨淘汰而不满"),  # 无关
        MockResult("再见爱人第四季收视创新高", "节目播出后麦琳成为话题中心"),
        MockResult("冥顽不灵成网络热词", "最近网络热词冥顽不灵的来源"),  # 无关
    ]
    kept, stats = filter_results(results, topic, core_entities=ents)
    print(f"   保留 {len(kept)}/{len(results)}, filtered={stats['filtered']}, 保留率={stats['retention_rate']}")
    for r in kept:
        print(f"   ✅ {r.title} (score={getattr(r,'relevance_score','?')})")

    print("=" * 60, "\nL3 总结校验:")
    good = "麦琳在再见爱人中的熏鸡话题引发讨论，李行亮做出回应"
    bad = "胡彦斌在歌手2026因张碧晨淘汰黑脸，展现冥顽不灵态度"
    for name, s in [("贴题总结", good), ("偏题总结", bad)]:
        ok, rep = validate_summary(s, topic, core_entities=ents)
        print(f"   {name}: relevant={ok}, 提及={rep['mentioned_entities']}, 覆盖={rep['entity_coverage']}")
