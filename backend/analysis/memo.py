"""Reuse readings that cannot have changed.

The analysis is a pure function of the bars it reads and the parameters
it reads them with. When neither has moved, last time's answer is still
the right answer — and computing it again costs about 130ms and a
quarter of a million function calls.

That matters because of the polling rhythm. The panel asks for a signal
every ten to fifteen seconds while an M1 bar arrives once a minute, so
most requests are asking a question that was already answered. On an M15
or H1 chart it is worse: dozens of identical recomputations per bar.

Freshness is decided by a fingerprint rather than a clock. A timestamp
cache has to choose a TTL, and every TTL is either too long (a new bar
sits unseen) or too short (work is repeated for nothing). Counting the
rows and taking the newest timestamp costs about half a millisecond
against a covering index and is exactly right instead: it changes the
moment the data does, and not before.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Generic, TypeVar

from backend.logging_setup import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

#: Per-cache entry ceiling. A handful of symbols across a handful of
#: timeframes; the bound only exists so a long session cannot grow
#: without limit.
MAX_ENTRIES = 96


class Memo(Generic[T]):
    """Fingerprint-keyed cache with a bounded, least-recently-used store.

    Not thread-safe by design. The backend serves requests on one loop
    and every caller here is synchronous; a lock would add contention to
    guard against something that does not happen. Should that change,
    the worst case is a duplicated computation, not a wrong answer.
    """

    def __init__(self, name: str, max_entries: int = MAX_ENTRIES) -> None:
        self._name = name
        self._max = max_entries
        self._store: OrderedDict[Any, tuple[Any, T]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: Any, fingerprint: Any) -> T | None:
        """The stored value, if it was computed from this exact data."""
        entry = self._store.get(key)

        if entry is None or entry[0] != fingerprint:
            self.misses += 1
            return None

        # Refresh recency so a series in active use is not evicted by one
        # glanced at once.
        self._store.move_to_end(key)
        self.hits += 1

        return entry[1]

    def put(self, key: Any, fingerprint: Any, value: T) -> None:
        self._store[key] = (fingerprint, value)
        self._store.move_to_end(key)

        while len(self._store) > self._max:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()

    @property
    def ratio(self) -> float:
        total = self.hits + self.misses

        return self.hits / total if total else 0.0

    def stats(self) -> dict[str, Any]:
        return {
            "name": self._name,
            "entries": len(self._store),
            "hits": self.hits,
            "misses": self.misses,
            "ratio": round(self.ratio, 3),
        }
