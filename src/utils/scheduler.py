from __future__ import annotations

import threading
import time
from datetime import datetime, timezone


class CronSpec:
    """Мини-парсер крон-строки (5 полей: минута час день месяц день-недели, `*` и числа)."""

    def __init__(self, expr: str) -> None:
        parts = expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"invalid cron expression {expr!r}: expected 5 fields, got {len(parts)}")
        self.minute = self._parse(parts[0], 0, 59)
        self.hour = self._parse(parts[1], 0, 23)
        self.day = self._parse(parts[2], 1, 31)
        self.month = self._parse(parts[3], 1, 12)
        self.weekday = self._parse(parts[4], 0, 7)

    @staticmethod
    def _parse(field: str, low: int, high: int) -> set[int]:
        if field == "*":
            return set(range(low, high + 1))
        if field.isdigit() and low <= int(field) <= high:
            return {int(field)}
        raise ValueError(f"invalid cron field {field!r} (expected * or {low}-{high})")

    def matches(self, dt: datetime) -> bool:
        return (
            dt.minute in self.minute
            and dt.hour in self.hour
            and dt.day in self.day
            and dt.month in self.month
            and dt.weekday() in self.weekday
        )


class Scheduler:
    """Фоновый поток: раз в минуту проверяет совпадение с расписанием и вызывает on_tick."""

    def __init__(self, expr: str, on_tick) -> None:
        self.cron = CronSpec(expr)
        self.on_tick = on_tick
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = datetime.now(timezone.utc)
            if self.cron.matches(now):
                self.on_tick()
            self._stop.wait(60)
