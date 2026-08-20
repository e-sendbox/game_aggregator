from __future__ import annotations

import os
import sys

import uvicorn
import yaml

from web.app import app


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def main() -> None:
    config_path = os.environ.get("CONFIG_PATH", "config.yaml")
    config = load_config(config_path)
    host = config.get("web", {}).get("host", "0.0.0.0")
    port = config.get("web", {}).get("port", 8000)
    print(f"Metacritic Research web: http://{host}:{port}", file=sys.stderr)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
