"""Генерирует docs.json из схемы приложения: python -m scripts.export_openapi"""

import json
from pathlib import Path

from app.main import app


def main() -> None:
    schema = app.openapi()
    schema["servers"] = [{"url": "http://localhost:8000"}]
    Path("docs.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("docs.json written")


if __name__ == "__main__":
    main()
