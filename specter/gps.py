"""GNSS sources: a gpsd client and a deterministic demo track."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import AsyncIterator
from dataclasses import dataclass

M_PER_DEG_LAT = 111_194.9


@dataclass(frozen=True)
class Fix:
    lat: float
    lon: float
    speed_mps: float
    course: float | None
    mode: int = 3


def offset(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    """Small-distance offset of a lat/lon by metres north and east."""
    dlat = north_m / M_PER_DEG_LAT
    dlon = east_m / (M_PER_DEG_LAT * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def parse_tpv(msg: dict) -> Fix | None:
    """Convert a gpsd TPV report into a Fix, or None when there is no 2D fix."""
    if msg.get("class") != "TPV" or msg.get("mode", 0) < 2:
        return None
    if "lat" not in msg or "lon" not in msg:
        return None
    track = msg.get("track")
    return Fix(
        lat=float(msg["lat"]),
        lon=float(msg["lon"]),
        speed_mps=float(msg.get("speed", 0.0)),
        course=None if track is None else float(track) % 360.0,
        mode=int(msg["mode"]),
    )


async def gpsd_fixes(host: str = "127.0.0.1", port: int = 2947) -> AsyncIterator[Fix]:
    """Yield fixes from gpsd, reconnecting forever. Read-only JSON watch."""
    while True:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            writer.write(b'?WATCH={"enable":true,"json":true}\n')
            await writer.drain()
            try:
                while line := await reader.readline():
                    try:
                        fix = parse_tpv(json.loads(line))
                    except (ValueError, TypeError):
                        continue
                    if fix:
                        yield fix
            finally:
                writer.close()
        except OSError:
            pass
        await asyncio.sleep(3)


# Demo track: due north at 20 m/s along one meridian. The sample pins in
# data/cameras.sample.geojson sit 15 m east of this line, so the run raises
# ADVISORY, NEAR and PASSING for the first pin, then repeats.
DEMO_START = (39.99101, -100.0)
DEMO_SPEED_MPS = 20.0
DEMO_LENGTH_M = 2600.0


class DemoTrack:
    """Pure function of the tick index, so runs are reproducible."""

    def __init__(self, hz: float = 1.0):
        self.hz = hz
        self.period = int(DEMO_LENGTH_M / DEMO_SPEED_MPS * hz)

    def fix(self, tick: int) -> Fix:
        t = (tick % self.period) / self.hz
        lat, lon = offset(*DEMO_START, DEMO_SPEED_MPS * t, 0.0)
        return Fix(lat, lon, DEMO_SPEED_MPS, 0.0)

    async def fixes(self) -> AsyncIterator[Fix]:
        tick = 0
        while True:
            yield self.fix(tick)
            tick += 1
            await asyncio.sleep(1.0 / self.hz)
