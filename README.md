# Document Search Service

Простой поисковик по текстам документов.

**Стек:** FastAPI (async) · PostgreSQL + SQLAlchemy 2 (asyncpg) · Elasticsearch 8 (AsyncElasticsearch) · pytest · Docker Compose.

## API

| Метод    | Путь                                  | Описание |
|----------|---------------------------------------|----------|
| `GET`    | `/documents/search?query=...&order=desc` | Полнотекстовый поиск: первые 20 релевантных документов со всеми полями БД, упорядоченные по `created_date` (`desc` по умолчанию, `asc` — опционально). Пустой запрос или запрос из одних пробелов — `422` |
| `DELETE` | `/documents/{id}`                     | Удаление документа из БД и индекса. `204` — удалён, `404` — не найден, `422` — `id` не положительное целое |

Документация OpenAPI лежит в `docs.json`. Интерактивная версия после запуска: http://localhost:8000/docs.

Пример:

```bash
curl "http://localhost:8000/documents/search?query=концерт"
curl -X DELETE "http://localhost:8000/documents/42"
```

## Быстрый старт (Docker)

1. Скачайте датасет и положите его в `data/posts.csv`.
   Ожидаемые колонки: `text`, `created_date`, `rubrics` (колонка `id` опциональна, иначе id генерирует БД).

2. Создайте `.env` из шаблона и подставьте свои значения (логин, пароль, имя БД и индекса):

   ```bash
   cp .env.example .env
   ```

3. Поднимите сервисы:

   ```bash
   docker compose up -d --build
   ```

   Сервис доступен на http://localhost:8000. Таблица и индекс создаются при старте автоматически.

4. Загрузите данные в БД и индекс:

   ```bash
   docker compose exec app python -m scripts.load_data /data/posts.csv --recreate
   ```

   `--recreate` пересоздаёт таблицу и индекс. Без него строки добавляются к уже
   загруженным: если в CSV нет колонки `id`, повторный запуск создаст дубликаты.

## Тесты

Функциональные тесты гоняются через HTTP-клиент по настоящим PostgreSQL и Elasticsearch
(отдельные БД `<POSTGRES_DB>_test` и индекс `<ES_INDEX>_test`, основные данные не затрагиваются):

```bash
docker compose --profile test run --rm --build tests
```

> Тестовая БД создаётся скриптом `docker/init-test-db.sh` при **первой** инициализации тома Postgres.
> Если том уже существовал до этого, создайте её вручную:
> `docker compose exec postgres sh -c 'createdb -U "$POSTGRES_USER" "${POSTGRES_DB}_test"'`

## Разработка

Всё запускается только через Docker. Образ собирается в двух вариантах:
`prod` (сервис `app`, только `[project.dependencies]`) и `dev` (сервис `tests`,
плюс группа `dev` — pytest, ruff, isort, black).

Проверка и форматирование кода (исходники монтируются в контейнер, чтобы
форматеры могли их изменить):

```bash
docker compose --profile test run --rm -v "$PWD":/srv tests ruff check .
docker compose --profile test run --rm -v "$PWD":/srv tests sh -c "isort . && black ."
```

После изменения API обновите документацию `docs.json`:

```bash
docker compose --profile test run --rm -v "$PWD":/srv tests python -m scripts.export_openapi
```

## Конфигурация

Секреты и настройки подключения хранятся только в переменных окружения:

```
.env  ──►  docker-compose.yml (${VAR})  ──►  environment контейнеров  ──►  Settings (pydantic-settings)
```

- `.env` — реальные значения, лежит локально и в git не попадает (`.gitignore`).
- `.env.example` — тот же набор переменных с плейсхолдерами, коммитится как шаблон.
- `docker-compose.yml` не содержит значений: только `${VAR}`. Если переменная не задана,
  compose останавливается с ошибкой.
- Приложение при старте загружает переменные окружения в `app/config.py` (`Settings`).

| Переменная          | Описание |
|---------------------|----------|
| `POSTGRES_USER`     | пользователь Postgres |
| `POSTGRES_PASSWORD` | пароль Postgres |
| `POSTGRES_DB`       | имя основной БД (тестовая — `<POSTGRES_DB>_test`) |
| `POSTGRES_HOST`     | хост Postgres (`postgres` — имя сервиса в compose) |
| `POSTGRES_PORT`     | порт Postgres внутри сети compose (`5432`) |
| `ELASTICSEARCH_URL` | адрес Elasticsearch (`http://elasticsearch:9200`) |
| `ES_INDEX`          | имя индекса (тестовый — `<ES_INDEX>_test`) |
| `SEARCH_LIMIT`      | необязательная: сколько документов возвращает поиск, от `1` до `10000`, по умолчанию `20` |

Учётные данные Postgres применяются только при **первой** инициализации тома `pg_data`;
чтобы сменить их позже, пересоздайте том: `docker compose down -v` (данные будут удалены).

Postgres (порт `5433`, например для DB-клиента) и Elasticsearch (порт `9200`) доступны
только с этой машины: порты привязаны к `127.0.0.1`. Elasticsearch работает без
аутентификации (`xpack.security.enabled=false`), поэтому наружу его открывать нельзя.

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
docker/
  init-test-db.sh   # создание тестовой БД при первой инициализации Postgres
data/               # сюда кладётся posts.csv (монтируется в app как /data)
docs.json           # OpenAPI-документация
```

Решения:

- **Поиск.** В индексе хранятся только `id` и `text` (поле `text` с анализатором `russian`,
  поэтому «кошки» находят «кошка»). Из ES берутся id 20 самых релевантных документов, затем
  полные записи достаются из PostgreSQL одним запросом и сортируются по `created_date`.
- **Удаление.** Документ удаляется из БД в транзакции, затем из индекса; коммит происходит
  только если удаление из индекса прошло успешно, чтобы БД и индекс не расходились.
  Запрос не ждёт обновления индекса ES, поэтому отвечает сразу, а документ пропадает
  из поисковой выдачи в течение ~1 с (интервал `refresh_interval`).
- **Загрузка.** Батчами: `INSERT ... RETURNING id` в БД, затем bulk в ES, затем коммит батча.
  Если какой-то шаг падает, транзакция откатывается, а документы батча удаляются из индекса.
- Миграции не используются: схема из одной таблицы создаётся через `metadata.create_all`.
