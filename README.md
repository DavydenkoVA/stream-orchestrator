# LLM Stream Orchestrator

## Назначение проекта

`stream-orchestrator` — локальный FastAPI-сервис для оркестрации LLM-ответов в контексте стрим-чата.

Основные задачи:
- приём событий чата;
- хранение истории сообщений;
- маршрутизация встроенных сценариев (`chat`, `dossier`, `weekly_movies`);
- выполнение динамических prompt-сценариев через отдельный API;
- формирование контекста для модели;
- вызов LLM через настраиваемые provider/profile-конфиги;
- возврат ответа, пригодного для отправки в чат.

Сервис **не управляет сценами, OBS и Streamer.bot напрямую**. Он принимает события и возвращает результат обработки.

---

## Что уже есть

- FastAPI API для ingest / reply / debug / dynamic prompt
- SQLite + Alembic миграции
- история чата и выборка контекста
- user memory для накопления фактов о пользователях
- генерация досье по накопленным данным
- file-based сценарий `weekly_movies`
- профили LLM в YAML-конфиге
- стили ответов в отдельном YAML-конфиге
- prompt-файлы, подгружаемые с диска без изменения кода
- тесты на `pytest`

---

## Архитектура

### Основные компоненты

- **API (FastAPI)** — принимает HTTP-события и отдаёт результат
- **RouterService** — оркестрирует встроенные chat-сценарии
- **FeatureSelector / handlers** — определяют, какой встроенный сценарий обработает сообщение
- **ChatMemoryService** — сохраняет сообщения и подготавливает контекст
- **UserMemoryService** — извлекает и обновляет долговременную память по пользователю
- **DossierService** — строит контекст для досье
- **DynamicPromptService** — выполняет произвольные prompt-сценарии с ручным набором входных данных
- **PromptStore** — читает system/user prompt-файлы
- **LLMRegistry** — загружает provider pools и feature settings из YAML
- **LLMExecutionService** — вызывает модель и обрабатывает failover по пулу моделей
- **StylePromptService** — применяет стиль ответа к system prompt
- **File readers** — читают внешние данные, например список weekly movies

---

## Потоки обработки

### 1. Ingest

`POST /events/chat_ingest`

Назначение:
- сохранить входящее сообщение в БД;
- не вызывать LLM;
- использоваться как отдельный канал накопления истории.

### 2. Reply

`POST /events/chat_reply`

Логика:
1. сохранить сообщение;
2. выбрать встроенный сценарий;
3. собрать нужный контекст;
4. вызвать LLM или deterministic-обработку;
5. вернуть текст ответа и выбранный route.

Встроенные сценарии на текущем этапе:
- `dossier`
- `weekly_movies`
- `chat`
- `ignored`

### 3. Dynamic Prompt

`POST /events/dynamic_prompt`

Отдельный механизм для явно вызываемых prompt-сценариев.

Используется, когда внешний оркестратор сам знает, какой prompt нужно выполнить, и передаёт:
- имя prompt-а;
- пользователя;
- произвольный `data` payload;
- при необходимости override параметров LLM.

### 4. Debug

- `GET /debug/context` — показывает контекст, который уйдёт в модель
- `GET /debug/prompts/{name}` — возвращает содержимое prompt-файла
- `GET /health` — healthcheck

---

## Структура prompt-сценариев

### Встроенные chat-сценарии

Используются в `RouterService` и вызываются автоматически через `/events/chat_reply`.

Текущие prompt-файлы:
- `prompts/chat_system.txt`
- `prompts/chat_user_template.txt`
- `prompts/dossier_system.txt`
- `prompts/dossier_user_template.txt`
- `prompts/weekly_movies_system.txt`
- `prompts/weekly_movies_user_template.txt`
- `prompts/user_memory_system.txt`
- `prompts/user_memory_user_template.txt`

### Dynamic Prompt сценарии

Хранятся в каталоге `prompts/dynamic/` и именуются так:
- `prompts/dynamic/<name>_system.txt`
- `prompts/dynamic/<name>_template.txt`

Пример:
- `prompts/dynamic/test_system.txt`
- `prompts/dynamic/test_template.txt`

Такой сценарий вызывается через `/events/dynamic_prompt`.

---

## Конфигурация

### `.env`

Базовые runtime-настройки лежат в `.env`.

Пример:

