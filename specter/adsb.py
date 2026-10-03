"""Receive-only ADS-B from a local dump1090 SBS feed. Rows are labelled AIRCRAFT."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .cameras import haversine_m

LABEL = "AIRCRAFT"
STALE_S = 60.0
M_TO_FT = 3.28084


@dataclass
class Aircraft:
    icao: str
    callsign: str = ""
    lat: float | None = None
    lon: float | None = None
    alt_ft: int | None = None
    seen: float = 0.0


def _float(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None


def parse_sbs(line: str) -> dict | None:
    """Parse one SBS-1 ``MSG`` line into a dict of the fields we use."""
    f = line.strip().split(",")
    if len(f) < 16 or f[0] != "MSG" or not f[4]:
        return None
    out: dict = {"icao": f[4].upper()}
    if f[10].strip():
        out["callsign"] = f[10].strip()
    if f[11].strip():
        v = _float(f[11])
        if v is not None:
            out["alt_ft"] = int(v)
    lat, lon = _float(f[14]) if f[14] else None, _float(f[15]) if f[15] else None
    if lat is not None and lon is not None:
        out["lat"], out["lon"] = lat, lon
    return out


class AircraftTable:
    def __init__(self) -> None:
        self._ac: dict[str, Aircraft] = {}

    def ingest(self, line: str, now: float | None = None) -> None:
        row = parse_sbs(line)
        if not row:
            return
        ac = self._ac.setdefault(row["icao"], Aircraft(row["icao"]))
        for key in ("callsign", "alt_ft", "lat", "lon"):
            if key in row:
                setattr(ac, key, row[key])
        ac.seen = time.time() if now is None else now

    def active(self, now: float | None = None) -> list[Aircraft]:
        now = time.time() if now is None else now
        self._ac = {k: v for k, v in self._ac.items() if now - v.seen <= STALE_S}
        return list(self._ac.values())

    def rows(self, lat: float, lon: float, now: float | None = None, limit: int = 6) -> list[dict]:
        """Rows for the cluster, nearest first. Never labelled as police."""
        rows = []
        for ac in self.active(now):
            dist = None
            if ac.lat is not None and ac.lon is not None:
                dist = round(haversine_m(lat, lon, ac.lat, ac.lon))
            rows.append(
                {
                    "label": LABEL,
                    "icao": ac.icao,
                    "callsign": ac.callsign,
                    "alt_ft": ac.alt_ft,
                    "distance_m": dist,
                }
            )
        rows.sort(key=lambda r: (r["distance_m"] is None, r["distance_m"] or 0))
        return rows[:limit]


async def sbs_lines(host: str = "127.0.0.1", port: int = 30003):
    """Yield raw SBS lines from dump1090, reconnecting forever."""
    while True:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            try:
                while line := await reader.readline():
                    yield line.decode("ascii", "replace")
            finally:
                writer.close()
        except OSError:
            pass
        await asyncio.sleep(5)


def demo_lines(lat: float, lon: float, tick: int) -> list[str]:
    """Two synthetic aircraft circling near the given position (no radio needed)."""
    out = []
    for i, (icao, call, alt) in enumerate(
        (("A1B2C3", "SYN101", 12000), ("D4E5F6", "SYN202", 34000))
    ):
        dlat = 0.02 * (i + 1) + 0.0005 * (tick % 40)
        dlon = -0.03 * (i + 1)
        out.append(
            f"MSG,3,1,1,{icao},1,2000/01/01,00:00:00.000,2000/01/01,00:00:00.000,"
            f"{call},{alt},,,{lat + dlat:.5f},{lon + dlon:.5f},,,,,,0"
        )
    return out
