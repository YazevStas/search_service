from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import services
from app.schemas import DocumentOut, ErrorOut, SortOrder
from app.search import SearchIndex

router = APIRouter(prefix="/documents", tags=["documents"])


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_index(request: Request) -> SearchIndex:
    return request.app.state.index


SessionDep = Annotated[AsyncSession, Depends(get_session)]
IndexDep = Annotated[SearchIndex, Depends(get_index)]


@router.get(
    "/search",
    response_model=list[DocumentOut],
    summary="Поиск документов",
    description=(
        "Ищет по тексту документов в индексе Elasticsearch, берёт первые 20 "
        "наиболее релевантных и возвращает их со всеми полями из БД, "
        "упорядоченными по дате создания."
    ),
)
async def search(
    request: Request,
    session: SessionDep,
    index: IndexDep,
    query: Annotated[str, Query(min_length=1, max_length=1000, description="Поисковый запрос")],
    order: Annotated[SortOrder, Query(description="Порядок сортировки по дате")] = SortOrder.desc,
) -> list[DocumentOut]:
    if not query.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Query must not be blank")
    limit = request.app.state.settings.search_limit
    docs = await services.search_documents(session, index, query, limit, order)
    return [DocumentOut.model_validate(d) for d in docs]


@router.delete(
    "/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удаление документа",
    description="Удаляет документ из БД и из поискового индекса по id.",
    responses={404: {"model": ErrorOut, "description": "Документ не найден"}},
)
async def delete(
    session: SessionDep,
    index: IndexDep,
    doc_id: Annotated[int, Path(ge=1, description="id документа")],
) -> Response:
    if not await services.delete_document(session, index, doc_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
