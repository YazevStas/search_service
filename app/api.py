from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    status,
)
from pydantic import Field, StringConstraints
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
SearchQuery = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
]
DocumentId = Annotated[int, Field(ge=1, le=2**63 - 1)]

UNAVAILABLE = {503: {"model": ErrorOut, "description": "Search index is unavailable"}}


@router.get(
    "/search",
    response_model=list[DocumentOut],
    summary="Search documents",
    description=(
        "Runs a full-text search over document texts in Elasticsearch, takes "
        "the 20 most relevant hits and returns them with all database fields, "
        "ordered by creation date."
    ),
    responses=UNAVAILABLE,
)
async def search(
    request: Request,
    session: SessionDep,
    index: IndexDep,
    query: Annotated[SearchQuery, Query(description="Search query")],
    order: Annotated[
        SortOrder, Query(description="Sort order by creation date")
    ] = SortOrder.desc,
) -> list[DocumentOut]:
    limit = request.app.state.settings.search_limit
    docs = await services.search_documents(session, index, query, limit, order)
    return [DocumentOut.model_validate(d) for d in docs]


@router.delete(
    "/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete document",
    description="Deletes a document from the database and the search index by id.",
    responses={
        404: {"model": ErrorOut, "description": "Document not found"},
        **UNAVAILABLE,
    },
)
async def delete(
    session: SessionDep,
    index: IndexDep,
    doc_id: Annotated[DocumentId, Path(description="Document id")],
) -> Response:
    if not await services.delete_document(session, index, doc_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
