from __future__ import annotations

import pathlib

import pytest

from src.db import Database
from src.services.parser_service import ParserService
from src.services.researcher_service import ResearcherService

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def config() -> dict:
    """Тестовый конфиг: файловая БД, без сети."""
    return {
        "research": {
            "list_url": "https://www.metacritic.com/browse/game/all/all/all-time/new/",
            "max_pages": 10,
        },
        "db": {"url": "sqlite://"},
        "http": {"timeout": 30, "pause_between_requests": 0, "retries": 1, "user_agent": "test"},
        "comments": {"limit": 20},
        "analyze": {"limit": 100, "workers": 2, "prompt": "analyze_batch.txt"},
        "letsplay": {"search_limit": 5, "max_age_days": 30, "summary_min_len": 200, "timeout": 5},
        "llm": {"base_url": "http://test", "model": "test-model", "timeout": 5, "prompts_dir": "prompts"},
        "logging": {"dir": "logs", "access_file": "access.log", "error_file": "error.log"},
    }


@pytest.fixture
def db(tmp_path, config) -> Database:
    """Файловая БД во временной папке (потоки ThreadPoolExecutor получают свои соединения)."""
    database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    database.init_schema()
    return database


class FakeLogger:
    """Заглушка логгера: собирает info/error в списки."""

    def __init__(self) -> None:
        self.infos: list[str] = []
        self.errors: list[str] = []
        self.activity_msgs: list[str] = []

    def info(self, message: str) -> None:
        self.infos.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def activity(self, message: str) -> None:
        self.activity_msgs.append(message)

    def close(self) -> None:
        pass


@pytest.fixture
def logger() -> FakeLogger:
    """Заглушка логгера."""
    return FakeLogger()


class FakeMc:
    """Заглушка HTTP-клиента: отдаёт HTML из фикстур по URL."""

    def __init__(self) -> None:
        self.base_url = "https://www.metacritic.com"
        self.calls: list[str] = []

    def get_slow(self, url: str) -> str:
        self.calls.append(url)
        if url.endswith("/game/"):
            return (FIXTURES / "home_page.html").read_text(encoding="utf-8")
        if "browse/game" in url:
            return (FIXTURES / "listing.html").read_text(encoding="utf-8")
        if "user-reviews" in url:
            return (FIXTURES / "user_reviews.html").read_text(encoding="utf-8")
        if "critic-reviews" in url:
            return (FIXTURES / "critic_reviews.html").read_text(encoding="utf-8")
        return (FIXTURES / "game_page.html").read_text(encoding="utf-8")


@pytest.fixture
def mc() -> FakeMc:
    """Заглушка HTTP-клиента."""
    return FakeMc()


class FakePw:
    """Заглушка Playwright-клиента: отдаёт HTML карточек отзывов."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_platform_options(self, url: str) -> list[str]:
        self.calls.append(url)
        return ["PC", "PlayStation 5"]

    async def get_reviews(self, url: str, platform_name: str, limit: int) -> str:
        self.calls.append(url)
        if "critic-reviews" in url:
            return (FIXTURES / "critic_reviews.html").read_text(encoding="utf-8")
        return (FIXTURES / "user_reviews.html").read_text(encoding="utf-8")


@pytest.fixture
def pw() -> FakePw:
    """Заглушка Playwright-клиента."""
    return FakePw()


class FakeOllama:
    """Заглушка LLM-клиента: возвращает ответы по имени промпта или ошибку."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.fail = False

    def ping(self) -> str:
        return "test-model"

    def summarize(self, prompt_name: str, game_title: str, game_description: str, comments: str,
                  extra: dict | None = None) -> str:
        self.calls.append((prompt_name, game_title, game_description, comments))
        if self.fail:
            raise RuntimeError("LLM down")
        if prompt_name == "letsplay_search.txt":
            return "elden ring letsplay"
        if prompt_name == "letsplay_pick.txt":
            return "abc123"
        if prompt_name == "letsplay_summary.txt":
            return ("Игра отличная. Боссы сложные, графика красивая, мир огромный. "
                    "Блогеру понравилась боевая система и исследование. "
                    "Из минусов — повторяющиеся подземелья и затянутый эндгейм. "
                    "В целом летсплей показывает игру с лучшей стороны, "
                    "рекомендуется к просмотру всем фанатам жанра. " * 3)
        return "Что хорошо:\n- отлично\nЧто плохо:\n- скучно\nОсобенности игры:\n- инди"


@pytest.fixture
def ollama() -> FakeOllama:
    """Заглушка LLM-клиента."""
    return FakeOllama()


class FakeYtDlp:
    """Заглушка yt-dlp: возвращает фиксированные ролики и субтитры."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def search(self, query: str, limit: int) -> list[dict]:
        self.calls.append(f"search:{query}")
        return [{
            "video_id": "abc123",
            "title": "Elden Ring Letsplay",
            "channel": "TestChannel",
            "views": 1000,
            "upload_date": "20260801",
            "url": "https://www.youtube.com/watch?v=abc123",
        }]

    def get_video(self, video_id: str) -> dict:
        self.calls.append(f"video:{video_id}")
        return {
            "video_id": video_id,
            "title": "Elden Ring Letsplay",
            "channel": "TestChannel",
            "views": 1000,
            "upload_date": "20260801",
            "url": f"https://www.youtube.com/watch?v={video_id}",
        }

    def get_transcript(self, video_id: str) -> str:
        self.calls.append(f"transcript:{video_id}")
        return "Это текст субтитров летсплея. Игра отличная, боссы сложные, графика красивая."


@pytest.fixture
def ytdlp() -> FakeYtDlp:
    """Заглушка yt-dlp."""
    return FakeYtDlp()


@pytest.fixture
def service(config, db, mc, logger, pw, ollama, ytdlp) -> ResearcherService:
    """ResearcherService с заглушками вместо сети."""
    return ResearcherService(config, db, mc, logger, pw, ollama, ytdlp)


@pytest.fixture
def parser() -> ParserService:
    """Парсер без состояния."""
    return ParserService()
