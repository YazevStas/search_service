"""Обёртка над поисковым индексом Elasticsearch."""
from collections.abc import Iterable

from elasticsearch import AsyncElasticsearch, BadRequestError, NotFoundError
from elasticsearch.helpers import async_bulk

INDEX_SETTINGS = {"number_of_shards": 1, "number_of_replicas": 0}
INDEX_MAPPINGS = {
    "properties": {
        "id": {"type": "long"},
        # встроенный анализатор со стеммингом для русского языка
        "text": {"type": "text", "analyzer": "russian"},
    }
}


class SearchIndex:
    def __init__(self, client: AsyncElasticsearch, name: str) -> None:
        self.client = client
        self.name = name

    async def ensure_index(self, recreate: bool = False) -> None:
        exists = bool(await self.client.indices.exists(index=self.name))
        if exists and recreate:
            await self.client.indices.delete(index=self.name)
            exists = False
        if not exists:
            try:
                await self.client.indices.create(
                    index=self.name, settings=INDEX_SETTINGS, mappings=INDEX_MAPPINGS
                )
            except BadRequestError as exc:  # индекс успели создать параллельно
                if exc.error != "resource_already_exists_exception":
                    raise

    async def search(self, query: str, size: int) -> list[int]:
        """Возвращает id наиболее релевантных документов."""
        resp = await self.client.search(
            index=self.name,
            query={"match": {"text": {"query": query}}},
            size=size,
            source=False,
        )
        return [int(hit["_id"]) for hit in resp["hits"]["hits"]]

    async def delete(self, doc_id: int) -> bool:
        """Удаляет документ; False, если его не было в индексе."""
        try:
            await self.client.delete(index=self.name, id=str(doc_id), refresh="wait_for")
        except NotFoundError:
            return False
        return True

    async def bulk_index(self, docs: Iterable[tuple[int, str]], refresh: bool = False) -> int:
        actions = (
            {"_index": self.name, "_id": str(doc_id), "_source": {"id": doc_id, "text": text}}
            for doc_id, text in docs
        )
        success, _ = await async_bulk(self.client, actions, refresh=refresh)
        return success
