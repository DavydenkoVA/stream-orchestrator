from pathlib import Path


class WeeklyMoviesFileService:
    def __init__(self, file_path: str) -> None:
        self.file_path = Path(file_path)

    def read_raw(self) -> dict:
        if not self.file_path:
            return {
                "found": False,
                "content": "",
                "message": "Путь к файлу списка фильмов не задан.",
            }

        if not self.file_path.exists():
            return {
                "found": False,
                "content": "",
                "message": f"Файл не найден: {self.file_path}",
            }

        content = self.file_path.read_text(encoding="utf-8").strip()

        if not content:
            return {
                "found": True,
                "content": "",
                "message": "Список фильмов на эту неделю пока пуст.",
            }

        return {
            "found": True,
            "content": content,
            "message": None,
        }