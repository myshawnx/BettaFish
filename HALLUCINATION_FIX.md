# 搜索幻觉问题修复方案

## 问题描述

在"再见爱人麦琳熏鸡事件"舆情分析中，系统出现以下幻觉：
- 搜索query过度扩展，包含"冥顽不灵"、"胡彦斌黑脸"等无关词汇
- 召回了"歌手2026张碧晨淘汰"等同时期无关娱乐热点
- LLM把无关热点当成主事件证据写入报告
- InsightEngine空库时幻觉最严重

## 根源分析

```
原始Topic: 麦琳熏鸡、李行亮、再见爱人
    ↓
反思Query扩展: "胡彦斌 黑脸 再见爱人4 冥顽不灵 评价 2026年6月"
    ↓
搜索返回: 相邻娱乐热点混入（歌手2026、张碧晨淘汰等）
    ↓
无相关性过滤: 直接传给LLM
    ↓
LLM总结: 把类比当事实，写成"胡彦斌在《歌手2026》中因张碧晨淘汰而黑脸"
    ↓
Forum放大: 主持人把"冥顽不灵"当下一轮研究重点
```

## 修复策略（4层防御）

### 第1层：搜索Query约束
**位置**: `*/nodes/search_node.py` 和 `*/prompts/prompts.py`

**改动**: 在SYSTEM_PROMPT中强制要求保留核心实体

```python
# 在SYSTEM_PROMPT_FIRST_SEARCH和SYSTEM_PROMPT_REFLECTION中添加：

**搜索Query生成规则（必须遵守）**：
1. 必须保留原始topic的至少一个核心实体（人名/品牌/事件名）
2. 禁止添加无关的人名、事件名
3. 时间限定词要与原始topic一致（如"2026年6月"要确认是topic时间）
4. 示例：
   - ✅ 正确: "麦琳 熏鸡 再见爱人 舆情"
   - ✅ 正确: "李行亮 麦琳 冲突 2026"
   - ❌ 错误: "胡彦斌 黑脸 冥顽不灵" （无关人物）
   - ❌ 错误: "歌手2026 淘汰" （无关节目）
```

### 第2层：搜索结果相关性过滤
**位置**: 新建 `*/utils/relevance_filter.py`

**功能**: 
- 提取原始topic的核心实体（NER或关键词）
- 过滤标题/摘要不含核心实体的搜索结果
- 记录过滤统计到日志

```python
# 伪代码示例
def filter_search_results(results, core_entities, min_match=1):
    """
    过滤搜索结果，只保留包含核心实体的结果
    
    Args:
        results: 搜索结果列表
        core_entities: 核心实体列表 ['麦琳', '李行亮', '再见爱人']
        min_match: 至少匹配的实体数量
    
    Returns:
        过滤后的结果 + 过滤统计
    """
    filtered = []
    for result in results:
        text = result.title + " " + result.snippet
        matched = sum(1 for entity in core_entities if entity in text)
        if matched >= min_match:
            result.relevance_score = matched
            filtered.append(result)
    
    logger.info(f"相关性过滤: {len(results)}条 -> {len(filtered)}条 (保留率{len(filtered)/len(results)*100:.1f}%)")
    return filtered
```

### 第3层：Summary Prompt强化约束
**位置**: `*/prompts/prompts.py` 的 SUMMARY 相关prompt

**改动**: 添加严格的"相关性准则"

```python
# 在SYSTEM_PROMPT_FIRST_SUMMARY和SYSTEM_PROMPT_REFLECTION_SUMMARY中添加：

**严格相关性准则（必须遵守）**：
1. ❌ 禁止写入：同名人物的其他热点（如"胡彦斌在其他节目的黑脸"与本topic无关）
2. ❌ 禁止写入：同时期但无关的事件（如"歌手2026淘汰"与"再见爱人"无关）
3. ❌ 禁止写入：没有来源链接支撑的数据（如"2小时1.2亿"需要来源）
4. ✅ 只能写入：搜索结果中明确提到原始topic核心实体的内容
5. ✅ 类比可以提及，但必须明确标注"作为类比"，不能当成主事件

**数据引用规则**：
- 所有具体数字必须注明来源
- 没有来源的声称，改为"搜索结果声称..."或直接过滤
- 多个来源冲突时，注明"不同来源数据存在差异"
```

