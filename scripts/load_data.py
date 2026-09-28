"""Загружает CSV в PostgreSQL и индексирует его в Elasticsearch.

Использование:
    python -m scripts.load_data data/posts.csv [--recreate] [--batch-size 1000]

Ожидаемые колонки CSV: text, created_date, rubrics (id — опционально).
"""

import argparse
import ast
import asyncio
import csv
import sys
from collections.abc import Iterator, Sequence
from datetime import datetime
from itertools import batched
from pathlib import Path

from elasticsearch import AsyncElasticsearch
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings
from app.models import Base, Document
from app.search import SearchIndex

csv.field_size_limit(sys.maxsize)


def parse_rubrics(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        return [str(r) for r in ast.literal_eval(raw)]
    return [r.strip() for r in raw.split(",") if r.strip()]


def read_rows(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            row = {k.strip().lower(): v for k, v in row.items() if k}
            item = {
                "text": row["text"],
                "created_date": datetime.fromisoformat(row["created_date"].strip()),
                "rubrics": parse_rubrics(row.get("rubrics", "")),
            }
            if row.get("id"):
                item["id"] = int(row["id"])
            yield item


async def load_batch(
    session: AsyncSession, index: SearchIndex, batch: Sequence[dict]
) -> None:
    """Записывает батч в БД и индекс. Если любой шаг падает, транзакция
    в БД откатывается, а батч удаляется из индекса, чтобы хранилища
    не расходились."""
    ids: list[int] = []
    try:
        result = await session.execute(
            insert(Document).returning(Document.id, Document.text), batch
        )
        rows = result.all()
        ids = [r.id for r in rows]
        await index.bulk_index((r.id, r.text) for r in rows)
        await session.commit()
    except BaseException:
        await session.rollback()
        if ids:
            await index.bulk_delete(ids)
        raise


async def load(path: Path, batch_size: int, recreate: bool, settings: Settings) -> None:
    engine = create_async_engine(settings.database_url)
    es = AsyncElasticsearch(settings.elasticsearch_url, request_timeout=60)
    index = SearchIndex(es, settings.es_index)
    try:
        async with engine.begin() as conn:
            if recreate:
                await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await index.ensure_index(recreate=recreate)

        total = 0
        sessionmaker = async_sessionmaker(engine)
        async with sessionmaker() as session:
            for batch in batched(read_rows(path), batch_size):
                await load_batch(session, index, batch)
                total += len(batch)
                print(f"loaded {total}", flush=True)
            # если id пришли из CSV, сдвигаем sequence за максимальный id
            await session.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('documents', 'id'), "
                    "COALESCE((SELECT MAX(id) FROM documents), 1))"
                )
            )
            await session.commit()
        await es.indices.refresh(index=settings.es_index)
        print(f"done: {total} documents")
    finally:
        await es.close()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument(
        "--recreate", action="store_true", help="recreate the table and the index"
    )
    args = parser.parse_args()
    asyncio.run(load(args.csv_path, args.batch_size, args.recreate, get_settings()))


if __name__ == "__main__":
    main()
