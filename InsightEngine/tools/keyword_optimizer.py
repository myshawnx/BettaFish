"""
Keyword optimization helper for InsightEngine database search.

Importing this module must be safe without API keys. When the optional keyword
optimizer key is missing, the optimizer falls back to deterministic local token
extraction.
"""

import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger
from openai import OpenAI

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from config import settings  # noqa: E402

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(current_dir))
utils_dir = os.path.join(root_dir, "utils")
if utils_dir not in sys.path:
    sys.path.append(utils_dir)

from retry_helper import SEARCH_API_RETRY_CONFIG, with_graceful_retry  # noqa: E402


@dataclass
class KeywordOptimizationResponse:
    original_query: str
    optimized_keywords: List[str]
    reasoning: str
    success: bool
    error_message: str = ""


class KeywordOptimizer:
    """Optional LLM-backed keyword optimizer with deterministic fallback."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self.api_key = api_key or settings.KEYWORD_OPTIMIZER_API_KEY
        self.base_url = base_url or settings.KEYWORD_OPTIMIZER_BASE_URL
        self.model = model_name or settings.KEYWORD_OPTIMIZER_MODEL_NAME
        self.client = None
        if self.api_key:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def optimize_keywords(self, original_query: str, context: str = "") -> KeywordOptimizationResponse:
        logger.info(f"Keyword optimizer received query: {original_query}")

        if not self.client:
            keywords = self._fallback_keyword_extraction(original_query)
            return KeywordOptimizationResponse(
                original_query=original_query,
                optimized_keywords=keywords,
                reasoning="Keyword optimizer API key is not configured; using local fallback.",
                success=True,
            )

        try:
            response = self._call_qwen_api(
                self._build_system_prompt(),
                self._build_user_prompt(original_query, context),
            )
            if response["success"]:
                keywords, reasoning = self._parse_response(response["content"])
                validated_keywords = self._validate_keywords(keywords)
                if validated_keywords:
                    return KeywordOptimizationResponse(
                        original_query=original_query,
                        optimized_keywords=validated_keywords,
                        reasoning=reasoning,
                        success=True,
                    )

            fallback_keywords = self._fallback_keyword_extraction(original_query)
            return KeywordOptimizationResponse(
                original_query=original_query,
                optimized_keywords=fallback_keywords,
                reasoning="Keyword optimizer API failed; using local fallback.",
                success=True,
                error_message=response.get("error", ""),
            )
        except Exception as exc:
            fallback_keywords = self._fallback_keyword_extraction(original_query)
            return KeywordOptimizationResponse(
                original_query=original_query,
                optimized_keywords=fallback_keywords,
                reasoning="Keyword optimizer error; using local fallback.",
                success=False,
                error_message=str(exc),
            )

    def _build_system_prompt(self) -> str:
        return (
            "You optimize user queries into concise social-media database search "
            "keywords. Return JSON with keys: keywords, reasoning. Keep keywords "
            "short, concrete, and non-duplicative."
        )

    def _build_user_prompt(self, original_query: str, context: str) -> str:
        prompt = f"Original query: {original_query}"
        if context:
            prompt += f"\nContext: {context}"
        return prompt

    @with_graceful_retry(
        SEARCH_API_RETRY_CONFIG,
        default_return={"success": False, "error": "Keyword optimizer service unavailable"},
    )
    def _call_qwen_api(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        if not self.client:
            return {"success": False, "error": "Keyword optimizer API key is not configured"}

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )
            if response.choices:
                return {"success": True, "content": response.choices[0].message.content}
            return {"success": False, "error": "Unexpected API response"}
        except Exception as exc:
            return {"success": False, "error": f"API call failed: {exc}"}

    def _parse_response(self, content: str) -> tuple[List[str], str]:
        content = (content or "").strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?", "", content).strip()
            content = re.sub(r"```$", "", content).strip()

        try:
            parsed = json.loads(content)
            keywords = parsed.get("keywords", [])
            reasoning = parsed.get("reasoning", "")
            if isinstance(keywords, str):
                keywords = [keywords]
            return list(keywords), str(reasoning)
        except Exception:
            return self._extract_keywords_from_text(content), content

    def _extract_keywords_from_text(self, text: str) -> List[str]:
        tokens = re.split(r"[\s,;:，。；：、]+", text or "")
        return self._validate_keywords(tokens)

    def _validate_keywords(self, keywords: List[str]) -> List[str]:
        seen = set()
        validated = []
        for keyword in keywords:
            if not isinstance(keyword, str):
                continue
            cleaned = keyword.strip().strip("\"'")
            if not cleaned or len(cleaned) > 30 or cleaned in seen:
                continue
            seen.add(cleaned)
            validated.append(cleaned)
            if len(validated) >= 20:
                break
        return validated

    def _fallback_keyword_extraction(self, original_query: str) -> List[str]:
        keywords = self._extract_keywords_from_text(original_query)
        if keywords:
            return keywords
        return [original_query.strip()] if original_query.strip() else ["hot topic"]


keyword_optimizer = KeywordOptimizer()
