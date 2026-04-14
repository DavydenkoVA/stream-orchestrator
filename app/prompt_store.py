from pathlib import Path
import re
import string

from app.config import settings


_SIMPLE_FIELD_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class PromptStore:
    def __init__(self, base_dir: str | None = None) -> None:
        self.base_dir = Path(base_dir or settings.prompts_dir)

    def read(self, name: str) -> str:
        path = self.base_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Prompt file not found: {path}")
        return path.read_text(encoding="utf-8").strip()

    def _extract_required_fields(self, template: str, *, template_name: str) -> set[str]:
        fields: set[str] = set()
        try:
            for _, field_name, _, _ in string.Formatter().parse(template):
                if field_name is None:
                    continue
                if not _SIMPLE_FIELD_RE.fullmatch(field_name):
                    raise ValueError(
                        f"Unsupported placeholder syntax in template '{template_name}': '{field_name}'"
                    )
                fields.add(field_name)
        except ValueError as exc:
            raise ValueError(
                f"Invalid prompt template syntax for '{template_name}': {exc}"
            ) from exc
        return fields

    def get_required_fields(self, name: str) -> set[str]:
        template = self.read(name)
        return self._extract_required_fields(template, template_name=name)

    def render(self, name: str, **kwargs) -> str:
        template = self.read(name)
        self._extract_required_fields(template, template_name=name)
        return template.format(**kwargs)
