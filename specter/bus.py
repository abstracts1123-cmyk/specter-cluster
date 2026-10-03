"""Local event bus. Events are plain JSON; plate text is scrubbed by default."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

EVENT_TYPES = frozenset(
    {"hello", "gps", "camera", "alert", "aircraft", "survey", "tracker", "status"}
)


def scrub(value: Any, retain_plates: bool = False) -> Any:
    """Drop plate text recursively unless retention was explicitly enabled.

    Any key containing "plate" whose value is not a bool/number (e.g. a
    ``plates_dropped`` flag) is removed.
    """
    if retain_plates:
        return value
    if isinstance(value, dict):
        return {
            k: scrub(v, retain_plates)
            for k, v in value.items()
            if not ("plate" in str(k).lower() and not isinstance(v, (bool, int, float)))
        }
    if isinstance(value, list):
        return [scrub(v, retain_plates) for v in value]
    return value


@dataclass
class Event:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "ts": round(self.ts, 3), "data": self.data})


class EventBus:
    """Asyncio pub/sub. Slow subscribers drop their oldest message, never block."""

    def __init__(self, retain_plates: bool = False, queue_size: int = 256):
        self.retain_plates = retain_plates
        self._queue_size = queue_size
        self._subs: set[asyncio.Queue[Event]] = set()
        self._last: dict[str, Event] = {}
        self._alerts: deque[Event] = deque(maxlen=5)

    def publish(self, type_: str, data: dict[str, Any] | None = None) -> Event:
        if type_ not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {type_}")
        event = Event(type_, scrub(data or {}, self.retain_plates))
        if type_ == "alert":
            self._alerts.append(event)
        else:
            self._last[type_] = event
        for q in self._subs:
            if q.full():
                q.get_nowait()
            q.put_nowait(event)
        return event

    def subscribe(self) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(self._queue_size)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        self._subs.discard(q)

    def snapshot(self) -> Iterable[Event]:
        """Last five alerts (oldest first) then the latest event of each other type."""
        return [*self._alerts, *self._last.values()]
