# Stream Orchestrator

`stream-orchestrator` — локальный FastAPI-сервис для оркестрации LLM-сценариев стрим-чата + встроенная operator/admin console для ручной настройки, запуска сценариев и просмотра trace-ов.

Главный UI-вход в console: `http://127.0.0.1:8000/`.

## Что это за проект

Проект совмещает два слоя:

- **Backend/API** для ingest/reply/dynamic prompt, работы с памятью чата, досье и debug-эндпоинтами.
- **Operator Console** (server-rendered HTML + JS) для:
  - редактирования LLM-конфига,
  - управления styles,
  - запуска playground-сценариев,
  - просмотра trace runs и событий.

## Что уже реализовано

- FastAPI API (`/events/chat_ingest`, `/events/chat_reply`, `/events/dynamic_prompt`, debug/health).
- Operator Console с root entrypoint на `/` и sidebar-навигацией.
- Экран **LLM Config** (валидация и применение provider/feature settings).
- Экран **Styles** (редактирование style definitions).
- Экран **Playground** с вкладками:
  - `Chat Reply`
  - `Dynamic Prompt`
  - `Dossier`
- Редактирование prompt-блоков в Playground с autosave on blur.
- Helper routes для Playground (список/создание dynamic prompts, загрузка/сохранение prompt sources, dossier run, reset test data).
- Экран **Traces**: список запусков, детали, timeline событий, raw JSON.
- Trace link после запусков из Playground (через `X-Trace-Id` → `/traces?run_id=...`).
- SQLite + Alembic migrations.
- CI-проверки: `ruff`, `flake8`, `mypy`, `pytest`.

## Быстрый локальный запуск

### Требования

- Python 3.11+
- `uv`

### Шаги

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

После старта:

- Console: `http://127.0.0.1:8000/`
- Healthcheck: `http://127.0.0.1:8000/health`

> Приложение проверяет наличие таблиц в БД на старте и завершится с ошибкой, если миграции не применены.

## Operator Console

Console доступна по `GET /` (это же экран `LLM Config`).

### Основные экраны

- **LLM Config** (`/` и `/llm-config`)
  - редактирование providers/models и feature settings;
  - validate/apply через UI;
  - отображение metadata активного snapshot-а.

- **Styles** (`/styles`)
  - редактирование списка стилей;
  - `default` обязателен и не удаляется;
  - validate/apply через UI.

- **Playground** (`/playground`)
  - ручной запуск сценариев;
  - prompt editing для chat/dossier/dynamic prompt;
  - autosave prompt-редакторов при потере фокуса;
  - ссылка в Traces после выполнения запуска.

- **Traces** (`/traces`)
  - список trace runs;
  - фильтрация (limit / stream_id / status);
  - detail view с timeline событий и raw JSON run/event payload.

## Playground

`/playground` поддерживает 3 рабочих режима:

- **Chat Reply**
  - preview контекста через `/debug/context`;
  - запуск `/events/chat_reply`;
  - prompt-редакторы `chat_system.txt` и `chat_user_template.txt`.

- **Dynamic Prompt**
  - запуск `/events/dynamic_prompt`;
  - выбор существующего dynamic prompt;
  - создание нового prompt через helper route;
  - редактирование `dynamic/<name>_system.txt` и `dynamic/<name>_template.txt`.

- **Dossier**
  - запуск dossier-пайплайна через helper route;
  - prompt-редакторы `dossier_system.txt` и `dossier_user_template.txt`.

### Что важно про prompts в Playground

- Изменения в prompt textarea сохраняются через `/playground/api/prompts/save`.
- Сохранение выполняется автоматически на blur.
- Следующие запуски используют уже сохранённые prompt-файлы (чтение идёт из PromptStore/файловой директории prompts).

## Traces

Экран `/traces` предназначен для локальной инспекции выполнения:

- список запусков (`/traces/api/runs`);
- деталка конкретного запуска (`/traces/api/runs/{run_id}`);
- timeline events по run;
- raw JSON run и выбранного event payload.

Практический сценарий: выполнить запуск в Playground → открыть trace по ссылке `Open trace`.

## Styles: текущая модель

- Источник стилей — YAML-конфиг (`LLM_STYLES_CONFIG_PATH`, по умолчанию `config/llm_styles.yml`).
- `default` — обязательный style key.
- `random` — зарезервированная системная опция выбора стиля, не обычная CRUD-запись.
- Стили используются в селекторах LLM Config и Dynamic Prompt override.

## Конфигурация и файлы (source of truth)

Ниже — ключевые пути и их назначение по текущему коду.

- `config/llm_profiles.yml`
  - provider pools + feature settings;
  - редактируется через экран **LLM Config** (apply) или вручную;
  - путь задаётся `LLM_PROFILES_CONFIG_PATH`.

- `config/llm_styles.yml`
  - definitions стилей;
  - редактируется через экран **Styles** (apply) или вручную;
  - путь задаётся `LLM_STYLES_CONFIG_PATH`.

- `prompts/`
  - chat/dossier prompt-файлы и `prompts/dynamic/*`;
  - редактируются через Playground prompt editors или вручную;
  - путь задаётся `PROMPTS_DIR`.

- `data/sqlite/app.db`
  - SQLite база (путь по умолчанию через `DATABASE_URL`).

### Когда файлы могут создаваться автоматически

- При создании dynamic prompt в Playground создаются:
  - `prompts/dynamic/<name>_system.txt`
  - `prompts/dynamic/<name>_template.txt`
- При `Apply` в LLM Config/Styles целевые YAML-файлы создаются, если отсутствуют.

## Ключевые маршруты

### UI pages

- `GET /` → console root (LLM Config)
- `GET /llm-config`
- `GET /styles`
- `GET /playground`
- `GET /traces`

### Core API

- `GET /health`
- `POST /events/chat_ingest`
- `POST /events/chat_reply`
- `POST /events/dynamic_prompt`
- `GET /debug/context`
- `GET /debug/prompts/{name}`

### Playground helper routes

- `GET /playground/api/dynamic-prompts`
- `GET /playground/api/dynamic-prompts/{name}`
- `POST /playground/api/dynamic-prompts/create`
- `GET /playground/api/prompts/{scope}`
- `POST /playground/api/prompts/save`
- `POST /playground/api/dossier/run`
- `POST /playground/api/chat/reset-stream`

### Traces API

- `GET /traces/api/runs`
- `GET /traces/api/runs/{run_id}`

## Quality checks / CI

В CI настроены отдельные job-ы для lint/typecheck/tests с командами:

```bash
uv run ruff check --no-fix .
uv run ruff format --check .
uv run flake8 .
uv run mypy .
uv run pytest
```

Рекомендуется запускать тот же набор локально перед PR.

## Текущий статус и ограничения

- Проект ориентирован на локальный/dev контур; мутации конфигурации через admin routes разрешены только в `local/dev/test` окружениях.
- Встроенной auth/roles для console/API нет.
- Console и Playground — операторские инструменты поверх текущих API, а не отдельный production-grade control plane.
