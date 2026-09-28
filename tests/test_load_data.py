import csv
from datetime import datetime

import pytest
from sqlalchemy import func, select

from app.models import Document
from scripts.load_data import load, load_batch, parse_rubrics, read_rows


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("['VK-1', 'VK-2']", ["VK-1", "VK-2"]),
        ("[]", []),
        ("", []),
        ("VK-1, VK-2", ["VK-1", "VK-2"]),
    ],
)
def test_parse_rubrics(raw, expected):
    assert parse_rubrics(raw) == expected


def test_read_rows(tmp_path):
    path = tmp_path / "posts.csv"
    path.write_text(
        '\ufeffText,Created_Date,Rubrics,id\n"line one\nline two",'
        "2019-07-25 12:42:13,\"['VK-1']\",7\n",
        encoding="utf-8",
    )

    assert list(read_rows(path)) == [
        {
            "text": "line one\nline two",
            "created_date": datetime(2019, 7, 25, 12, 42, 13),
            "rubrics": ["VK-1"],
            "id": 7,
        }
    ]


def make_batch(n: int) -> list[dict]:
    return [
        {"text": f"пост номер {i}", "created_date": datetime(2020, 1, 1), "rubrics": []}
        for i in range(n)
    ]


async def count_docs(app) -> tuple[int, int]:
    async with app.state.sessionmaker() as session:
        in_db = await session.scalar(select(func.count()).select_from(Document))
    await app.state.es.indices.refresh(index=app.state.index.name)
    in_index = (await app.state.es.count(index=app.state.index.name))["count"]
    return in_db, in_index


async def test_load_batch_rolls_back_index_on_db_failure(app, monkeypatch):
    async with app.state.sessionmaker() as session:

        async def fail() -> None:
            raise RuntimeError("commit failed")

        monkeypatch.setattr(session, "commit", fail)

        with pytest.raises(RuntimeError):
            await load_batch(session, app.state.index, make_batch(3))

    assert await count_docs(app) == (0, 0)


async def test_load(app, settings, tmp_path):
    path = tmp_path / "posts.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["text", "created_date", "rubrics"])
        for i in range(5):
            writer.writerow([f"пост {i}", "2019-07-25 12:42:13", "['VK-1']"])

    # батчи по 2: два полных и один неполный
    await load(path, batch_size=2, recreate=False, settings=settings)

    assert await count_docs(app) == (5, 5)
