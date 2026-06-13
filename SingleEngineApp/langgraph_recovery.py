"""Helpers for recovering LangGraph Streamlit runs after API failures."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]


RECOVERABLE_API_MARKERS = (
    "api key",
    "apikey",
    "invalid key",
    "invalid_api_key",
    "incorrect api key",
    "authentication",
    "authenticationerror",
    "unauthorized",
    "permission denied",
    "forbidden",
    "401",
    "403",
    "insufficient_quota",
    "quota_exceeded",
    "quota exceeded",
    "exceeded your current quota",
    "billing_hard_limit",
    "rate_limit_exceeded",
    "rate limit",
    "too many requests",
    "429",
    "apiconnectionerror",
    "api connection",
    "apitimeouterror",
    "api timeout",
    "failed to connect",
    "connection refused",
    "connection error",
    "connect timeout",
    "read timeout",
    "timed out",
    "max retries exceeded",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "ssl",
    "certificate",
    "proxy",
    "tavily",
    "bocha",
    "anspire",
    "余额不足",
    "额度不足",
    "额度",
    "限流",
    "鉴权",
    "认证",
    "密钥",
    "连接失败",
    "超时",
)


NON_RECOVERABLE_MARKERS = (
    "graphrecursionerror",
    "recursion limit",
    "data_inspection_failed",
    "datainspectionfailed",
    "content_filter",
    "content management policy",
)


def normalize_error_text(error: Any) -> str:
    """Return a compact text representation including exception type names."""
    if isinstance(error, BaseException):
        parts = [type(error).__name__, str(error)]
        cause = getattr(error, "__cause__", None) or getattr(error, "__context__", None)
        if cause is not None and cause is not error:
            parts.extend([type(cause).__name__, str(cause)])
        return " ".join(part for part in parts if part)
    return str(error or "")


def is_recoverable_api_error(error: Any) -> bool:
    """Return True when a failure is likely fixable by updating API settings."""
    text = normalize_error_text(error).lower()
    if not text:
        return False
    if any(marker in text for marker in NON_RECOVERABLE_MARKERS):
        return False
    return any(marker in text for marker in RECOVERABLE_API_MARKERS)


def choose_env_path(env_path: Optional[Path] = None) -> Path:
    """Match the project convention: cwd .env if present, otherwise root .env."""
    if env_path is not None:
        return Path(env_path)
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        return cwd_env
    return PROJECT_ROOT / ".env"


def _format_env_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return str(value)

    value_str = str(value)
    if "\n" in value_str or "#" in value_str or any(ch.isspace() for ch in value_str):
        escaped = value_str.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value_str


def persist_env_updates(updates: Mapping[str, Any], env_path: Optional[Path] = None) -> Path:
    """Persist non-empty updates into .env and mirror them into os.environ."""
    filtered = {key: value for key, value in updates.items() if value is not None and str(value) != ""}
    target_path = choose_env_path(env_path)
    lines: List[str] = []
    indices: Dict[str, int] = {}

    if target_path.exists():
        lines = target_path.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                indices[key] = idx

    for key, value in filtered.items():
        line = f"{key}={_format_env_value(value)}"
        if key in indices:
            lines[indices[key]] = line
        else:
            lines.append(line)
        os.environ[key] = str(value)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target_path


def merge_form_values(
    fields: Iterable[Mapping[str, Any]],
    submitted_values: Mapping[str, Any],
) -> Dict[str, Any]:
    """Merge submitted form values with current field values."""
    merged: Dict[str, Any] = {}
    for field in fields:
        key = str(field["key"])
        raw_value = submitted_values.get(key)
        if raw_value is not None and str(raw_value).strip() != "":
            merged[key] = str(raw_value).strip()
            continue

        current_value = field.get("value")
        if current_value is not None and str(current_value).strip() != "":
            merged[key] = current_value
    return merged


def missing_required_fields(
    fields: Iterable[Mapping[str, Any]],
    merged_values: Mapping[str, Any],
) -> List[str]:
    """Return labels for required fields that still have no usable value."""
    missing: List[str] = []
    for field in fields:
        key = str(field["key"])
        if field.get("required") and not str(merged_values.get(key, "") or "").strip():
            missing.append(str(field.get("label") or key))
    return missing


def render_api_recovery_form(
    *,
    form_key: str,
    engine_label: str,
    fields: List[Mapping[str, Any]],
    error_text: str,
    thread_id: Optional[str],
    submit_label: str,
) -> Optional[Dict[str, Any]]:
    """Render a Streamlit API recovery form and return merged values on submit."""
    import streamlit as st

    st.warning(f"{engine_label} 的 API 调用失败，可以更新配置后继续。")
    if thread_id:
        st.caption(f"Checkpoint Thread ID: `{thread_id}`")
    if error_text:
        with st.expander("错误摘要", expanded=False):
            st.code(error_text[:4000])

    submitted_values: Dict[str, Any] = {}
    with st.form(form_key):
        for field in fields:
            key = str(field["key"])
            label = str(field.get("label") or key)
            current_value = field.get("value")
            secret = bool(field.get("secret"))
            placeholder = "留空沿用当前配置" if current_value else ""
            options = field.get("options")
            if options:
                option_list = [str(option) for option in options]
                try:
                    index = option_list.index(str(current_value))
                except ValueError:
                    index = 0
                submitted_values[key] = st.selectbox(
                    label,
                    options=option_list,
                    index=index,
                    key=f"{form_key}_{key}",
                )
            elif secret:
                submitted_values[key] = st.text_input(
                    label,
                    value="",
                    type="password",
                    placeholder=placeholder,
                    key=f"{form_key}_{key}",
                )
            else:
                submitted_values[key] = st.text_input(
                    label,
                    value=str(current_value or ""),
                    key=f"{form_key}_{key}",
                )

        submitted = st.form_submit_button(submit_label)

    if not submitted:
        return None

    merged_values = merge_form_values(fields, submitted_values)
    missing = missing_required_fields(fields, merged_values)
    if missing:
        st.error("请补全配置: " + ", ".join(missing))
        return None

    updates = {
        key: value
        for key, value in submitted_values.items()
        if value is not None and str(value).strip() != ""
    }
    if updates:
        env_path = persist_env_updates(updates)
        try:
            import config as root_config

            root_config.reload_settings()
        except Exception:
            pass
        st.success(f"配置已保存到 {env_path}")

    return merged_values
