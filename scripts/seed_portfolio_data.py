"""Seed deterministic portfolio demo data into the existing MindSpider tables."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import quote_plus

from sqlalchemy import MetaData, create_engine
from sqlalchemy.exc import SQLAlchemyError

from config import settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_PATH = PROJECT_ROOT / "sample_data" / "portfolio_insight_seed.json"

INSERT_ORDER = [
    "daily_topics",
    "daily_news",
    "topic_news_relation",
    "crawling_tasks",
    "weibo_note",
    "weibo_note_comment",
    "bilibili_video",
    "bilibili_video_comment",
    "xhs_note",
    "xhs_note_comment",
    "zhihu_content",
    "zhihu_comment",
]

IDENTITY_COLUMNS = {
    "daily_topics": "topic_id",
    "daily_news": "news_id",
    "topic_news_relation": ("topic_id", "news_id"),
    "crawling_tasks": "task_id",
    "weibo_note": "note_id",
    "weibo_note_comment": "comment_id",
    "bilibili_video": "video_id",
    "bilibili_video_comment": "comment_id",
    "xhs_note": "note_id",
    "xhs_note_comment": "comment_id",
    "zhihu_content": "content_id",
    "zhihu_comment": "comment_id",
}


def load_seed_data(path: Path = DEFAULT_DATA_PATH) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    tables = data.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("Seed file must contain a top-level 'tables' object.")
    return data


def count_seed_rows(data: Dict[str, Any]) -> int:
    return sum(len(rows) for rows in data.get("tables", {}).values())


def _normalize_sync_database_url(database_url: str) -> str:
    replacements = {
        "postgresql+asyncpg://": "postgresql+psycopg://",
        "postgresql://": "postgresql+psycopg://",
        "mysql+aiomysql://": "mysql+pymysql://",
        "mysql+asyncmy://": "mysql+pymysql://",
    }
    for source, target in replacements.items():
        if database_url.startswith(source):
            return database_url.replace(source, target, 1)
    return database_url


def build_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return _normalize_sync_database_url(database_url)

    dialect = (settings.DB_DIALECT or "postgresql").lower()
    host = settings.DB_HOST or "localhost"
    port = settings.DB_PORT or (5432 if dialect in {"postgresql", "postgres"} else 3306)
    user = settings.DB_USER or "bettafish"
    password = quote_plus(settings.DB_PASSWORD or "")
    db_name = settings.DB_NAME or "bettafish"

    if dialect in {"postgresql", "postgres"}:
        return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db_name}"
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{db_name}?charset={settings.DB_CHARSET}"


def _rows_for_table(data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
    rows = data.get("tables", {}).get(table_name, [])
    if not isinstance(rows, list):
        raise ValueError(f"Seed rows for table '{table_name}' must be a list.")
    return rows


def _reflect_tables(engine, table_names: Iterable[str]) -> Dict[str, Any]:
    metadata = MetaData()
    metadata.reflect(bind=engine, only=list(table_names))
    return {name: metadata.tables[name] for name in table_names if name in metadata.tables}


def _delete_seed_rows(conn, table, identity, rows: List[Dict[str, Any]]) -> int:
    if isinstance(identity, tuple):
        deleted = 0
        for row in rows:
            clauses = [table.c[column] == row[column] for column in identity if column in row]
            if len(clauses) == len(identity):
                result = conn.execute(table.delete().where(*clauses))
                deleted += result.rowcount or 0
        return deleted

    values = [row[identity] for row in rows if identity in row]
    if not values:
        return 0
    result = conn.execute(table.delete().where(table.c[identity].in_(values)))
    return result.rowcount or 0


def reset_seed_data(conn, reflected_tables: Dict[str, Any], data: Dict[str, Any]) -> int:
    deleted = 0
    for table_name in reversed(INSERT_ORDER):
        rows = _rows_for_table(data, table_name)
        if not rows or table_name not in reflected_tables:
            continue
        deleted += _delete_seed_rows(
            conn,
            reflected_tables[table_name],
            IDENTITY_COLUMNS[table_name],
            rows,
        )
    return deleted


def insert_seed_data(conn, reflected_tables: Dict[str, Any], data: Dict[str, Any]) -> int:
    inserted = 0
    for table_name in INSERT_ORDER:
        rows = _rows_for_table(data, table_name)
        if not rows:
            continue
        if table_name not in reflected_tables:
            raise RuntimeError(f"Required table '{table_name}' does not exist. Run MindSpider.schema.init_database first.")
        conn.execute(reflected_tables[table_name].insert(), rows)
        inserted += len(rows)
    return inserted


def seed_portfolio_data(data_path: Path = DEFAULT_DATA_PATH, reset: bool = False, dry_run: bool = False) -> Dict[str, int]:
    data = load_seed_data(data_path)
    if dry_run:
        return {"deleted": 0, "inserted": 0, "total_seed_rows": count_seed_rows(data)}

    table_names = [name for name in INSERT_ORDER if _rows_for_table(data, name)]
    engine = create_engine(build_database_url(), future=True, connect_args={"connect_timeout": 5})

    with engine.begin() as conn:
        reflected_tables = _reflect_tables(engine, table_names)
        deleted = reset_seed_data(conn, reflected_tables, data) if reset and not dry_run else 0
        inserted = 0 if dry_run else insert_seed_data(conn, reflected_tables, data)

    engine.dispose()
    return {"deleted": deleted, "inserted": inserted, "total_seed_rows": count_seed_rows(data)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed deterministic portfolio demo data.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH, help="Path to the seed JSON file.")
    parser.add_argument("--reset", action="store_true", help="Delete known portfolio seed rows before inserting.")
    parser.add_argument("--dry-run", action="store_true", help="Validate the seed file without connecting or inserting rows.")
    args = parser.parse_args()

    try:
        result = seed_portfolio_data(data_path=args.data, reset=args.reset, dry_run=args.dry_run)
    except SQLAlchemyError as exc:
        detail = str(exc).splitlines()[0]
        raise SystemExit(
            "Portfolio seed failed: database is unavailable or schema is not initialized. "
            f"Run `docker compose up -d db` and `python -m MindSpider.schema.init_database` first. Detail: {detail}"
        )
    print(
        "Portfolio seed complete: "
        f"deleted={result['deleted']} inserted={result['inserted']} "
        f"total_seed_rows={result['total_seed_rows']}"
    )


if __name__ == "__main__":
    main()
