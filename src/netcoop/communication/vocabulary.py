"""Vocabulary registry and validation helpers for canonical network telemetry."""

from pathlib import Path
from typing import Any

import yaml


class VocabularyError(ValueError):
    """Raised when an invalid metric, unit, or vocabulary term is encountered."""


_VOCABULARY_CACHE: dict[str, Any] | None = None


def get_vocabulary_path() -> Path:
    """Finds config/vocabulary.yaml relative to project root."""
    # Look from current file up to project root
    current = Path(__file__).resolve().parent
    for _ in range(4):
        candidate = current / "config" / "vocabulary.yaml"
        if candidate.exists():
            return candidate
        current = current.parent
    # Fallback to working directory config
    candidate = Path.cwd() / "config" / "vocabulary.yaml"
    if candidate.exists():
        return candidate
    raise FileNotFoundError("Could not locate config/vocabulary.yaml")


def load_vocabulary(force_reload: bool = False) -> dict[str, Any]:
    global _VOCABULARY_CACHE
    if _VOCABULARY_CACHE is not None and not force_reload:
        return _VOCABULARY_CACHE

    vocab_file = get_vocabulary_path()
    with open(vocab_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    _VOCABULARY_CACHE = data
    return data


def validate_metric_and_unit(metric_name: str, unit: str, value: float) -> None:
    """Validates that metric_name exists in canonical vocabulary, unit matches, and value is within bounds."""
    vocab = load_vocabulary()
    metrics = vocab.get("metrics", {})

    if metric_name not in metrics:
        raise VocabularyError(
            f"Unknown metric '{metric_name}'. Canonical metrics are: {list(metrics.keys())}"
        )

    spec = metrics[metric_name]
    expected_unit = spec.get("unit")
    if expected_unit and unit != expected_unit:
        raise VocabularyError(
            f"Invalid unit '{unit}' for metric '{metric_name}'. Expected '{expected_unit}'."
        )

    min_val = spec.get("min")
    if min_val is not None and value < min_val:
        raise VocabularyError(
            f"Value {value} for '{metric_name}' is below minimum allowed {min_val}."
        )

    max_val = spec.get("max")
    if max_val is not None and value > max_val:
        raise VocabularyError(
            f"Value {value} for '{metric_name}' is above maximum allowed {max_val}."
        )


def validate_finding_type(finding_type: str) -> None:
    vocab = load_vocabulary()
    allowed = vocab.get("finding_types", [])
    if allowed and finding_type not in allowed:
        raise VocabularyError(
            f"Invalid finding_type '{finding_type}'. Allowed types are: {allowed}"
        )


def validate_fault_code(fault_code: str) -> None:
    vocab = load_vocabulary()
    allowed = vocab.get("fault_codes", [])
    if allowed and fault_code not in allowed:
        raise VocabularyError(
            f"Invalid fault_code '{fault_code}'. Allowed fault codes are: {allowed}"
        )
