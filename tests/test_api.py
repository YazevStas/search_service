from datetime import datetime, timedelta

import pytest_asyncio
from elasticsearch import AsyncElasticsearch
from sqlalchemy import select

from app.models import Document


async def test_search_returns_all_db_fields(client, seed):
    [doc] = await seed(
        [
            {
                "text": "Сегодня в городе прошёл концерт",
                "rubrics": ["VK-1", "VK-2"],
                "created_date": datetime(2019, 12, 8, 6, 24, 46),
            }
        ]
    )
    await seed([{"text": "Совсем другой текст про погоду"}])

    resp = await client.get("/documents/search", params={"query": "концерт"})

    assert resp.status_code == 200
    assert resp.json() == [
        {
            "id": doc.id,
            "rubrics": ["VK-1", "VK-2"],
            "text": "Сегодня в городе прошёл концерт",
            "created_date": "2019-12-08T06:24:46",
        }
    ]


async def test_search_orders_by_created_date(client, seed):
    base = datetime(2020, 1, 1)
    await seed(
        [
            {"text": "новость номер один", "created_date": base + timedelta(days=1)},
            {"text": "новость номер два", "created_date": base + timedelta(days=3)},
            {"text": "новость номер три", "created_date": base + timedelta(days=2)},
        ]
    )

    desc = (await client.get("/documents/search", params={"query": "новость"})).json()
    asc = (
        await client.get(
            "/documents/search", params={"query": "новость", "order": "asc"}
        )
    ).json()

    desc_dates = [d["created_date"] for d in desc]
    assert len(desc) == 3
    assert desc_dates == sorted(desc_dates, reverse=True)
    assert [d["created_date"] for d in asc] == sorted(desc_dates)


async def test_search_limit_is_20(client, seed):
    await seed([{"text": f"документ про котов {i}"} for i in range(25)])

    resp = await client.get("/documents/search", params={"query": "котов"})

    assert resp.status_code == 200
    assert len(resp.json()) == 20


async def test_search_uses_russian_morphology(client, seed):
    [doc] = await seed([{"text": "У меня живёт кошка"}])

    resp = await client.get("/documents/search", params={"query": "кошки"})

    assert [d["id"] for d in resp.json()] == [doc.id]


async def test_search_no_results(client, seed):
    await seed([{"text": "что-то совсем иное"}])

    resp = await client.get("/documents/search", params={"query": "абракадабра"})

    assert resp.status_code == 200
    assert resp.json() == []


async def test_search_requires_query(client):
    assert (await client.get("/documents/search")).status_code == 422
    assert (
        await client.get("/documents/search", params={"query": ""})
    ).status_code == 422
    assert (
        await client.get("/documents/search", params={"query": "   "})
    ).status_code == 422


async def test_delete_removes_from_db_and_index(app, client, seed, caplog):
    keep, remove = await seed(
        [{"text": "первый пост о спорте"}, {"text": "второй пост о спорте"}]
    )

    resp = await client.delete(f"/documents/{remove.id}")
    assert resp.status_code == 204
    assert f"Document {remove.id} deleted" in caplog.messages
    # удаление станет видно поиску после следующего обновления индекса
    await app.state.es.indices.refresh(index=app.state.index.name)

    found = (await client.get("/documents/search", params={"query": "пост"})).json()
    assert [d["id"] for d in found] == [keep.id]

    async with app.state.sessionmaker() as session:
        ids = (await session.scalars(select(Document.id))).all()
    assert ids == [keep.id]

    hits = await app.state.index.search("пост", 20)
    assert hits == [keep.id]


@pytest_asyncio.fixture
async def break_index(app, monkeypatch):
    """Возвращает функцию, которая направляет индекс на порт, где никто не слушает."""
    dead = AsyncElasticsearch("http://127.0.0.1:1", max_retries=0)
    yield lambda: monkeypatch.setattr(app.state.index, "client", dead)
    await dead.close()


async def test_delete_keeps_document_if_index_is_down(app, client, seed, break_index):
    [doc] = await seed([{"text": "важный документ"}])
    break_index()

    resp = await client.delete(f"/documents/{doc.id}")

    assert resp.status_code == 503
    assert resp.json() == {"detail": "Search index is unavailable"}
    async with app.state.sessionmaker() as session:
        assert await session.get(Document, doc.id) is not None


async def test_delete_missing_document_returns_404(client, seed):
    [doc] = await seed([{"text": "одноразовый"}])
    assert (await client.delete(f"/documents/{doc.id}")).status_code == 204

    resp = await client.delete(f"/documents/{doc.id}")

    assert resp.status_code == 404
    assert resp.json() == {"detail": "Document not found"}


async def test_delete_invalid_id(client):
    assert (await client.delete("/documents/abc")).status_code == 422
    assert (await client.delete("/documents/0")).status_code == 422
    # не помещается в BIGINT
    assert (await client.delete(f"/documents/{2**63}")).status_code == 422
