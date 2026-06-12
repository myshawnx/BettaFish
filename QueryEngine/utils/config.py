"""
Configuration management for QueryEngine.

Importing this module must not require external secrets. Real QueryEngine
execution still validates API keys when the LLM client and search tool are
constructed.
"""

from pathlib import Path
from typing import Optional

from loguru import logger
from pydantic import Field
from pydantic_settings import BaseSettings


PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
CWD_ENV: Path = Path.cwd() / ".env"
ENV_FILE: str = str(CWD_ENV if CWD_ENV.exists() else (PROJECT_ROOT / ".env"))


class Settings(BaseSettings):
    """QueryEngine settings loaded from environment variables and .env."""

    QUERY_ENGINE_API_KEY: Optional[str] = Field(None, description="QueryEngine LLM API key")
    QUERY_ENGINE_BASE_URL: Optional[str] = Field(None, description="QueryEngine OpenAI-compatible base URL")
    QUERY_ENGINE_MODEL_NAME: Optional[str] = Field(None, description="QueryEngine LLM model name")
    QUERY_ENGINE_PROVIDER: Optional[str] = Field(None, description="Optional provider label")

    TAVILY_API_KEY: Optional[str] = Field(None, description="Tavily API key")

    SEARCH_TIMEOUT: int = Field(240, description="Search timeout in seconds")
    SEARCH_CONTENT_MAX_LENGTH: int = Field(20000, description="Maximum search content length for prompts")
    MAX_REFLECTIONS: int = Field(2, description="Maximum reflection rounds")
    MAX_PARAGRAPHS: int = Field(5, description="Maximum report paragraphs")
    MAX_SEARCH_RESULTS: int = Field(20, description="Maximum search results")

    OUTPUT_DIR: str = Field("reports", description="Output directory")
    SAVE_INTERMEDIATE_STATES: bool = Field(True, description="Whether to save intermediate states")

    class Config:
        env_file = ENV_FILE
        env_prefix = ""
        case_sensitive = False
        extra = "allow"


settings = Settings()


def print_config(config: Settings):
    """Log a redacted QueryEngine configuration summary."""
    message = ""
    message += "=== QueryEngine config ===\n"
    message += f"LLM model: {config.QUERY_ENGINE_MODEL_NAME or '(unset)'}\n"
    message += f"LLM base URL: {config.QUERY_ENGINE_BASE_URL or '(default)'}\n"
    message += f"Tavily API key: {'configured' if config.TAVILY_API_KEY else 'missing'}\n"
    message += f"Search timeout: {config.SEARCH_TIMEOUT}s\n"
    message += f"Search content max length: {config.SEARCH_CONTENT_MAX_LENGTH}\n"
    message += f"Max reflections: {config.MAX_REFLECTIONS}\n"
    message += f"Max paragraphs: {config.MAX_PARAGRAPHS}\n"
    message += f"Max search results: {config.MAX_SEARCH_RESULTS}\n"
    message += f"Output dir: {config.OUTPUT_DIR}\n"
    message += f"Save intermediate states: {config.SAVE_INTERMEDIATE_STATES}\n"
    message += f"LLM API key: {'configured' if config.QUERY_ENGINE_API_KEY else 'missing'}\n"
    message += "==========================\n"
    logger.info(message)
