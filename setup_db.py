"""Накатка схемы БД при установке. Идемпотентно: создаёт только отсутствующие таблицы.

Использование: python setup_db.py
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from src.db import Database


def main() -> None:
    config_path = os.environ.get("CONFIG_PATH", "config.yaml")
    with open(config_path, encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    url = config["db"]["url"]
    db = Database(url)
    # создать директорию БД, если её нет (свежий клон без data/)
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    db.init_schema()
    path = url.removeprefix("sqlite:///")
    print(f"База данных создана: {Path(path).resolve()}")


if __name__ == "__main__":
    main()
