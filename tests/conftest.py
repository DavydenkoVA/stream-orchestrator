from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.config import settings
from app.db import Base
from app.services.dynamic_prompt_service import DynamicPromptService
from app.services.router import RouterService


@pytest.fixture
def temp_prompts_dir(tmp_path: Path) -> Path:
    prompts_dir = tmp_path / "prompts"
    dynamic_dir = prompts_dir / "dynamic"
    dynamic_dir.mkdir(parents=True, exist_ok=True)

    prompt_files = {
        "chat_system.txt": "Ты чат-ассистент.",
        "chat_user_template.txt": "user={username}\ntext={text}\n{global_recent_block}",
        "dossier_system.txt": "Собери досье.",
        "dossier_user_template.txt": "target={username}\n{recent_block}\n{memory_block}",
        "weekly_movies_system.txt": "Список фильмов.",
        "weekly_movies_user_template.txt": "q={user_text}\n{file_content}",
        "user_memory_system.txt": "Извлеки память.",
        "user_memory_user_template.txt": "{username}\n{messages_block}",
        "dynamic/test_system.txt": "dynamic system",
        "dynamic/test_template.txt": "hello {user}, loot={loot}",
    }

    for rel, content in prompt_files.items():
        path = prompts_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    return prompts_dir


@pytest.fixture
def temp_llm_profiles(tmp_path: Path) -> Path:
    path = tmp_path / "llm_profiles.yml"
    path.write_text(
        """
providers:
  primary:
    provider: mock
    models:
      - name: model_a
        api_key: test-key-a
        base_url: https://example.invalid
        model: mock-a
      - name: model_b
        api_key: test-key-b
        base_url: https://example.invalid
        model: mock-b
feature_settings:
  chat:
    provider: primary
    temperature: 0.7
    max_output_tokens: 200
    style: default
  dossier:
    provider: primary
    temperature: 0.7
    max_output_tokens: 200
    style: default
  weekly_movies:
    provider: primary
    temperature: 0.7
    max_output_tokens: 200
    style: default
  dynamic_prompt:
    provider: primary
    temperature: 0.5
    max_output_tokens: 180
    style: default
  user_memory:
    provider: primary
    temperature: 0.1
    max_output_tokens: 220
    style: default
""".strip(),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def temp_styles_config(tmp_path: Path) -> Path:
    path = tmp_path / "llm_styles.yml"
    path.write_text(
        """
styles:
  default:
    title: По умолчанию
    instruction: ""
  fun:
    title: Веселый
    instruction: Добавь шутку.
  strict:
    title: Строгий
    instruction: Отвечай кратко и по делу.
""".strip(),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def temp_weekly_movies_file(tmp_path: Path) -> Path:
    file_path = tmp_path / "weekly_movies.txt"
    file_path.write_text("1) Movie A\n2) Movie B", encoding="utf-8")
    return file_path


@pytest.fixture(autouse=True)
def test_settings(
    monkeypatch: pytest.MonkeyPatch,
    temp_prompts_dir: Path,
    temp_llm_profiles: Path,
    temp_styles_config: Path,
    temp_weekly_movies_file: Path,
) -> None:
    monkeypatch.setattr(settings, "prompts_dir", str(temp_prompts_dir))
    monkeypatch.setattr(settings, "llm_profiles_config_path", str(temp_llm_profiles))
    monkeypatch.setattr(settings, "llm_styles_config_path", str(temp_styles_config))
    monkeypatch.setattr(settings, "weekly_movies_file", str(temp_weekly_movies_file))

    monkeypatch.setattr(settings, "user_memory_bootstrap_message_threshold", 2)
    monkeypatch.setattr(settings, "user_memory_min_unprocessed_messages", 2)
    monkeypatch.setattr(settings, "user_memory_extract_message_limit", 20)
    monkeypatch.setattr(settings, "user_memory_max_items_per_user", 3)
    monkeypatch.setattr(settings, "user_memory_min_confidence", 0.6)

    fresh_router = RouterService()
    monkeypatch.setattr("app.api.routes.service", fresh_router)
    monkeypatch.setattr(
        "app.api.routes.dynamic_prompt_service",
        DynamicPromptService(
            llm_registry=fresh_router.llm_registry,
            llm_executor=fresh_router.llm_executor,
            prompts=fresh_router.prompts,
            style_prompt=fresh_router.style_prompt,
        ),
    )


@pytest.fixture
def db_session(tmp_path: Path) -> Generator[Session, None, None]:
    db_file = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_file}", future=True)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
