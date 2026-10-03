"""specter-core: asyncio service. Reads sensors, evaluates pins, serves the cluster.

Everything here is receive-only. The server binds to loopback by default and the
precise track (latitude/longitude) is never put on the websocket.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from . import __version__
from .adsb import AircraftTable, demo_lines, sbs_lines
from .ble_watch import FOOTNOTE as BLE_FOOTNOTE
from .ble_watch import TrackerWatch, ble_beacons, demo_beacons
from .bus import Event, EventBus
from .cameras import (
    CameraMonitor,
    CameraSet,
    Level,
    fetch_osm,
    load_cameras,
    parse_bbox,
)
from .gps import DemoTrack, Fix, gpsd_fixes
from .survey import SurveyDB, load_oui_notes, synthetic_observation, tail_jsonl

ROOT = Path(__file__).resolve().parent.parent
HOME_DIR = Path.home() / ".specter"
MPS_TO_MPH = 2.2369362920544
MPS_TO_KMH = 3.6
INGEST_TYPES = {"fabric", "optic", "cortex"}
ROTATE_EVERY_TICKS = 1800  # run_aux ticks every 2 s, so about hourly

DEFAULTS: dict[str, dict[str, Any]] = {
    "display": {"units": "mph", "theme": "night"},
    "server": {"host": "127.0.0.1", "port": 8770},
    "cameras": {"path": ""},
    "gps": {"host": "127.0.0.1", "port": 2947},
    "adsb": {"enabled": False, "host": "127.0.0.1", "port": 30003},
    "ble": {"enabled": False},
    "survey": {"enabled": True, "db": str(HOME_DIR / "survey.db"), "oui_notes": "", "source": ""},
    "privacy": {"retain_plates_local": False},
}


def load_config(path: str | Path | None) -> dict[str, dict[str, Any]]:
    cfg = {k: dict(v) for k, v in DEFAULTS.items()}
    if path:
        with Path(path).expanduser().open("rb") as fh:
            user = tomllib.load(fh)
        for section, values in user.items():
            if section in cfg and isinstance(values, dict):
                cfg[section].update(values)
    return cfg


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Core:
    def __init__(
        self,
        cfg: dict[str, dict[str, Any]],
        cameras: CameraSet,
        survey: SurveyDB,
        *,
        demo: bool = False,
    ):
        self.cfg = cfg
        self.demo = demo
        self.cameras = cameras
        self.survey = survey
        self.bus = EventBus(retain_plates=bool(cfg["privacy"]["retain_plates_local"]))
        self.monitor = CameraMonitor(cameras)
        self.aircraft = AircraftTable()
        self.ble = TrackerWatch()
        self.units = "kmh" if str(cfg["display"]["units"]).lower() == "kmh" else "mph"
        self.odometer_m = 0.0
        self.last_fix: Fix | None = None
        self.status: dict[str, Any] = {"optic": "OFF", "cortex": "OFF", "fabric": 0}

    # -- messages ------------------------------------------------------------

    def hello(self) -> dict[str, Any]:
        return {
            "version": __version__,
            "demo": self.demo,
            "units": self.units,
            "theme": self.cfg["display"]["theme"],
            "sample": self.cameras.sample,
            "banner": self.cameras.banner,
            "plates_dropped": not self.bus.retain_plates,
            "ble_footnote": BLE_FOOTNOTE,
            "survey_synthetic": self.demo,
            "pins": len(self.cameras.cameras),
        }

    def alert(self, level: str, kind: str, text: str, distance_m: float | None = None) -> None:
        self.bus.publish(
            "alert",
            {
                "level": level,
                "kind": kind,
                "text": text,
                "distance_m": None if distance_m is None else round(distance_m),
            },
        )

    # -- sensor handlers -------------------------------------------------------

    def handle_fix(self, fix: Fix, dt: float = 1.0) -> None:
        self.last_fix = fix
        self.odometer_m += fix.speed_mps * dt
        factor = MPS_TO_KMH if self.units == "kmh" else MPS_TO_MPH
        self.bus.publish(
            "gps",
            {"speed": round(fix.speed_mps * factor, 1), "course": fix.course, "mode": fix.mode},
        )
        snap = self.monitor.update(fix.lat, fix.lon, fix.course)
        nearest = snap.nearest
        self.bus.publish(
            "camera",
            {
                "level": snap.level.name,
                "ahead_count": snap.ahead_count,
                "next": None
                if nearest is None
                else {
                    "name": nearest.camera.name,
                    "operator": nearest.camera.operator,
                    "kind": nearest.camera.kind,
                    "bearing": round(nearest.bearing),
                    "distance_m": round(nearest.distance_m),
                },
            },
        )
        for pin in snap.escalations:
            who = pin.camera.operator or pin.camera.name or "unnamed"
            self.alert(
                pin.level.name, "camera", f"{pin.camera.kind.upper()} \u00b7 {who}", pin.distance_m
            )

    def handle_beacon(self, beacon: str) -> None:
        if self.ble.observe(beacon, self.odometer_m):
            self.bus.publish("tracker", {"beacon": beacon, "footnote": BLE_FOOTNOTE})
            self.alert(Level.ADVISORY.name, "tracker", "TRACKER? \u00b7 beacon persists >2 km")

    def record_ap(self, obs: dict) -> None:
        fix = self.last_fix
        self.survey.add(
            str(obs["bssid"]),
            str(obs.get("ssid", "")),
            obs.get("rssi"),
            obs.get("channel"),
            fix.lat if fix else None,
            fix.lon if fix else None,
        )

    def publish_aux(self) -> None:
        """Slow-changing panels: survey, aircraft, rail status."""
        fix = self.last_fix
        rows = self.aircraft.rows(fix.lat, fix.lon) if fix else []
        self.bus.publish("aircraft", {"count": len(rows), "rows": rows})
        rate = self.survey.aps_per_min()
        self.bus.publish(
            "survey",
            {"aps_per_min": rate, "synthetic": self.demo, "rows": self.survey.recent(12)},
        )
        self.bus.publish(
            "status",
            {
                "optic": self.status["optic"],
                "cortex": self.status["cortex"],
                "fabric": self.status["fabric"],
                "survey_aps_min": rate,
                "ble": "ON" if (self.demo or self.cfg["ble"]["enabled"]) else "OFF",
                "air": len(rows),
            },
        )

    def ingest(self, type_: str, data: dict) -> None:
        """Accept a bridge report. Only a counter or up/down flag is kept; payloads are dropped."""
        if type_ == "fabric":
            self.status["fabric"] += 1
        else:
            self.status[type_] = "UP" if data.get("ok") else "DOWN"
        self.publish_aux()

    # -- demo and live loops ---------------------------------------------------

    def demo_tick(self, tick: int, hz: float = 1.0) -> None:
        track = DemoTrack(hz)
        fix = track.fix(tick)
        self.handle_fix(fix, 1.0 / hz)
        for line in demo_lines(fix.lat, fix.lon, tick):
            self.aircraft.ingest(line)
        for beacon in demo_beacons(tick):
            self.handle_beacon(beacon)
        self.record_ap(synthetic_observation(tick))
        if tick % 2 == 0:
            self.publish_aux()

    async def run_demo(self) -> None:
        tick = 0
        while True:
            self.demo_tick(tick)
            tick += 1
            await asyncio.sleep(1.0)

    async def run_gps(self) -> None:
        last = time.monotonic()
        async for fix in gpsd_fixes(self.cfg["gps"]["host"], int(self.cfg["gps"]["port"])):
            now = time.monotonic()
            self.handle_fix(fix, min(now - last, 5.0))
            last = now

    async def run_adsb(self) -> None:
        async for line in sbs_lines(self.cfg["adsb"]["host"], int(self.cfg["adsb"]["port"])):
            self.aircraft.ingest(line)

    async def run_ble(self) -> None:
        try:
            async for beacon in ble_beacons():
                self.handle_beacon(beacon)
        except RuntimeError as exc:
            print(f"BLE disabled: {exc}", file=sys.stderr)

    async def run_survey(self) -> None:
        async for obs in tail_jsonl(self.cfg["survey"]["source"]):
            self.record_ap(obs)

    async def run_aux(self) -> None:
        rotations = 0
        while True:
            await asyncio.sleep(2.0)
            rotations += 1
            if rotations % ROTATE_EVERY_TICKS == 0:
                self.survey.rotate()
            if not self.demo:
                self.publish_aux()


# -- web -----------------------------------------------------------------------


def make_app(core: Core, cluster_dir: Path = ROOT / "cluster") -> web.Application:
    async def index(_: web.Request) -> web.StreamResponse:
        return web.FileResponse(cluster_dir / "index.html")

    async def ws_handler(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        queue = core.bus.subscribe()
        closed = asyncio.ensure_future(_drain(ws))
        getter: asyncio.Future | None = None
        try:
            await ws.send_str(Event("hello", core.hello()).to_json())
            for event in core.bus.snapshot():
                await ws.send_str(event.to_json())
            while not ws.closed:
                getter = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({getter, closed}, return_when=asyncio.FIRST_COMPLETED)
                if getter not in done:
                    break
                await ws.send_str(getter.result().to_json())
        except ConnectionError:
            pass
        finally:
            core.bus.unsubscribe(queue)
            closed.cancel()
            if getter is not None:
                getter.cancel()
        return ws

    async def _drain(ws: web.WebSocketResponse) -> None:
        async for msg in ws:
            if msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                break

    async def ingest(request: web.Request) -> web.Response:
        peer = request.transport.get_extra_info("peername") if request.transport else None
        if not peer or not is_loopback(peer[0]):
            raise web.HTTPForbidden(text="loopback only")
        if "Origin" in request.headers:  # bridges are not browsers; refuse cross-site POSTs
            raise web.HTTPForbidden(text="browser requests not accepted")
        try:
            body = await request.json()
        except ValueError:
            raise web.HTTPBadRequest(text="invalid JSON") from None
        type_ = body.get("type") if isinstance(body, dict) else None
        if type_ not in INGEST_TYPES:
            raise web.HTTPBadRequest(text="unsupported type")
        data = body.get("data")
        core.ingest(type_, data if isinstance(data, dict) else {})
        return web.json_response({"ok": True})

    app = web.Application(client_max_size=64 * 1024)
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app.router.add_post("/api/ingest", ingest)
    app.router.add_static("/", cluster_dir, show_index=False)
    return app


# -- entry point ---------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="specter-core", description="SPECTER core (detection only)")
    p.add_argument("--config", help="TOML config (default: ~/.specter/config.toml if present)")
    p.add_argument(
        "--demo", action="store_true", help="simulated track and synthetic data, no radio"
    )
    p.add_argument("--host", help="bind address (loopback only unless --allow-lan)")
    p.add_argument("--port", type=int)
    p.add_argument("--allow-lan", action="store_true", help="permit a non-loopback bind")
    p.add_argument("--cameras", help="camera GeoJSON path")
    p.add_argument(
        "--retain-plates-local",
        action="store_true",
        help="keep plate text from bridges on the local bus (default: dropped)",
    )
    p.add_argument(
        "--fetch-osm",
        action="store_true",
        help="download ALPR pins from OpenStreetMap once, then exit (needs --bbox)",
    )
    p.add_argument("--bbox", help="south,west,north,east for --fetch-osm")
    return p.parse_args(argv)


def resolve_cameras_path(cfg: dict, override: str | None, demo: bool) -> Path:
    if override or cfg["cameras"]["path"]:
        return Path(override or cfg["cameras"]["path"]).expanduser()
    user = HOME_DIR / "cameras.geojson"
    if user.is_file() and not demo:
        return user
    return ROOT / "data" / "cameras.sample.geojson"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = args.config
    default_cfg = HOME_DIR / "config.toml"
    if not config_path and default_cfg.is_file():
        config_path = str(default_cfg)
    cfg = load_config(config_path)
    if args.retain_plates_local:
        cfg["privacy"]["retain_plates_local"] = True
    host = args.host or cfg["server"]["host"]
    port = args.port or int(cfg["server"]["port"])
    if not is_loopback(host) and not args.allow_lan:
        print(
            f"refusing to bind {host}: use a loopback address or pass --allow-lan", file=sys.stderr
        )
        return 2

    if args.fetch_osm:
        if not args.bbox:
            print("--fetch-osm requires an explicit --bbox south,west,north,east", file=sys.stderr)
            return 2
        import json

        out = Path(args.cameras or HOME_DIR / "cameras.geojson").expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        data = fetch_osm(parse_bbox(args.bbox))
        out.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"wrote {len(data['features'])} pins to {out}")
        return 0

    cam_path = resolve_cameras_path(cfg, args.cameras, args.demo)
    cameras = load_cameras(cam_path)
    if args.demo:
        survey = SurveyDB(":memory:")
    else:
        survey = SurveyDB(cfg["survey"]["db"], load_oui_notes(cfg["survey"]["oui_notes"] or None))
        survey.rotate()
    core = Core(cfg, cameras, survey, demo=args.demo)
    print(
        f"specter-core {__version__}: {len(cameras.cameras)} pins from {cam_path}"
        f"{' [' + cameras.banner + ']' if cameras.sample else ''}"
    )
    asyncio.run(serve(core, host, port))
    return 0


async def serve(core: Core, host: str, port: int) -> None:
    runner = web.AppRunner(make_app(core))
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    print(f"cluster: http://{host}:{port}  (kiosk: chromium --kiosk --app=http://{host}:{port})")
    tasks = [asyncio.create_task(core.run_aux())]
    if core.demo:
        tasks.append(asyncio.create_task(core.run_demo()))
    else:
        tasks.append(asyncio.create_task(core.run_gps()))
        if core.cfg["adsb"]["enabled"]:
            tasks.append(asyncio.create_task(core.run_adsb()))
        if core.cfg["ble"]["enabled"]:
            tasks.append(asyncio.create_task(core.run_ble()))
        if core.cfg["survey"]["enabled"] and core.cfg["survey"]["source"]:
            tasks.append(asyncio.create_task(core.run_survey()))
    try:
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()
        await runner.cleanup()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
