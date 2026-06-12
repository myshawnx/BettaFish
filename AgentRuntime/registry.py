"""JSONL-backed run registry and event bus for the portfolio agents.

The registry is deliberately small: it gives LangGraph agents, ForumEngine,
and MCP tools a shared observation surface without coupling the three engine
implementations to a database or a common base class.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
RUNS_FILENAME = "agent_runs.jsonl"
EVENTS_FILENAME = "agent_events.jsonl"
VALID_ENGINES = {"insight", "media", "query", "forum", "system"}
VALID_RUN_STATUSES = {"running", "completed", "failed"}
VALID_EVENT_STATUSES = {"ok", "error"}
_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _runtime_log_dir(log_dir: Optional[os.PathLike | str] = None) -> Path:
    configured = log_dir or os.environ.get("AGENT_RUNTIME_LOG_DIR")
    return Path(configured).resolve() if configured else DEFAULT_LOG_DIR


def _runs_path(log_dir: Optional[os.PathLike | str] = None) -> Path:
    return _runtime_log_dir(log_dir) / RUNS_FILENAME


def _events_path(log_dir: Optional[os.PathLike | str] = None) -> Path:
    return _runtime_log_dir(log_dir) / EVENTS_FILENAME


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(k): _json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_json_safe(item) for item in value]
        if isinstance(value, Path):
            return str(value)
        return str(value)


def _append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_json_safe(record), ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []

    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
    return records


def _run_id(engine: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"{engine}-{stamp}-{uuid.uuid4().hex[:8]}"


def _event_id(engine: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"evt-{engine}-{stamp}-{uuid.uuid4().hex[:8]}"


def _normalize_engine(engine: str) -> str:
    normalized = str(engine or "").strip().lower()
    return normalized if normalized in VALID_ENGINES else normalized or "system"


def _collapse_runs(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    collapsed: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for record in records:
        run_id = record.get("run_id")
        if not run_id:
            continue
        if run_id not in collapsed:
            order.append(run_id)
        collapsed[run_id] = record

    runs = [collapsed[run_id] for run_id in order]
    return sorted(
        runs,
        key=lambda item: item.get("finished_at") or item.get("started_at") or "",
        reverse=True,
    )


def start_run(
    engine: str,
    query: str,
    thread_id: str,
    checkpoint_path: Optional[str] = None,
    log_dir: Optional[os.PathLike | str] = None,
) -> Dict[str, Any]:
    """Append a new running run record and matching run_started event."""
    normalized_engine = _normalize_engine(engine)
    now = _now()
    run = {
        "run_id": _run_id(normalized_engine),
        "engine": normalized_engine,
        "query": str(query or ""),
        "thread_id": str(thread_id or ""),
        "status": "running",
        "checkpoint_path": str(checkpoint_path) if checkpoint_path else None,
        "final_report_path": None,
        "started_at": now,
        "finished_at": None,
        "error_summary": None,
        "updated_at": now,
    }
    try:
        with _LOCK:
            _append_jsonl(_runs_path(log_dir), run)
            record_event(
                engine=normalized_engine,
                run_id=run["run_id"],
                thread_id=run["thread_id"],
                event_type="run_started",
                status="ok",
                message="run started",
                payload={
                    "query": run["query"],
                    "checkpoint_path": run["checkpoint_path"],
                },
                log_dir=log_dir,
            )
    except Exception as exc:  # pragma: no cover - filesystem guard
        run["runtime_error"] = str(exc)
    return run


def record_event(
    engine: str,
    run_id: Optional[str],
    thread_id: Optional[str],
    event_type: str,
    node: Optional[str] = None,
    status: str = "ok",
    payload: Optional[Dict[str, Any]] = None,
    message: Optional[str] = None,
    log_dir: Optional[os.PathLike | str] = None,
) -> Dict[str, Any]:
    """Append one structured runtime event.

    The function returns the event even if the file append fails; callers should
    treat runtime tracing as best effort and never let it break agent execution.
    """
    normalized_engine = _normalize_engine(engine)
    event = {
        "event_id": _event_id(normalized_engine),
        "run_id": run_id,
        "engine": normalized_engine,
        "thread_id": thread_id,
        "event_type": str(event_type or "event"),
        "node": node,
        "status": status if status in VALID_EVENT_STATUSES else "ok",
        "message": message,
        "payload": _json_safe(payload or {}),
        "created_at": _now(),
    }
    try:
        with _LOCK:
            _append_jsonl(_events_path(log_dir), event)
    except Exception as exc:  # pragma: no cover - filesystem guard
        event["runtime_error"] = str(exc)
    return event


def finish_run(
    run_id: Optional[str],
    status: str,
    final_report_path: Optional[str] = None,
    error_summary: Optional[str] = None,
    log_dir: Optional[os.PathLike | str] = None,
) -> Dict[str, Any]:
    """Append a terminal run record and matching completed/failed event."""
    if not run_id:
        return {
            "success": False,
            "error": "run_id is required",
        }

    terminal_status = status if status in VALID_RUN_STATUSES else "failed"
    if terminal_status == "running":
        terminal_status = "completed"

    try:
        with _LOCK:
            runs = _collapse_runs(_read_jsonl(_runs_path(log_dir)))
            existing = next((run for run in runs if run.get("run_id") == run_id), {})
            updated = {
                **existing,
                "run_id": run_id,
                "status": terminal_status,
                "final_report_path": str(final_report_path) if final_report_path else existing.get("final_report_path"),
                "finished_at": _now(),
                "error_summary": error_summary,
                "updated_at": _now(),
            }
            _append_jsonl(_runs_path(log_dir), updated)
            record_event(
                engine=updated.get("engine", "system"),
                run_id=run_id,
                thread_id=updated.get("thread_id"),
                event_type="run_failed" if terminal_status == "failed" else "run_completed",
                status="error" if terminal_status == "failed" else "ok",
                message=error_summary or terminal_status,
                payload={"final_report_path": updated.get("final_report_path")},
                log_dir=log_dir,
            )
            return updated
    except Exception as exc:  # pragma: no cover - filesystem guard
        return {"success": False, "run_id": run_id, "error": str(exc)}


def list_runs(limit: int = 20, log_dir: Optional[os.PathLike | str] = None) -> List[Dict[str, Any]]:
    """Return the latest collapsed run records."""
    try:
        safe_limit = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        safe_limit = 20

    try:
        with _LOCK:
            runs = _collapse_runs(_read_jsonl(_runs_path(log_dir)))
    except Exception:
        return []
    return runs[:safe_limit]


def list_events(
    run_id: Optional[str] = None,
    engine: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 50,
    log_dir: Optional[os.PathLike | str] = None,
) -> List[Dict[str, Any]]:
    """Return matching runtime events in chronological order."""
    try:
        safe_limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        safe_limit = 50

    try:
        with _LOCK:
            events = _read_jsonl(_events_path(log_dir))
    except Exception:
        return []

    if run_id:
        events = [event for event in events if event.get("run_id") == run_id]
    if engine:
        normalized_engine = _normalize_engine(engine)
        events = [event for event in events if event.get("engine") == normalized_engine]
    if event_type:
        events = [event for event in events if event.get("event_type") == event_type]

    return events[-safe_limit:]


def get_runtime_status(log_dir: Optional[os.PathLike | str] = None) -> Dict[str, Any]:
    """Summarize latest runs and events for MCP/status surfaces."""
    runs = list_runs(limit=100, log_dir=log_dir)
    events = list_events(limit=200, log_dir=log_dir)
    latest_by_engine: Dict[str, Dict[str, Any]] = {}
    for run in reversed(runs):
        latest_by_engine[run.get("engine", "unknown")] = run

    event_counts: Dict[str, int] = {}
    for event in events:
        event_counts[event.get("event_type", "event")] = event_counts.get(event.get("event_type", "event"), 0) + 1

    active_runs = [run for run in runs if run.get("status") == "running"]
    failed_runs = [run for run in runs if run.get("status") == "failed"]
    log_dir_path = _runtime_log_dir(log_dir)
    return {
        "success": True,
        "run_count": len(runs),
        "active_run_count": len(active_runs),
        "failed_run_count": len(failed_runs),
        "latest_runs": runs[:10],
        "latest_by_engine": latest_by_engine,
        "latest_events": events[-20:],
        "event_counts": event_counts,
        "paths": {
            "log_dir": str(log_dir_path),
            "runs": str(_runs_path(log_dir)),
            "events": str(_events_path(log_dir)),
        },
    }


def _truncate_text(value: Any, max_chars: int = 2000) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...[truncated]"


def build_langgraph_payload(
    node: str,
    state: Optional[Dict[str, Any]],
    update: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Create a compact, stable event payload from a LangGraph node update."""
    state = state or {}
    update = update or {}
    payload: Dict[str, Any] = {
        "query": state.get("query") or update.get("query"),
        "current_paragraph_index": update.get(
            "current_paragraph_index",
            state.get("current_paragraph_index"),
        ),
        "current_reflection_count": update.get(
            "current_reflection_count",
            state.get("current_reflection_count"),
        ),
    }

    paragraphs = update.get("paragraphs") or state.get("paragraphs") or []
    if isinstance(paragraphs, list):
        payload["paragraph_count"] = len(paragraphs)
        idx = payload.get("current_paragraph_index")
        if isinstance(idx, int) and 0 <= idx < len(paragraphs) and isinstance(paragraphs[idx], dict):
            paragraph = paragraphs[idx]
            payload["paragraph_title"] = paragraph.get("title")
            payload["paragraph_order"] = paragraph.get("order")
            payload["paragraph_completed"] = paragraph.get("is_completed")
        if node == "generate_structure":
            payload["paragraph_titles"] = [
                paragraph.get("title")
                for paragraph in paragraphs[:10]
                if isinstance(paragraph, dict) and paragraph.get("title")
            ]

    search_results = update.get("current_search_results")
    if search_results is None:
        search_results = state.get("current_search_results")
    if isinstance(search_results, list):
        payload["search_results_count"] = len(search_results)
        payload["search_result_samples"] = [
            {
                "title": _truncate_text(item.get("title") or item.get("title_or_content") or item.get("content"), 200),
                "url": item.get("url"),
                "platform": item.get("platform"),
            }
            for item in search_results[:3]
            if isinstance(item, dict)
        ]

    for key in ("current_search_query", "current_search_tool"):
        value = update.get(key, state.get(key))
        if value:
            payload[key] = value

    summary = update.get("current_summary")
    if summary:
        payload["current_summary"] = _truncate_text(summary)

    if update.get("final_report"):
        final_report = str(update.get("final_report"))
        payload["final_report_length"] = len(final_report)
        payload["final_report_preview"] = _truncate_text(final_report, 1000)

    messages = update.get("messages")
    if messages:
        payload["messages"] = messages[-3:] if isinstance(messages, list) else [str(messages)]

    errors = update.get("errors")
    if errors:
        payload["errors"] = errors[-3:] if isinstance(errors, list) else [str(errors)]

    return {key: value for key, value in payload.items() if value is not None}
