# 搜索幻觉问题修复 - 实施指南

## ✅ 已完成

### 1. 相关性过滤工具 (`utils/relevance_filter.py`)
- [x] 实体提取功能（从topic中提取核心实体）
- [x] 搜索结果过滤（只保留包含核心实体的结果）
- [x] 总结相关性验证（检查LLM输出是否偏离主题）
- [x] 测试通过（40%保留率，成功过滤无关结果）

## 🔧 待实施修改

### P0 - 立即修复（本周必须完成）

#### 1. QueryEngine Prompt 强化

**文件**: `QueryEngine/prompts/prompts.py`

**修改位置**: `SYSTEM_PROMPT_FIRST_SEARCH` 和 `SYSTEM_PROMPT_REFLECTION`

**添加内容**（在工具介绍后）:
```python
**搜索Query生成规则（必须严格遵守）**：
1. ✅ 必须保留原始topic的核心实体（人名/品牌/事件名）
2. ❌ 禁止添加无关的人名、事件名、节目名
3. ❌ 禁止添加未在原始topic中出现的娱乐热点
4. ⏰ 时间限定词要与原始topic时间一致
5. 示例：
   - 原始topic: "再见爱人麦琳熏鸡事件"
   - ✅ 正确query: "麦琳 熏鸡 再见爱人 舆情 2026"
   - ✅ 正确query: "李行亮 麦琳 冲突"
   - ❌ 错误query: "胡彦斌 黑脸 冥顽不灵" （无关人物）
   - ❌ 错误query: "歌手2026 淘汰" （无关节目）
```

**修改位置**: `SYSTEM_PROMPT_FIRST_SUMMARY` 和 `SYSTEM_PROMPT_REFLECTION_SUMMARY`

**添加内容**（在撰写标准后）:
```python
**严格相关性准则（必须遵守，违反将导致报告质量问题）**：

❌ **禁止写入以下内容**：
1. 同名人物的其他热点事件（例如："胡彦斌在其他节目的黑脸事件"与本topic无关）
2. 同时期但主题不相关的事件（例如："歌手2026淘汰"与"再见爱人"完全无关）
3. 没有搜索结果来源支撑的具体数据（例如："2小时1.2亿播放"必须有来源链接）
4. 搜索结果中未提及原始topic核心实体的内容

✅ **只能写入以下内容**：
1. 搜索结果中明确提到原始topic核心实体的内容
2. 有明确来源链接的数据和引用
3. 类比可以提及，但必须明确标注"作为类比"或"类似案例"，不能混淆为主事件

**数据引用铁律**：
- 所有具体数字（播放量、点赞数、转发数等）必须注明来源
- 没有来源的数据，改为"搜索结果声称..."或直接过滤
- 多个来源数据冲突时，必须注明"不同来源数据存在差异：A来源称X，B来源称Y"
```

#### 2. MediaEngine Prompt 强化

**文件**: `MediaEngine/prompts/prompts.py`

**修改**: 与QueryEngine相同的内容添加到对应的SEARCH和SUMMARY prompts中

#### 3. InsightEngine 空库处理

**文件**: `InsightEngine/nodes/summary_node.py`

**修改**: `FirstSummaryNode.run()` 方法，在调用LLM前添加：

```python
# 在 line 80 左右，data 准备好之后添加
# 检测空搜索结果
search_results = data.get('search_results', [])
if not search_results or len(search_results) == 0:
    logger.warning(f"InsightEngine数据库无相关数据")
    return "【本地数据库无相关记录】\n\n本地舆情数据库暂无该话题的历史数据。这可能是因为：\n1. 话题较新，尚未进行数据采集\n2. 爬虫功能未启用\n3. 数据库中无相关关键词记录\n\n建议依赖Media Engine和Query Engine的外部搜索结果进行分析。"

# 检测结果过少（警告但继续）
if len(search_results) < 3:
    logger.warning(f"InsightEngine数据过少，仅{len(search_results)}条，分析可能不够全面")
    data['_data_warning'] = f"注意：本地数据库仅找到{len(search_results)}条相关记录，分析可能不够全面。"
```

**同样修改**: `ReflectionSummaryNode.run()` 添加相同的检查

#### 4. 集成相关性过滤到 QueryEngine

**文件**: `QueryEngine/agent.py`

**修改位置**: 搜索工具调用后，将结果传给LLM之前

找到搜索结果处理的地方（大约在处理 `search_results` 的位置），添加：

```python
from utils.relevance_filter import filter_results

# 在搜索完成后，summary之前
# 假设搜索结果在 search_results 变量中
if search_results:
    # 过滤搜索结果
    filtered_results, filter_stats = filter_results(
        search_results,
        state.original_query,  # 原始用户query
        min_score=0.2,
        min_match=1
    )
    
    # 记录过滤统计
    logger.info(f"搜索结果相关性过滤: {filter_stats}")
    
    # 如果保留率太低，警告
    if filter_stats.get('retention_rate', 1.0) < 0.3:
        logger.warning(
            f"⚠️ Query可能过宽，保留率仅{filter_stats['retention_rate']*100:.1f}%"
        )
    
    # 使用过滤后的结果
    search_results = filtered_results
```

#### 5. 集成相关性过滤到 MediaEngine

**文件**: `MediaEngine/agent.py`

**修改**: 与QueryEngine相同的逻辑

