# Document Search Service

Простой поисковик по текстам документов.

**Стек:** FastAPI (async) · PostgreSQL + SQLAlchemy 2 (asyncpg) · Elasticsearch 8 (AsyncElasticsearch) · pytest · Docker Compose.

## API

| Метод    | Путь                                  | Описание |
|----------|---------------------------------------|----------|
| `GET`    | `/documents/search?query=...&order=desc` | Полнотекстовый поиск: первые 20 релевантных документов со всеми полями БД, упорядоченные по `created_date` (`desc` по умолчанию, `asc` — опционально) |
| `DELETE` | `/documents/{id}`                     | Удаление документа из БД и индекса. `204` — удалён, `404` — не найден |
| `GET`    | `/health`                             | Healthcheck |

Документация OpenAPI лежит в `docs.json`. Интерактивная версия после запуска: http://localhost:8000/docs.

Пример:

```bash
curl "http://localhost:8000/documents/search?query=концерт"
curl -X DELETE "http://localhost:8000/documents/42"
```

## Быстрый старт (Docker)

1. Скачайте датасет и положите его в `data/posts.csv`.
   Ожидаемые колонки: `text`, `created_date`, `rubrics` (колонка `id` опциональна, иначе id генерирует БД).

2. Поднимите сервисы:

   ```bash
   docker compose up -d --build
   ```

   Сервис доступен на http://localhost:8000. Таблица и индекс создаются при старте автоматически.

3. Загрузите данные в БД и индекс:

   ```bash
   docker compose exec app python -m scripts.load_data /data/posts.csv --recreate
   ```

   `--recreate` пересоздаёт таблицу и индекс (удобно для повторной загрузки).

## Тесты

Функциональные тесты гоняются через HTTP-клиент по настоящим PostgreSQL и Elasticsearch
(отдельные БД `documents_test` и индекс `documents_test`, основные данные не затрагиваются):

```bash
docker compose --profile test run --rm --build tests
```

> БД `documents_test` создаётся init-скриптом при **первой** инициализации тома Postgres.
> Если том уже существовал до этого, создайте её вручную:
> `docker compose exec postgres createdb -U postgres documents_test`

## Локальный запуск без Docker для приложения

```bash
uv sync                                       # создаёт .venv и ставит зависимости из uv.lock
docker compose up -d postgres elasticsearch   # или свои инстансы
cp .env.example .env
uv run uvicorn app.main:app --reload
uv run python -m scripts.load_data data/posts.csv --recreate
uv run pytest -v
```

## Конфигурация (переменные окружения)

| Переменная          | По умолчанию |
|---------------------|--------------|
| `DATABASE_URL`      | `postgresql+asyncpg://postgres:postgres@localhost:5432/documents` |
| `ELASTICSEARCH_URL` | `http://localhost:9200` |
| `ES_INDEX`          | `documents` |
| `SEARCH_LIMIT`      | `20` |

## Устройство

```
app/
  main.py      # фабрика приложения, lifespan: подключения к PG и ES, создание таблицы/индекса
  api.py       # эндпоинты
  services.py  # бизнес-логика поиска и удаления
  search.py    # обёртка над индексом Elasticsearch
  models.py    # ORM-модель documents
  schemas.py   # pydantic-схемы ответа
  config.py    # настройки
scripts/
  load_data.py      # загрузка CSV в БД + bulk-индексация
  export_openapi.py # регенерация docs.json
tests/              # функциональные тесты
```

Решения:

- **Поиск.** В индексе хранятся только `id` и `text` (поле `text` с анализатором `russian`,
  поэтому «кошки» находят «кошка»). Из ES берутся id 20 самых релевантных документов, затем
  полные записи достаются из PostgreSQL одним запросом и сортируются по `created_date`.
- **Удаление.** Документ удаляется из БД в транзакции, затем из индекса; коммит происходит
  только если удаление из индекса прошло успешно, чтобы БД и индекс не расходились.
- **Загрузка.** Батчами: `INSERT ... RETURNING id` в БД, затем bulk в ES, затем коммит батча.
- Миграции не используются: схема из одной таблицы создаётся через `metadata.create_all`.

После изменения API обновите документацию: `uv run python -m scripts.export_openapi`.
