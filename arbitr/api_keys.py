from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


API_KEYS_FILE = Path(__file__).resolve().parent.parent / "api_keys.json"


@lru_cache(maxsize=1)
def _load_api_keys() -> dict[str, str]:
    if not API_KEYS_FILE.exists():
        raise RuntimeError(
            "Missing api_keys.json file in project root. "
            "Create it from api_keys.example.json."
        )

    try:
        data = json.loads(API_KEYS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid JSON in api_keys.json") from exc

    if not isinstance(data, dict):
        raise RuntimeError("api_keys.json must contain a JSON object")

    return {str(key): str(value) for key, value in data.items()}


def get_api_key(key_name: str) -> str:
    key = _load_api_keys().get(key_name)
    if not key:
        raise RuntimeError(f"Missing API key in api_keys.json: {key_name}")
    return key

