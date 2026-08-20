from __future__ import annotations

import os

from src.clients.ollama import OllamaClient


def _make_client(config: dict, env_key: str | None) -> OllamaClient:
    """Хелпер: создаёт OllamaClient с заданным конфигом и env-переменной."""
    old = os.environ.get("OLLAMA_API_KEY")
    if env_key is None:
        os.environ.pop("OLLAMA_API_KEY", None)
    else:
        os.environ["OLLAMA_API_KEY"] = env_key
    try:
        return OllamaClient(config, logger=None)
    finally:
        if old is None:
            os.environ.pop("OLLAMA_API_KEY", None)
        else:
            os.environ["OLLAMA_API_KEY"] = old


def test_api_key_priority_config_wins(config):
    """Проверяет: непустой llm.api_key из конфига важнее env OLLAMA_API_KEY."""
    config["llm"]["api_key"] = "config-key"
    client = _make_client(config, env_key="env-key")
    assert client.api_key == "config-key"


def test_api_key_priority_fallback_env(config):
    """Проверяет: пустой llm.api_key в конфиге → fallback на env OLLAMA_API_KEY."""
    config["llm"]["api_key"] = ""
    client = _make_client(config, env_key="env-key")
    assert client.api_key == "env-key"


def test_api_key_priority_both_empty(config):
    """Проверяет: пустой конфиг и нет env → api_key None (заголовок Authorization не добавляется)."""
    config["llm"]["api_key"] = ""
    client = _make_client(config, env_key=None)
    assert client.api_key is None
    assert "Authorization" not in client._headers()


def test_model_priority_model_wins(config):
    """Проверяет: непустой llm.model важнее llm.default_model."""
    config["llm"]["model"] = "model-a"
    config["llm"]["default_model"] = "model-b"
    client = _make_client(config, env_key=None)
    assert client.model == "model-a"


def test_model_priority_fallback_default(config):
    """Проверяет: пустой llm.model → fallback на llm.default_model."""
    config["llm"]["model"] = ""
    config["llm"]["default_model"] = "model-b"
    client = _make_client(config, env_key=None)
    assert client.model == "model-b"
