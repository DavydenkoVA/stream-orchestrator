from pathlib import Path

from app.config import settings


class PromptStore:
    def __init__(self, base_dir: str | None = None) -> None:
        self.base_dir = Path(base_dir or settings.prompts_dir)

    def read(self, name: str) -> str:
        path = self.base_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Prompt file not found: {path}")
        return path.read_text(encoding="utf-8").strip()

    def render(self, name: str, **kwargs) -> str:
        template = self.read(name)
        return template.format(**kwargs)