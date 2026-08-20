from __future__ import annotations

import os
from datetime import datetime, timezone


class RunLogger:
    def __init__(self, log_dir: str, access_file: str, error_file: str,
                 activity_file: str = "activity.log") -> None:
        os.makedirs(log_dir, exist_ok=True)
        self.access_path = os.path.join(log_dir, access_file)
        self.error_path = os.path.join(log_dir, error_file)
        self.activity_path = os.path.join(log_dir, activity_file)
        self.access_fh = open(self.access_path, "a", encoding="utf-8")
        self.error_fh = open(self.error_path, "a", encoding="utf-8")
        self.activity_fh = open(self.activity_path, "a", encoding="utf-8")

    @staticmethod
    def _ts() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def info(self, message: str) -> None:
        self.access_fh.write(f"{self._ts()} INFO  {message}\n")
        self.access_fh.flush()

    def error(self, message: str) -> None:
        self.error_fh.write(f"{self._ts()} ERROR {message}\n")
        self.error_fh.flush()

    def activity(self, message: str) -> None:
        self.activity_fh.write(f"{self._ts()} {message}\n")
        self.activity_fh.flush()

    def close(self) -> None:
        for fh in (self.access_fh, self.error_fh, self.activity_fh):
            if not fh.closed:
                fh.close()
