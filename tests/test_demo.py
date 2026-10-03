import asyncio
import json
import sqlite3
import time
from pathlib import Path

import aiohttp
from aiohttp import web

from specter.adsb import AircraftTable, demo_lines, parse_sbs
from specter.ble_watch import TrackerWatch
from specter.bus import EventBus, scrub
from specter.cameras import load_cameras
from specter.core import Core, load_config, make_app
from specter.gps import DemoTrack
from specter.survey import SurveyDB, load_oui_notes, synthetic_observation

ROOT = Path(__file__).resolve().parent.parent


def make_core(demo=True, **privacy):
    cfg = load_config(None)
    cfg["privacy"].update(privacy)
    cams = load_cameras(ROOT / "data" / "cameras.sample.geojson")
    return Core(cfg, cams, SurveyDB(":memory:"), demo=demo)


def run_demo(core, ticks):
    q = core.bus.subscribe()
    events = []
    for t in range(ticks):
        core.demo_tick(t)
        while not q.empty():
            events.append(q.get_nowait())
    return events


def test_demo_raises_advisory_then_near_then_passing():
    core = make_core()
    events = run_demo(core, DemoTrack().period)
    levels = [e.data["level"] for e in events if e.type == "alert" and e.data["kind"] == "camera"]
    assert levels[:3] == ["ADVISORY", "NEAR", "PASSING"]


def test_demo_is_deterministic():
    def summary():
        ev = run_demo(make_core(), 120)
        return [
            (e.type, json.dumps(e.data, sort_keys=True))
            for e in ev
            if e.type in ("gps", "camera", "alert")
        ]

    assert summary() == summary()


def test_off_axis_and_behind_pins_never_alert():
    events = run_demo(make_core(), DemoTrack().period)
    names = {e.data["text"] for e in events if e.type == "alert"}
    assert not any("Red-light" in n or "behind" in n for n in names)


def test_tracker_raised_once_in_demo():
    events = run_demo(make_core(), DemoTrack().period * 2)
    trackers = [e for e in events if e.type == "tracker"]
    assert len(trackers) == 1
    assert (
        "neighbour" in trackers[0].data["footnote"] or "other cars" in trackers[0].data["footnote"]
    )


def test_tracker_watch_threshold():
    w = TrackerWatch()
    assert not w.observe("b", 0)
    assert not w.observe("b", 2000)  # not "more than" 2 km
    assert w.observe("b", 2001)
    assert not w.observe("b", 5000)  # only once


def test_plate_text_scrubbed_by_default():
    payload = {"plate": "ABC123", "nested": {"plate_text": "XYZ"}, "plates_dropped": True, "n": 1}
    assert scrub(payload) == {"nested": {}, "plates_dropped": True, "n": 1}
    bus = EventBus()
    assert "ABC123" not in bus.publish("status", payload).to_json()
    kept = EventBus(retain_plates=True).publish("status", payload).to_json()
    assert "ABC123" in kept


def test_wire_never_carries_position():
    events = run_demo(make_core(), 5)
    wire = " ".join(e.to_json() for e in events)
    assert '"lat"' not in wire and '"lon"' not in wire


def test_adsb_rows_are_labeled_aircraft():
    row = parse_sbs(demo_lines(40.0, -100.0, 0)[0])
    assert row and row["icao"] == "A1B2C3"
    table = AircraftTable()
    now = time.time()
    for line in demo_lines(40.0, -100.0, 0):
        table.ingest(line, now)
    rows = table.rows(40.0, -100.0, now)
    assert len(rows) == 2 and {r["label"] for r in rows} == {"AIRCRAFT"}
    assert "POLICE" not in json.dumps(rows).upper()
    assert table.rows(40.0, -100.0, now + 120) == []  # stale


def test_survey_rotation_and_notes(tmp_path):
    notes = tmp_path / "oui.txt"
    notes.write_text("# comment\n02:00:5E  synthetic test vendor\n", encoding="utf-8")
    db = SurveyDB(":memory:", load_oui_notes(notes))
    now = time.time()
    db.add("02:00:5e:00:00:01", "OLD", -50, 6, 40.0, -100.0, ts=now - 8 * 86400)
    db.add("02:00:5e:00:00:02", "NEW", -60, 11, 40.0, -100.0, ts=now)
    assert db.rotate(now) == 1 and db.count() == 1
    rows = db.recent()
    assert rows[0]["ssid"] == "NEW" and rows[0]["note"] == "synthetic test vendor"
    assert "lat" not in rows[0]
    assert db.aps_per_min(now) == 1


def test_survey_db_has_only_passive_columns():
    db = SurveyDB(":memory:")
    cols = [r[1] for r in db.db.execute("PRAGMA table_info(aps)")]
    assert cols == ["id", "ts", "bssid", "ssid", "rssi", "channel", "lat", "lon", "note"]
    assert isinstance(db.db, sqlite3.Connection)
    assert synthetic_observation(3) == synthetic_observation(3)
    assert synthetic_observation(3)["bssid"].startswith("02:00:5E")  # locally administered


def test_default_bind_is_loopback():
    cfg = load_config(None)
    assert cfg["server"]["host"] == "127.0.0.1" and cfg["server"]["port"] == 8770


def test_server_serves_cluster_and_websocket():
    async def scenario():
        core = make_core()
        run_demo(core, 3)
        runner = web.AppRunner(make_app(core, ROOT / "cluster"))
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]
        base = f"http://127.0.0.1:{port}"
        try:
            async with aiohttp.ClientSession() as s:
                page = await (await s.get(base + "/")).text()
                assert "SAMPLE PINS" in page and "DET. ONLY" in page
                async with s.ws_connect(base + "/ws") as ws:
                    hello = json.loads((await ws.receive(timeout=5)).data)
                    assert hello["type"] == "hello" and hello["data"]["sample"] is True
                    assert hello["data"]["plates_dropped"] is True
                # ingest: loopback only, plate text never reaches the bus
                r = await s.post(
                    base + "/api/ingest", json={"type": "fabric", "data": {"plate": "ABC123"}}
                )
                assert r.status == 200 and core.status["fabric"] == 1
                bad = await s.post(base + "/api/ingest", json={"type": "gps", "data": {}})
                assert bad.status == 400
        finally:
            await runner.cleanup()

    asyncio.run(scenario())
