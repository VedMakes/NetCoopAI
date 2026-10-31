"""Deterministic and runtime ID generation utilities."""

import itertools
import threading
import uuid


class IdGenerator:
    """Protocol / base class for ID generation."""

    def next_id(self, prefix: str) -> str:
        raise NotImplementedError


class UuidGenerator(IdGenerator):
    """Runtime ID generator producing short random UUIDs."""

    def next_id(self, prefix: str) -> str:
        short_id = uuid.uuid4().hex[:8]
        return f"{prefix}-{short_id}"


class DeterministicIdGenerator(IdGenerator):
    """Deterministic sequence generator for tests and reproducible runs."""

    def __init__(self, start: int = 1) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, itertools.count] = {}
        self._start = start

    def reset(self, start: int = 1) -> None:
        with self._lock:
            self._start = start
            self._counters.clear()

    def next_id(self, prefix: str) -> str:
        with self._lock:
            if prefix not in self._counters:
                self._counters[prefix] = itertools.count(self._start)
            num = next(self._counters[prefix])
            return f"{prefix}-{num:06d}"


# Global default generator instance
_DEFAULT_GENERATOR: IdGenerator = DeterministicIdGenerator()


def set_id_generator(generator: IdGenerator) -> None:
    global _DEFAULT_GENERATOR
    _DEFAULT_GENERATOR = generator


def get_id_generator() -> IdGenerator:
    return _DEFAULT_GENERATOR


def generate_id(prefix: str) -> str:
    return _DEFAULT_GENERATOR.next_id(prefix)
