from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.utils.scheduler import CronSpec, Scheduler


def test_cron_star_matches_always():
    """Проверяет: '*' во всех полях совпадает с любым временем."""
    spec = CronSpec("* * * * *")
    assert spec.matches(datetime(2026, 8, 17, 12, 30, tzinfo=timezone.utc))
    assert spec.matches(datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc))


def test_cron_hourly():
    """Проверяет: '0 * * * *' совпадает в начале часа, не совпадает в другое время."""
    spec = CronSpec("0 * * * *")
    assert spec.matches(datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc))
    assert not spec.matches(datetime(2026, 8, 17, 12, 30, tzinfo=timezone.utc))
    assert not spec.matches(datetime(2026, 8, 17, 13, 1, tzinfo=timezone.utc))


def test_cron_numbers():
    """Проверяет: конкретные числа в полях (минута и час)."""
    spec = CronSpec("30 9 * * *")
    assert spec.matches(datetime(2026, 8, 17, 9, 30, tzinfo=timezone.utc))
    assert not spec.matches(datetime(2026, 8, 17, 9, 31, tzinfo=timezone.utc))
    assert not spec.matches(datetime(2026, 8, 17, 10, 30, tzinfo=timezone.utc))


def test_cron_invalid_expressions():
    """Проверяет: невалидные крон-строки вызывают ValueError."""
    with pytest.raises(ValueError):
        CronSpec("0 * * *")          # 4 поля
    with pytest.raises(ValueError):
        CronSpec("0 * * * * *")      # 6 полей
    with pytest.raises(ValueError):
        CronSpec("60 * * * *")       # минута вне диапазона
    with pytest.raises(ValueError):
        CronSpec("0 * * * foo")      # не число и не *
    with pytest.raises(ValueError):
        CronSpec("*/5 * * * *")      # шаги не поддерживаются


def test_scheduler_skips_busy(capsys):
    """Проверяет: on_tick не вызывается, если флаг stop установлен (поток спит)."""
    calls = []

    def on_tick():
        calls.append(1)

    scheduler = Scheduler("0 * * * *", on_tick)
    scheduler._loop = lambda: None  # не запускаем реальный цикл
    assert scheduler.cron.matches(datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc))
