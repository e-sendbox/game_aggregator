from __future__ import annotations

import os

import requests


class OllamaClient:
    """Клиент LLM (Ollama, облако или локально)."""

    def __init__(self, config: dict, logger) -> None:
        self.base_url = config["llm"]["base_url"]
        self.model = config["llm"]["model"] or config["llm"].get("default_model")
        self.timeout = config["llm"]["timeout"]
        self.prompts_dir = config["llm"]["prompts_dir"]
        self.logger = logger
        self.api_key = config["llm"].get("api_key") or os.environ.get("OLLAMA_API_KEY")

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def ping(self) -> str:
        resp = requests.get(f"{self.base_url}/api/tags", headers=self._headers(), timeout=self.timeout)
        resp.raise_for_status()
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        if self.model not in models:
            raise RuntimeError(f"model {self.model!r} not found in Ollama, available: {models}")
        return self.model

    def summarize(self, prompt_name: str, game_title: str, game_description: str, comments: str,
                  extra: dict | None = None) -> str:
        prompt_path = os.path.join(self.prompts_dir, prompt_name)
        with open(prompt_path, encoding="utf-8") as fh:
            prompt = fh.read()
        values = {
            "game_title": game_title,
            "game_description": game_description or "нет описания",
            "comments": comments,
        }
        if extra:
            values.update(extra)
        prompt = prompt.format(**values)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        resp = requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["response"].strip()