```env
APP_ENV=dev
APP_HOST=127.0.0.1
APP_PORT=8000
LOG_LEVEL=INFO

DATABASE_URL=sqlite:///./data/sqlite/app.db

LLM_TIMEOUT_SECONDS=30
LLM_TEMPERATURE=0.7
LLM_MAX_OUTPUT_TOKENS=400

TWITCH_MESSAGE_LIMIT=450
PROMPTS_DIR=./prompts

LLM_PROFILES_CONFIG_PATH=./config/llm_profiles.yml
LLM_STYLES_CONFIG_PATH=./config/llm_styles.yml

USER_MEMORY_BOOTSTRAP_MESSAGE_THRESHOLD=10
USER_MEMORY_MIN_UNPROCESSED_MESSAGES=50
USER_MEMORY_EXTRACT_MESSAGE_LIMIT=80
USER_MEMORY_MAX_ITEMS_PER_USER=12
USER_MEMORY_MIN_CONFIDENCE=0.6

CHAT_GLOBAL_CONTEXT_LIMIT=20
CHAT_USER_CONTEXT_LIMIT=8
CHAT_DIALOG_CONTEXT_LIMIT=12

BOT_USERNAME=stream_bot

STREAMERBOT_BASE_URL=http://127.0.0.1:7474
STREAMERBOT_AUTH_TOKEN=

OBS_WS_URL=ws://127.0.0.1:4455
OBS_WS_PASSWORD=

WEEKLY_MOVIES_FILE=
```

### `config/llm_profiles.yml`

Отдельный YAML-конфиг для:
- provider pools;
- моделей внутри провайдера;
- feature settings.

Через него настраиваются:
- какой provider используется для `chat`, `dossier`, `weekly_movies`, `dynamic_prompt`, `user_memory`;
- temperature;
- max output tokens;
- style.

### `config/llm_styles.yml`

Отдельный YAML-конфиг для стилей ответа.

Стиль применяется к system prompt через `StylePromptService`.

---

## База данных

Используется SQLite.

Схема БД ведётся через **Alembic миграции**.

Рабочая модель:
- приложение не должно полагаться на runtime `create_all()` как на основной механизм управления схемой;
- перед запуском нужно применить миграции;
- для уже существующей старой БД можно выполнить её принятие в Alembic через `stamp head`.

### Основной запуск

Если используется Windows-скрипт проекта:

```bat
start.bat
```

Он делает:
1. создание `.venv`, если её ещё нет;
2. создание каталога `data/sqlite`, если его ещё нет;
3. `uv sync`;
4. `uv run alembic upgrade head`;
5. запуск `uvicorn`.

### Принятие уже существующей БД

Если БД уже существует и её нужно привязать к текущей голове миграций:

```bat
adopt_existing_db.bat
```

Или вручную:

```bash
uv run alembic stamp head
```

### Ручной запуск без `.bat`

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

---

## Установка

### Требования

- Python 3.11+
- `uv`
- SQLite

### Установка зависимостей

```bash
uv venv
uv sync
```

---

## Примеры API

### Ingest

```bash
curl -X POST http://127.0.0.1:8000/events/chat_ingest \
  -H "Content-Type: application/json" \
  -d '{
    "stream_id": "main-stream",
    "username": "alice",
    "text": "всем привет",
    "mentions_bot": false,
    "role": "viewer"
  }'
```

### Reply

```bash
curl -X POST http://127.0.0.1:8000/events/chat_reply \
  -H "Content-Type: application/json" \
  -d '{
    "stream_id": "main-stream",
    "username": "alice",
    "text": "@stream_bot что смотрим в воскресенье?",
    "mentions_bot": true,
    "role": "viewer"
  }'
```

### Dynamic Prompt

```bash
curl -X POST http://127.0.0.1:8000/events/dynamic_prompt \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "test",
    "user": "alice",
    "data": {
      "loot": "coins"
    }
  }'
```

---

## Context / Memory

### Контекст чата

Для chat-сценария используются:
- `global_recent` — последние сообщения чата;
- `user_recent` — недавние сообщения конкретного пользователя;
- `dialog_recent` — недавний диалог пользователь ↔ бот.

Лимиты задаются через:
- `CHAT_GLOBAL_CONTEXT_LIMIT`
- `CHAT_USER_CONTEXT_LIMIT`
- `CHAT_DIALOG_CONTEXT_LIMIT`