### 第4层：InsightEngine空库处理
**位置**: `InsightEngine/nodes/summary_node.py`

**改动**: 检测空结果，明确标注而不是编造

```python
# 在FirstSummaryNode.run()中添加空结果检测
if not search_results or len(search_results) == 0:
    logger.warning(f"InsightEngine数据库无相关数据，段落{paragraph_index}")
    return "【数据库无相关记录】本地舆情数据库暂无该话题的历史数据。建议启用爬虫采集或依赖Media/Query引擎的外部搜索结果。"

# 检测结果过少
if len(search_results) < 3:
    logger.warning(f"InsightEngine数据过少，仅{len(search_results)}条，可能不足以支撑分析")
```

## 实施优先级

### P0（立即修复）
1. **Summary Prompt强化** - 最快见效，立即阻止幻觉写入
2. **InsightEngine空库标注** - 防止最严重的编造

### P1（本周完成）
3. **搜索结果相关性过滤** - 阻止污染数据进入
4. **搜索Query约束** - 源头控制

### P2（优化增强）
5. Forum主持人相关性检查（避免放大无关方向）
6. 添加人工审核节点（高风险报告人工确认）

## 测试验证

### 测试用例1：再见爱人麦琳事件
```
输入: "再见爱人麦琳熏鸡事件舆情分析"
核心实体: ['麦琳', '李行亮', '再见爱人', '熏鸡']

预期Query: 
✅ "麦琳 熏鸡 再见爱人 舆情 2026"
❌ "胡彦斌 黑脸 冥顽不灵"

预期过滤:
- 保留: 标题含"麦琳"或"再见爱人"的结果
- 过滤: "歌手2026"、"张碧晨淘汰"等结果

预期输出:
- 不应出现："胡彦斌在《歌手2026》中..."
- 不应出现："冥顽不灵"作为核心词汇
```

### 测试用例2：InsightEngine空库
```
输入: 任意话题
数据库: 空

预期输出:
"【数据库无相关记录】本地舆情数据库暂无该话题的历史数据。建议启用爬虫采集或依赖Media/Query引擎的外部搜索结果。"

而不是编造数据。
```

## 监控指标

1. **相关性过滤率**: 目标 >60%保留率（<60%说明query太宽）
2. **核心实体覆盖**: 每个summary段落应至少提及1个核心实体
3. **无来源数据率**: 目标 <5%（过多说明在编造）
4. **InsightEngine空结果率**: 记录并提醒用户启用爬虫

## 代码改动清单

- [ ] `QueryEngine/prompts/prompts.py` - 添加Query约束
- [ ] `MediaEngine/prompts/prompts.py` - 添加Query约束  
- [ ] `InsightEngine/prompts/prompts.py` - 添加Query约束
- [ ] `QueryEngine/prompts/prompts.py` - 添加Summary相关性准则
- [ ] `MediaEngine/prompts/prompts.py` - 添加Summary相关性准则
- [ ] `InsightEngine/prompts/prompts.py` - 添加Summary相关性准则
- [ ] 新建 `utils/relevance_filter.py` - 相关性过滤工具
- [ ] `QueryEngine/agent.py` - 集成相关性过滤
- [ ] `MediaEngine/agent.py` - 集成相关性过滤
- [ ] `InsightEngine/nodes/summary_node.py` - 空库检测
- [ ] `ForumEngine/llm_host.py` - (可选) 相关性检查

## 回滚计划

所有修改通过环境变量控制，可随时关闭：
```python
ENABLE_RELEVANCE_FILTER = os.getenv("ENABLE_RELEVANCE_FILTER", "true") == "true"
STRICT_SUMMARY_MODE = os.getenv("STRICT_SUMMARY_MODE", "true") == "true"
```
