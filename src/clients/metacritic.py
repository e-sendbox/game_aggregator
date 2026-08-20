from __future__ import annotations

import time

import requests


class MetacriticClient:
    def __init__(self, config: dict, logger) -> None:
        self.base_url = config["research"]["list_url"].rsplit("/", 3)[0]
        self.timeout = config["http"]["timeout"]
        self.pause = config["http"]["pause_between_requests"]
        self.retries = config["http"]["retries"]
        self.user_agent = config["http"]["user_agent"]
        self.logger = logger

    def get_slow(self, url: str) -> str:
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Language": "en-US,en;q=0.9",
        }
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = requests.get(url, headers=headers, timeout=self.timeout)
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as exc:
                last_error = exc
                self.logger.error(f"GET {url} attempt {attempt}/{self.retries}: {exc}")
                time.sleep(self.pause * attempt)
        raise RuntimeError(f"GET {url} failed after {self.retries} attempts: {last_error}")
