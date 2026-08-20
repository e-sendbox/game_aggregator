from __future__ import annotations

import json
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


class YtDlpClient:
    """Обёртка над yt-dlp: поиск роликов, проверка, скачивание авто-субтитров."""

    def __init__(self, config: dict, logger) -> None:
        self.logger = logger
        self.timeout = config.get("letsplay", {}).get("timeout", 120)

    def _run(self, args: list[str]) -> str:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        if result.returncode != 0:
            error = self._clean_stderr(result.stderr)
            raise RuntimeError(f"yt-dlp failed: {error[:500]}")
        return result.stdout

    @staticmethod
    def _clean_stderr(stderr: str) -> str:
        """Убирает шумные предупреждения (Deprecated Feature и др.), оставляет реальную ошибку."""
        lines = []
        for line in stderr.splitlines():
            if "Deprecated Feature" in line:
                continue
            if line.startswith("WARNING:"):
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    def search(self, query: str, limit: int) -> list[dict]:
        """Поиск роликов: ytsearchN:<query> → список с полями."""
        out = self._run([
            "yt-dlp", "--simulate", "--no-warnings",
            "--print", "%(id)s|%(title)s|%(channel)s|%(view_count)s|%(upload_date)s",
            f"ytsearch{limit}:{query}",
        ])
        results = []
        for line in out.splitlines():
            parts = line.split("|")
            if len(parts) < 5:
                continue
            video_id, title, channel, views, upload_date = parts[:5]
            results.append({
                "video_id": video_id,
                "title": title,
                "channel": channel,
                "views": int(views) if views and views.isdigit() else None,
                "upload_date": upload_date or None,
                "url": f"https://www.youtube.com/watch?v={video_id}",
            })
        return results

    def get_video(self, video_id: str) -> dict:
        """Данные конкретного ролика."""
        out = self._run([
            "yt-dlp", "--simulate", "--no-warnings",
            "--print", "%(id)s|%(title)s|%(channel)s|%(view_count)s|%(upload_date)s",
            f"https://www.youtube.com/watch?v={video_id}",
        ])
        parts = out.split("|")
        if len(parts) < 5:
            raise RuntimeError(f"yt-dlp: unexpected output for {video_id}")
        return {
            "video_id": parts[0],
            "title": parts[1],
            "channel": parts[2],
            "views": int(parts[3]) if parts[3].isdigit() else None,
            "upload_date": parts[4] or None,
            "url": f"https://www.youtube.com/watch?v={parts[0]}",
        }

    def get_transcript(self, video_id: str) -> str:
        """Авто-субтитры ролика → plain text."""
        with tempfile.TemporaryDirectory() as tmp:
            out_path = str(Path(tmp) / "sub.%(ext)s")
            self._run([
                "yt-dlp", "--skip-download", "--no-warnings",
                "--write-auto-subs", "--sub-langs", "en",
                "--sub-format", "srt",
                "-o", out_path,
                f"https://www.youtube.com/watch?v={video_id}",
            ])
            srt_path = Path(tmp) / "sub.en.srt"
            if not srt_path.exists():
                raise RuntimeError(f"yt-dlp: no subtitles for {video_id}")
            return self._srt_to_text(srt_path.read_text(encoding="utf-8", errors="replace"))

    @staticmethod
    def _srt_to_text(srt: str) -> str:
        """SRT → plain text (убираем таймкоды и номера)."""
        lines = []
        for line in srt.splitlines():
            line = line.strip()
            if not line or line.isdigit() or "-->" in line:
                continue
            lines.append(line)
        return "\n".join(lines)