### User Memory

User memory — это отдельный слой долговременных фактов о пользователях.

Используется для:
- досье;
- персонализированных ответов в будущем.

Текущее поведение:
- память извлекается из накопленных сообщений пользователя;
- извлечение запускается по threshold-правилам;
- память хранит `kind`, `text`, `evidence_count`, `confidence`;
- количество memory items на пользователя ограничивается настройками.

---

## File-based сценарии

Сейчас основной file-based сценарий — `weekly_movies`.

### Принцип работы

1. встроенный router определяет intent;
2. сервис читает файл;
3. делает отдельный LLM-запрос;
4. использует отдельные prompts.

### Формат файла

Допустим простой текст:

```text
Alien
The Thing
Event Horizon
```

Допустима строка с метаданными:

```text
Alien | added_by=alice
```

### Поведение

- файл пуст → бот сообщает об этом;
- файл заполнен → бот перечисляет содержимое;
- файл не найден → бот сообщает об ошибке.

---

## Ограничение длины ответа

Ответ обрезается через `prepare_chat_text()` до `TWITCH_MESSAGE_LIMIT`.

Это нужно, чтобы укладываться в ограничения платформы чата.

---

## Streamer.bot интеграция

В проекте есть примеры интеграции со Streamer.bot в каталоге `examples/streamer.bot/`.

Типичный сценарий:
- внешний sender отправляет chat events в `/events/chat_ingest`;
- отдельный sender или automation вызывает `/events/chat_reply` или `/events/dynamic_prompt`;
- оркестратор возвращает уже готовый ответ.

`stream_id` уже присутствует в контрактах как задел под разделение нескольких потоков/стримов, даже если локально сейчас часто используется константное значение.

---

## Debug и отладка

### Проверка контекста

```bash
curl "http://127.0.0.1:8000/debug/context?stream_id=main-stream&username=alice&text=hello"
```

Это позволяет:
- увидеть, что реально уйдёт в модель;
- проверить лимиты контекста;
- понять, какие сообщения попали в выборку.

### Проверка prompt-файла

```bash
curl http://127.0.0.1:8000/debug/prompts/chat_system.txt
```

---

## Тесты

В проекте есть каталог `tests/` с `pytest`-фикстурами и тестами.

Запуск:

```bash
uv run pytest
```

Тестовый контур использует:
- временную SQLite БД;
- временные prompt-файлы;
- временные YAML-конфиги профилей и стилей.

---

## Расширение проекта

### Когда добавлять встроенный route

Через `FeatureSelector` / `RouterService` имеет смысл добавлять только сценарии, которые:
- должны определяться автоматически из chat message;
- естественно живут внутри `/events/chat_reply`.

### Когда использовать `dynamic_prompt`

Через `/events/dynamic_prompt` лучше добавлять сценарии, которые:
- вызываются явно внешним оркестратором;
- требуют кастомного набора входных данных;
- не должны усложнять встроенный auto-router.

Это текущий основной путь расширения для кастомной бизнес-логики без разрастания встроенных chat-intents.

---

## Ограничения текущей реализации

На текущем этапе стоит считать актуальными следующие ограничения:
- нет полноценной дедупликации сообщений;
- нет RAG / векторной базы;
- нет UI для безопасного редактирования YAML-конфигов;
- встроенный auto-router intentionally небольшой и не должен разрастаться под все сценарии;
- observability / trace UI ещё требует отдельного развития.

---

## Рекомендации по эксплуатации

- не перегружать общий chat prompt;
- для новых внешних сценариев сначала рассматривать `dynamic_prompt`, а не новый встроенный handler;
- применять миграции до запуска сервиса;
- держать `llm_profiles.yml` и `llm_styles.yml` под version control;
- использовать deterministic-логику там, где важна точность выше гибкости модели.

---

## Итог

Проект уже является рабочей базой для локального LLM-оркестратора стрим-чата:
- ingest / reply / debug / dynamic prompt API;
- контекстная память чата;
- user memory и досье;
- file-based сценарии;
- конфигурируемые профили моделей и стили;
- миграции и тестовый контур.

Следующий естественный уровень развития:
- UI для безопасного редактирования конфигов;
- улучшенная observability;
- аккуратное развитие dynamic prompt-сценариев;
- дальнейшее усиление memory / routing / validation контуров.
