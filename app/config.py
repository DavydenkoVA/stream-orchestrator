from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "sqlite"
DEFAULT_DB_PATH = DATA_DIR / "app.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"

    database_url: str = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"

    llm_provider: str = "mock"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""

    llm_timeout_seconds: int = 30
    llm_temperature: float = 0.7
    llm_max_output_tokens: int = 400

    twitch_message_limit: int = 450
    prompts_dir: str = str(BASE_DIR / "prompts")

    chat_global_context_limit: int = 20
    chat_user_context_limit: int = 8
    chat_dialog_context_limit: int = 12

    bot_username: str = "stream_bot"

    streamerbot_base_url: str = "http://127.0.0.1:7474"
    streamerbot_auth_token: str = ""

    obs_ws_url: str = "ws://127.0.0.1:4455"
    obs_ws_password: str = ""

    weekly_movies_file: str = ""

settings = Settings()