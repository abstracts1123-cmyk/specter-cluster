"""Passive wireless survey log. Records what was heard; never associates or transmits."""

from __future__ import annotations

import json
import random
import sqlite3
import time
from collections.abc import AsyncIterator
from pathlib import Path

ROTATION_DAYS = 7

_SCHEMA = """
CREATE TABLE IF NOT EXISTS aps (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    bssid TEXT NOT NULL,
    ssid TEXT NOT NULL,
    rssi INTEGER,
    channel INTEGER,
    lat REAL,
    lon REAL,
    note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS aps_ts ON aps (ts);
"""


def load_oui_notes(path: str | Path | None) -> dict[str, str]:
    """Load a user-supplied notes file: ``AA:BB:CC  free text`` per line, ``#`` comments."""
    notes: dict[str, str] = {}
    if not path or not Path(path).expanduser().is_file():
        return notes
    for line in Path(path).expanduser().read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        prefix, _, note = line.partition(" ")
        key = prefix.upper().replace("-", ":")
        if len(key) == 8 and note.strip():
            notes[key] = note.strip()
    return notes


class SurveyDB:
    def __init__(self, path: str | Path = ":memory:", oui_notes: dict[str, str] | None = None):
        if str(path) != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(Path(path).expanduser()) if str(path) != ":memory:" else path)
        self.db.executescript(_SCHEMA)
        self.oui_notes = oui_notes or {}

    def note_for(self, bssid: str) -> str:
        return self.oui_notes.get(bssid.upper()[:8], "")

    def add(
        self,
        bssid: str,
        ssid: str,
        rssi: int | None,
        channel: int | None,
        lat: float | None,
        lon: float | None,
        ts: float | None = None,
    ) -> None:
        self.db.execute(
            "INSERT INTO aps (ts, bssid, ssid, rssi, channel, lat, lon, note) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                time.time() if ts is None else ts,
                bssid.upper(),
                ssid,
                rssi,
                channel,
                lat,
                lon,
                self.note_for(bssid),
            ),
        )
        self.db.commit()

    def rotate(self, now: float | None = None, days: int = ROTATION_DAYS) -> int:
        """Delete rows older than ``days`` days. Returns the number removed."""
        cutoff = (time.time() if now is None else now) - days * 86400
        cur = self.db.execute("DELETE FROM aps WHERE ts < ?", (cutoff,))
        self.db.commit()
        return cur.rowcount

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM aps").fetchone()[0]

    def aps_per_min(self, now: float | None = None) -> int:
        """Distinct BSSIDs heard in the last 60 seconds."""
        since = (time.time() if now is None else now) - 60
        return self.db.execute(
            "SELECT COUNT(DISTINCT bssid) FROM aps WHERE ts >= ?", (since,)
        ).fetchone()[0]

    def recent(self, limit: int = 12) -> list[dict]:
        """Recent rows for display. Position is deliberately left out."""
        cur = self.db.execute(
            "SELECT ts, bssid, ssid, rssi, channel, note FROM aps ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        keys = ("ts", "bssid", "ssid", "rssi", "channel", "note")
        return [dict(zip(keys, row, strict=True)) for row in cur]

    def close(self) -> None:
        self.db.close()


def synthetic_observation(tick: int) -> dict:
    """Deterministic, clearly fake receive-only observation (locally administered MACs)."""
    rng = random.Random(tick)
    n = rng.randrange(1, 9)
    return {
        "bssid": f"02:00:5E:00:00:{n:02X}",
        "ssid": f"SYNTH-AP-{n:02d}",
        "rssi": -40 - rng.randrange(0, 50),
        "channel": (1, 6, 11, 36, 149)[n % 5],
    }


async def tail_jsonl(path: str | Path, poll_s: float = 1.0) -> AsyncIterator[dict]:
    """Follow a JSON-lines file written by a passive capture tool you run yourself.

    Each line needs ``bssid`` and may carry ``ssid``, ``rssi`` and ``channel``.
    SPECTER itself never puts a radio into monitor mode and never transmits.
    """
    import asyncio

    p = Path(path).expanduser()
    pos = p.stat().st_size if p.exists() else 0
    while True:
        if p.exists() and p.stat().st_size > pos:
            with p.open(encoding="utf-8") as fh:
                fh.seek(pos)
                for line in fh:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict) and row.get("bssid"):
                        yield row
                pos = fh.tell()
        await asyncio.sleep(poll_s)
