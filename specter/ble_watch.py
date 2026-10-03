"""BLE persistence watcher. Notify only; it never connects to or pairs with a device."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator

PERSIST_M = 2000.0
STALE_M = 10_000.0  # forget beacons not heard from for this much driving
FOOTNOTE = (
    "TRACKER? is a guess. Phones, earbuds and other cars' devices can follow you "
    "for miles without any intent."
)


def anonymise(address: str) -> str:
    """Short, non-reversible id so raw MAC addresses are not kept or displayed."""
    return hashlib.sha256(address.upper().encode()).hexdigest()[:8]


class TrackerWatch:
    """Raises TRACKER? once per beacon seen across more than 2 km of odometer."""

    def __init__(self, persist_m: float = PERSIST_M):
        self.persist_m = persist_m
        self._first: dict[str, float] = {}
        self._last: dict[str, float] = {}
        self._flagged: set[str] = set()

    def observe(self, beacon: str, odometer_m: float) -> bool:
        last = self._last.get(beacon)
        if last is not None and odometer_m - last > STALE_M:
            self._first.pop(beacon, None)
            self._flagged.discard(beacon)
        self._first.setdefault(beacon, odometer_m)
        self._last[beacon] = odometer_m
        if beacon in self._flagged:
            return False
        if odometer_m - self._first[beacon] > self.persist_m:
            self._flagged.add(beacon)
            return True
        return False

    @property
    def tracked(self) -> int:
        return len(self._last)


async def ble_beacons() -> AsyncIterator[str]:
    """Yield anonymised beacon ids using bleak (passive scanning). Optional dependency."""
    try:
        from bleak import BleakScanner
    except ImportError as exc:  # pragma: no cover - depends on host
        raise RuntimeError("bleak is not installed; pip install bleak") from exc
    queue: asyncio.Queue[str] = asyncio.Queue()

    def _cb(device, _adv) -> None:
        queue.put_nowait(anonymise(device.address))

    async with BleakScanner(_cb, scanning_mode="passive"):
        while True:
            yield await queue.get()


def demo_beacons(tick: int) -> list[str]:
    """One synthetic beacon that follows the demo car, plus short-lived passers-by."""
    out = ["synth-follower"]
    if tick % 7 == 0:
        out.append(f"synth-pass-{tick // 7}")
    return out
