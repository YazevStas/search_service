import os
from collections.abc import Awaitable, Callable
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.models import Base, Document


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url=os.getenv(
            "TEST_DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/documents_test",
        ),
        elasticsearch_url=os.getenv("TEST_ELASTICSEARCH_URL", "http://localhost:9200"),
        es_index=os.getenv("TEST_ES_INDEX", "documents_test"),
    )


@pytest_asyncio.fixture
async def app(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await app.state.index.ensure_index(recreate=True)
        yield app
        await app.state.es.indices.delete(index=settings.es_index, ignore_unavailable=True)


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


SeedFn = Callable[[list[dict]], Awaitable[list[Document]]]


@pytest_asyncio.fixture
async def seed(app) -> SeedFn:
    async def _seed(docs: list[dict]) -> list[Document]:
        async with app.state.sessionmaker() as session:
            objs = [
                Document(
                    text=d["text"],
                    rubrics=d.get("rubrics", ["VK-1"]),
                    created_date=d.get("created_date", datetime(2020, 1, 1)),
                )
                for d in docs
            ]
            session.add_all(objs)
            await session.commit()
        await app.state.index.bulk_index(((o.id, o.text) for o in objs), refresh=True)
        return objs

    return _seed
