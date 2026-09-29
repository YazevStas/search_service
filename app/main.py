import logging
from contextlib import asynccontextmanager

from elasticsearch import AsyncElasticsearch, NotFoundError, TransportError
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import router
from app.config import Settings, get_settings
from app.models import Base
from app.search import SearchIndex

# uvicorn настраивает только свои логгеры, поэтому логам приложения нужен обработчик
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
# клиент ES пишет в INFO каждый HTTP-запрос — это шум
logging.getLogger("elastic_transport").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


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
        description="Simple full-text search over documents (PostgreSQL + Elasticsearch).",
        lifespan=lifespan,
    )
    app.include_router(router)

    async def search_unavailable(request: Request, exc: Exception) -> JSONResponse:
        logger.warning("Search index is unavailable: %r", exc)
        return JSONResponse(
            {"detail": "Search index is unavailable"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # TransportError — ES не отвечает (нет соединения, таймаут),
    # NotFoundError — индекса нет (отсутствие документа SearchIndex.delete обрабатывает сам)
    app.add_exception_handler(TransportError, search_unavailable)
    app.add_exception_handler(NotFoundError, search_unavailable)

    return app


app = create_app()
