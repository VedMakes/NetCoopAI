"""Rule and threshold configuration loader for diagnostic towers."""

from pathlib import Path
from typing import Any

import yaml

_RULES_CACHE: dict[str, Any] | None = None


def get_rules_path() -> Path:
    current = Path(__file__).resolve().parent
    for _ in range(4):
        candidate = current / "config" / "rules.yaml"
        if candidate.exists():
            return candidate
        current = current.parent
    candidate = Path.cwd() / "config" / "rules.yaml"
    if candidate.exists():
        return candidate
    raise FileNotFoundError("Could not locate config/rules.yaml")


def load_rules(force_reload: bool = False) -> dict[str, Any]:
    global _RULES_CACHE
    if _RULES_CACHE is not None and not force_reload:
        return _RULES_CACHE

    rules_file = get_rules_path()
    with open(rules_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    _RULES_CACHE = data
    return data
