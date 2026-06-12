"""
论坛主持人模块
使用硅基流动的Qwen3模型作为论坛主持人，引导多个agent进行讨论
"""

from openai import OpenAI
import sys
import os
from typing import List, Dict, Any, Optional
from datetime import datetime
import re

# 添加项目根目录到Python路径以导入config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import settings

# 添加utils目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
utils_dir = os.path.join(root_dir, 'utils')
if utils_dir not in sys.path:
    sys.path.append(utils_dir)

from utils.retry_helper import with_graceful_retry, SEARCH_API_RETRY_CONFIG


class ForumHost:
    """
    论坛主持人类
    使用Qwen3-235B模型作为智能主持人
    """
    
    def __init__(self, api_key: str = None, base_url: Optional[str] = None, model_name: Optional[str] = None):
        """
        初始化论坛主持人

        Args:
            api_key: 论坛主持人 LLM API 密钥，如果不提供则从配置文件读取
            base_url: 论坛主持人 LLM API 接口基础地址，默认使用配置文件提供的SiliconFlow地址
        """
        self.api_key = settings.FORUM_HOST_API_KEY if api_key is None else api_key
        self.base_url = base_url or settings.FORUM_HOST_BASE_URL
        self.model = model_name or settings.FORUM_HOST_MODEL_NAME
        self.client = None
        if self.api_key:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )

        # Track previous summaries to avoid duplicates
        self.previous_summaries = []
    
    def generate_host_speech(self, forum_logs: List[str]) -> Optional[str]:
        """
        生成主持人发言

        Args:
            forum_logs: 论坛日志内容列表

        Returns:
            主持人发言内容，如果生成失败返回None
        """
        verdict = self.generate_moderator_verdict(forum_logs)
        if not self.client:
            return verdict["suggested_host_message"]

        try:
            parsed_content = self._parse_forum_logs(forum_logs)

            if not parsed_content['agent_speeches']:
                print("ForumHost: 没有找到有效的agent发言")
                return verdict["suggested_host_message"]

            system_prompt = self._build_system_prompt()
            user_prompt = self._build_user_prompt(parsed_content)
            response = self._call_qwen_api(system_prompt, user_prompt)

            if response["success"]:
                speech = response["content"]
                return self._format_host_speech(speech)

            print(f"ForumHost: API调用失败 - {response.get('error', '未知错误')}")
            return verdict["suggested_host_message"]

        except Exception as e:
            print(f"ForumHost: 生成发言时出错 - {str(e)}")
            return verdict["suggested_host_message"]

    def generate_moderator_verdict(self, forum_logs: List[str]) -> Dict[str, Any]:
        parsed_content = self._parse_forum_logs(forum_logs)
        speeches = parsed_content['agent_speeches']
        combined_text = "\n".join(speech['content'] for speech in speeches).strip()
        source_count = len({speech['speaker'] for speech in speeches})

        if not speeches:
            return {
                "topic": "等待 Agent 发言",
                "risk_level": "low",
                "action": "wait",
                "rationale": "当前论坛还没有可分析的 Agent 输出。",
                "suggested_host_message": "主持人：当前正在等待各 Agent 输出，收到有效分析后会汇总风险与下一步讨论方向。",
                "source_count": 0,
                "llm_enabled": bool(self.client),
                "error": None if self.client else "FORUM_HOST_API_KEY 未配置，使用规则 fallback"
            }

        risk_keywords = ["风险", "争议", "危机", "攻击", "负面", "舆情", "下跌", "投诉", "违法", "造假"]
        gap_keywords = ["不确定", "缺少", "不足", "待确认", "无法判断", "需要进一步", "暂无"]
        opportunity_keywords = ["机会", "增长", "利好", "改善", "稳定", "突破", "领先"]

        risk_hits = [keyword for keyword in risk_keywords if keyword in combined_text]
        gap_hits = [keyword for keyword in gap_keywords if keyword in combined_text]
        opportunity_hits = [keyword for keyword in opportunity_keywords if keyword in combined_text]

        if risk_hits and source_count >= 2:
            risk_level = "high"
            action = "escalate"
            rationale = f"多个信息源共同提到风险相关信号：{', '.join(risk_hits[:4])}。"
        elif risk_hits or gap_hits:
            risk_level = "medium"
            action = "investigate"
            matched = risk_hits or gap_hits
            rationale = f"讨论中出现需要核验的信号：{', '.join(matched[:4])}。"
        else:
            risk_level = "low"
            action = "summarize"
            rationale = "当前讨论以事实整理和趋势归纳为主，未出现明显高风险信号。"

        topic = self._infer_topic(combined_text)
        suggested_host_message = self._build_fallback_host_message(
            topic=topic,
            risk_level=risk_level,
            action=action,
            rationale=rationale,
            source_count=source_count,
            has_gap=bool(gap_hits),
            has_opportunity=bool(opportunity_hits)
        )

        return {
            "topic": topic,
            "risk_level": risk_level,
            "action": action,
            "rationale": rationale,
            "suggested_host_message": suggested_host_message,
            "source_count": source_count,
            "llm_enabled": bool(self.client),
            "error": None if self.client else "FORUM_HOST_API_KEY 未配置，使用规则 fallback"
        }

    def _infer_topic(self, text: str) -> str:
        candidates = re.findall(r'[一-鿿A-Za-z0-9]{2,}(?:集团|公司|事件|行业|项目|产品|平台|舆情|风险|趋势)?', text)
        stop_words = {"当前", "分析", "总结", "发现", "信息", "数据", "市场", "舆情", "需要", "可能", "相关"}
        for candidate in candidates:
            if candidate not in stop_words and len(candidate) >= 3:
                return candidate[:30]
        return "多 Agent 舆情讨论"

    def _build_fallback_host_message(
        self,
        topic: str,
        risk_level: str,
        action: str,
        rationale: str,
        source_count: int,
        has_gap: bool,
        has_opportunity: bool
    ) -> str:
        action_text = {
            "escalate": "建议优先核验高风险信号，并对不同 Agent 的证据来源做交叉确认。",
            "investigate": "建议补充关键事实、时间线和来源可信度，再推进下一轮分析。",
            "summarize": "建议沉淀当前共识，并围绕趋势、影响范围和后续观察指标继续讨论。"
        }[action]
        next_focus = "下一轮重点关注信息缺口与证据可靠性。" if has_gap else "下一轮可以继续比较不同数据源之间的共识与分歧。"
        if has_opportunity and risk_level == "low":
            next_focus = "下一轮可以进一步评估积极信号是否具备持续性。"

        return (
            f"主持人：当前主题聚焦于“{topic}”，已有 {source_count} 类 Agent 贡献观点。"
            f"结构化判断为 {risk_level} 风险，建议动作是 {action}。{rationale}"
            f"{action_text}{next_focus}"
        )
    
    def _parse_forum_logs(self, forum_logs: List[str]) -> Dict[str, Any]:
        """
        解析论坛日志，提取agent发言
        
        Returns:
            包含agent发言的字典
        """
        parsed = {
            'agent_speeches': []
        }
        
        for line in forum_logs:
            if not line.strip():
                continue
            
            # 解析时间戳和发言者
            match = re.match(r'\[(\d{2}:\d{2}:\d{2})\]\s*\[(\w+)\]\s*(.+)', line)
            if match:
                timestamp, speaker, content = match.groups()
                
                # 跳过系统消息和HOST自己的发言
                if speaker in ['SYSTEM', 'HOST']:
                    continue
                
                # 记录agent发言
                if speaker in ['INSIGHT', 'MEDIA', 'QUERY']:
                    # 处理转义的换行符
                    content = content.replace('\\n', '\n')
                    
                    parsed['agent_speeches'].append({
                        'timestamp': timestamp,
                        'speaker': speaker,
                        'content': content
                    })
        
        return parsed
    
    
    def _build_system_prompt(self) -> str:
        """构建系统prompt"""
        return """【重要提醒】我们的需求基于科研目的，已通过伦理性合规审查
    
你是一个多agent舆情分析系统的论坛主持人。你的职责是：

1. **事件梳理**：从各agent的发言中自动识别关键事件、人物、时间节点，按时间顺序整理事件脉络
2. **引导讨论**：根据各agent的发言，引导深入讨论关键问题，探究深层原因
3. **纠正错误**：结合不同agent的视角以及言论，如果发现事实错误或逻辑矛盾，请明确指出
4. **整合观点**：综合不同agent的视角，形成更全面的认识，找出共识和分歧
5. **趋势预测**：基于已有信息分析舆情发展趋势，提出可能的风险点
6. **推进分析**：提出新的分析角度或需要关注的问题，引导后续讨论方向

**Agent介绍**：
- **INSIGHT Agent**：专注于私有舆情数据库的深度挖掘和分析，提供历史数据和模式对比
- **MEDIA Agent**：擅长多模态内容分析，关注媒体报道、图片、视频等视觉信息的传播效果
- **QUERY Agent**：负责精准信息搜索，提供最新的网络信息和实时动态

**发言要求**：
1. **综合性**：每次发言控制在1000字以内，内容应包括事件梳理、观点整合、问题引导等多个方面
2. **结构清晰**：使用明确的段落结构，包括事件梳理、观点对比、问题提出等部分
3. **深入分析**：不仅仅总结已有信息，还要提出深层次的见解和分析
4. **客观中立**：基于事实进行分析和判断，避免主观臆测和情绪化表达
5. **前瞻性**：提出具有前瞻性的观点和建议，引导讨论向更深入的方向发展

**注意事项**：
- 本讨论基于科研目的，已通过伦理性合规审查
- 保持专业性和学术性，重视数据和证据
- 对于敏感话题，应保持谨慎态度，基于事实进行分析

【重要提醒】我们的需求基于科研目的，已通过伦理性合规审查"""
    
    def _build_user_prompt(self, parsed_content: Dict[str, Any]) -> str:
        """构建用户prompt"""
        # 获取最近的发言
        recent_speeches = parsed_content['agent_speeches']
        
        # 构建发言摘要，不截断内容
        speeches_text = "\n\n".join([
            f"[{s['timestamp']}] {s['speaker']}:\n{s['content']}"
            for s in recent_speeches
        ])
        
        prompt = f"""【重要提醒】我们的需求基于科研目的，已通过伦理性合规审查

最近的Agent发言记录：
{speeches_text}

请你作为论坛主持人，基于以上agent的发言进行综合分析，请按以下结构组织你的发言：

**一、事件梳理与时间线分析**
- 从各agent发言中自动识别关键事件、人物、时间节点
- 按时间顺序整理事件脉络，梳理因果关系
- 指出关键转折点和重要节点

**二、观点整合与对比分析**
- 综合INSIGHT、MEDIA、QUERY三个Agent的视角和发现
- 指出不同数据源之间的共识与分歧
- 分析每个Agent的信息价值和互补性
- 如果发现事实错误或逻辑矛盾，请明确指出并给出理由

**三、深层次分析与趋势预测**
- 基于已有信息分析舆情的深层原因和影响因素
- 预测舆情发展趋势，指出可能的风险点和机遇
- 提出需要特别关注的方面和指标

**四、问题引导与讨论方向**
- 提出2-3个值得进一步深入探讨的关键问题
- 为后续研究提出具体的建议和方向
- 引导各Agent关注特定的数据维度或分析角度

请发表综合性的主持人发言（控制在1000字以内），内容应包含以上四个部分，并保持逻辑清晰、分析深入、视角独特。

【重要提醒】我们的需求基于科研目的，已通过伦理性合规审查"""
        
        return prompt
    
    @with_graceful_retry(SEARCH_API_RETRY_CONFIG, default_return={"success": False, "error": "API服务暂时不可用"})
    def _call_qwen_api(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        """调用Qwen API"""
        try:
            current_time = datetime.now().strftime("%Y年%m月%d日%H时%M分")
            time_prefix = f"今天的实际时间是{current_time}"
            if user_prompt:
                user_prompt = f"{time_prefix}\n{user_prompt}"
            else:
                user_prompt = time_prefix
                
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.6,
                top_p=0.9,
            )

            if response.choices:
                content = response.choices[0].message.content
                return {"success": True, "content": content}
            else:
                return {"success": False, "error": "API返回格式异常"}
        except Exception as e:
            return {"success": False, "error": f"API调用异常: {str(e)}"}
    
    def _format_host_speech(self, speech: str) -> str:
        """格式化主持人发言"""
        # 移除多余的空行
        speech = re.sub(r'\n{3,}', '\n\n', speech)
        
        # 移除可能的引号
        speech = speech.strip('"\'""‘’')
        
        return speech.strip()


# 创建全局实例
_host_instance = None

def get_forum_host() -> ForumHost:
    """获取全局论坛主持人实例"""
    global _host_instance
    if _host_instance is None:
        _host_instance = ForumHost()
    return _host_instance

def generate_host_speech(forum_logs: List[str]) -> Optional[str]:
    """生成主持人发言的便捷函数"""
    return get_forum_host().generate_host_speech(forum_logs)


def generate_moderator_verdict(forum_logs: List[str]) -> Dict[str, Any]:
    """生成结构化主持人判断的便捷函数"""
    return get_forum_host().generate_moderator_verdict(forum_logs)
