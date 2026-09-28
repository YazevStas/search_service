from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document
from app.schemas import SortOrder
from app.search import SearchIndex


async def search_documents(
    session: AsyncSession,
    index: SearchIndex,
    query: str,
    limit: int,
    order: SortOrder = SortOrder.desc,
) -> list[Document]:
    """Takes the `limit` most relevant documents from the index
    and returns them from the database, ordered by creation date."""
    ids = await index.search(query, limit)
    if not ids:
        return []
    date_col = (
        Document.created_date.asc()
        if order is SortOrder.asc
        else Document.created_date.desc()
    )
    stmt = select(Document).where(Document.id.in_(ids)).order_by(date_col, Document.id)
    return list((await session.scalars(stmt)).all())


async def delete_document(
    session: AsyncSession, index: SearchIndex, doc_id: int
) -> bool:
    """Deletes a document from the database and the index. The database
    deletion is committed only after the index deletion succeeds."""
    doc = await session.get(Document, doc_id)
    if doc is not None:
        await session.delete(doc)
        await session.flush()
    try:
        in_index = await index.delete(doc_id)
    except Exception:
        await session.rollback()
        raise
    await session.commit()
    return doc is not None or in_index
