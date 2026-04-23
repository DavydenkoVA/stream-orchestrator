import pathlib
import re
import string
import typing

from app.config import settings


_SIMPLE_FIELD_RE: typing.Final = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


@typing.final
class PromptStore:
    def __init__(
        self,
        base_directory: str | None = None,
        *,
        base_dir: str | None = None,
    ) -> None:
        self.base_directory = pathlib.Path(
            (base_directory if base_directory is not None else base_dir) or settings.prompts_dir
        )

    def _resolve_path(self, file_name: str) -> pathlib.Path:
        candidate_path: typing.Final = (self.base_directory / file_name).resolve()
        base_path: typing.Final = self.base_directory.resolve()
        if candidate_path != base_path and base_path not in candidate_path.parents:
            raise ValueError("Prompt path is outside prompt storage")
        return candidate_path

    def read_raw(self, file_name: str) -> str:
        prompt_path: typing.Final = self._resolve_path(file_name)
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
        return prompt_path.read_text(encoding="utf-8")

    def read(self, file_name: str) -> str:  # noqa: COP007
        return self.read_raw(file_name).strip()

    def write(self, file_name: str, file_content: str) -> None:  # noqa: COP007
        prompt_path: typing.Final = self._resolve_path(file_name)
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(file_content, encoding="utf-8")

    def _extract_required_fields(self, template_content: str, *, template_name: str) -> set[str]:
        required_fields: typing.Final[set[str]] = set()
        try:
            for _, field_name, _, _ in string.Formatter().parse(template_content):
                if field_name is None:
                    continue
                if not _SIMPLE_FIELD_RE.fullmatch(field_name):
                    raise ValueError(  # noqa: TRY301
                        f"Unsupported placeholder syntax in template '{template_name}': '{field_name}'"
                    )
                required_fields.add(field_name)
        except ValueError as exception_obj:
            raise ValueError(
                f"Invalid prompt template syntax for '{template_name}': {exception_obj}"
            ) from exception_obj
        return required_fields

    def get_required_fields(self, file_name: str) -> set[str]:
        return self._extract_required_fields(self.read(file_name), template_name=file_name)

    def render(self, file_name: str, **template_kwargs: object) -> str:  # noqa: COP007
        template_content: typing.Final = self.read(file_name)
        self._extract_required_fields(template_content, template_name=file_name)
        return template_content.format(**template_kwargs)
