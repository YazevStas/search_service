from contextlib import asynccontextmanager

from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import router
from app.config import Settings, get_settings
from app.models import Base
from app.search import SearchIndex


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        es = AsyncElasticsearch(settings.elasticsearch_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        index = SearchIndex(es, settings.es_index)
        await index.ensure_index()

        app.state.settings = settings
        app.state.engine = engine
        app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        app.state.es = es
        app.state.index = index
        try:
            yield
        finally:
            await es.close()
            await engine.dispose()

    app = FastAPI(
        title="Document Search Service",
        version="1.0.0",
        description="Простой поисковик по текстам документов (PostgreSQL + Elasticsearch).",
        lifespan=lifespan,
    )
    app.include_router(router)

    @app.get("/health", tags=["service"], summary="Проверка работоспособности")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