### P1 - 本周完成（提升效果）

#### 6. InsightEngine Prompt 强化

**文件**: `InsightEngine/prompts/prompts.py`

**修改**: 添加与Query/Media相同的相关性准则到SUMMARY prompts

#### 7. 添加环境变量控制

**文件**: `.env.example` 和 `config.py`

**添加配置项**:
```bash
# 相关性过滤开关（默认启用）
ENABLE_RELEVANCE_FILTER=true

# 严格模式（更强的约束）
STRICT_SUMMARY_MODE=true

# 过滤阈值（0.0-1.0，越高越严格）
RELEVANCE_MIN_SCORE=0.2

# 最少匹配实体数
RELEVANCE_MIN_MATCH=1
```

**在 `config.py` 中添加**:
```python
# 相关性过滤配置
ENABLE_RELEVANCE_FILTER = os.getenv("ENABLE_RELEVANCE_FILTER", "true").lower() == "true"
STRICT_SUMMARY_MODE = os.getenv("STRICT_SUMMARY_MODE", "true").lower() == "true"
RELEVANCE_MIN_SCORE = float(os.getenv("RELEVANCE_MIN_SCORE", "0.2"))
RELEVANCE_MIN_MATCH = int(os.getenv("RELEVANCE_MIN_MATCH", "1"))
```

### P2 - 优化增强（可选）

#### 8. Forum主持人相关性检查

**文件**: `ForumEngine/llm_host.py`

**功能**: 在主持人生成建议topic时，也检查是否偏离原始query

#### 9. 添加用户可见的警告

在报告中添加数据质量警告：
- InsightEngine空库时显示："⚠️ 本地数据库无相关历史数据"
- 搜索结果被大量过滤时："⚠️ 部分无关搜索结果已被过滤"

## 📊 测试验证清单

### 测试用例1: 再见爱人麦琳事件
```bash
输入: "再见爱人麦琳熏鸡事件舆情分析"

预期行为:
✅ Query生成: "麦琳 熏鸡 再见爱人" 而非 "胡彦斌 黑脸 冥顽不灵"
✅ 搜索过滤: 保留包含"麦琳"或"再见爱人"的结果，过滤"歌手2026"
✅ 报告输出: 不出现"胡彦斌在《歌手2026》..."等无关内容
✅ 无幻觉数据: 不出现无来源的"2小时1.2亿"等数据
```

### 测试用例2: InsightEngine空库
```bash
输入: 任意新话题（数据库无数据）

预期行为:
✅ 明确标注: "【本地数据库无相关记录】"
✅ 不编造数据: 不出现虚假的用户评论、互动数据
✅ 建议提示: 提示用户依赖外部搜索结果
```

### 测试用例3: 过滤效果监控
```bash
检查日志中的过滤统计:
✅ 保留率 >30%: 正常（过宽会触发警告）
✅ 核心实体提取: 应包含2-5个关键词
✅ 过滤样例记录: 查看被过滤的内容是否确实无关
```

## 🚀 部署步骤

1. **备份当前版本**
   ```bash
   git checkout -b fix-hallucination-backup
   git add .
   git commit -m "Backup before hallucination fix"
   ```

2. **应用修改**（按P0顺序）
   - [ ] 修改 QueryEngine/prompts/prompts.py
   - [ ] 修改 MediaEngine/prompts/prompts.py
   - [ ] 修改 InsightEngine/nodes/summary_node.py
   - [ ] 修改 QueryEngine/agent.py（集成过滤）
   - [ ] 修改 MediaEngine/agent.py（集成过滤）

3. **测试验证**
   ```bash
   # 测试相关性过滤工具
   source .venv/bin/activate
   python utils/relevance_filter.py
   
   # 运行完整测试
   python app.py
   # 输入测试query: "再见爱人麦琳熏鸡事件"
   ```

4. **监控效果**
   - 查看 `logs/query.log` 和 `logs/media.log` 中的过滤统计
   - 对比修复前后的报告质量
   - 记录保留率、实体覆盖率等指标

5. **回滚方案**（如果出现问题）
   ```bash
   # 关闭相关性过滤
   echo "ENABLE_RELEVANCE_FILTER=false" >> .env
   
   # 或回退到备份
   git checkout fix-hallucination-backup
   ```

## 📈 成功指标

修复成功的标志：
- ✅ Query不再包含无关人物/节目
- ✅ 搜索结果相关性 >60%
- ✅ 报告中核心实体提及率 >80%
- ✅ 无来源幻觉数据 <5%
- ✅ InsightEngine空库时明确标注

## 💡 后续优化方向

1. **集成专业NER工具** (如jieba, LAC)
   - 更准确的实体识别
   - 区分人名、地名、事件名

2. **时间一致性检查**
   - 验证query中的时间与topic时间一致
   - 过滤时间不匹配的结果

3. **来源验证机制**
   - 检查数据是否有URL来源
   - 标记"待验证"的数据

4. **用户反馈学习**
   - 收集用户标注的幻觉案例
   - 持续优化过滤规则

## 📞 问题反馈

如遇到问题，请检查：
1. 日志文件中的过滤统计
2. 实体提取是否正确
3. 环境变量配置是否生效

提Issue时请包含：
- 原始query
- 提取的核心实体
- 过滤统计信息
- 问题报告片段
