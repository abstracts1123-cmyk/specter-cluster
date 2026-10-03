"""specter-bridge: optional adapters that report to the local core.

``fabric-in``      accepts Predator Fabric JSON on loopback and reports only a count.
                   Plate text is dropped unless ``--retain-plates-local`` is set.
``optic-status``   polls a user-configured Optic/Cortex URL on the car LAN (GET only).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from aiohttp import ClientError, ClientSession, ClientTimeout, web

from .bus import scrub


async def post_core(session: ClientSession, core_url: str, type_: str, data: dict) -> None:
    try:
        async with session.post(f"{core_url}/api/ingest", json={"type": type_, "data": data}):
            pass
    except (ClientError, TimeoutError, OSError) as exc:
        print(f"core unreachable: {exc}", file=sys.stderr)


def fabric_report(payload: object, retain_plates: bool) -> dict:
    """Reduce a Fabric event to a heartbeat; plate text is removed unless retained."""
    data = scrub(payload if isinstance(payload, dict) else {}, retain_plates)
    return {"plates_dropped": not retain_plates, "received": time.time(), "event": data}


async def run_fabric_in(host: str, port: int, core_url: str, retain: bool) -> None:
    async def handler(request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except ValueError:
            raise web.HTTPBadRequest(text="invalid JSON") from None
        async with ClientSession(timeout=ClientTimeout(total=3)) as session:
            await post_core(session, core_url, "fabric", fabric_report(payload, retain))
        return web.json_response({"ok": True})

    app = web.Application(client_max_size=256 * 1024)
    app.router.add_post("/fabric", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    print(
        f"fabric_in on http://{host}:{port}/fabric (plates "
        f"{'RETAINED LOCALLY' if retain else 'dropped'})"
    )
    await asyncio.Event().wait()


async def run_optic_status(name: str, url: str, core_url: str, interval: float) -> None:
    async with ClientSession(timeout=ClientTimeout(total=4)) as session:
        while True:
            try:
                async with session.get(url) as resp:
                    ok = resp.status < 500
            except (ClientError, TimeoutError, OSError):
                ok = False
            await post_core(session, core_url, name, {"ok": ok})
            await asyncio.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="specter-bridge")
    p.add_argument("--core", default="http://127.0.0.1:8770", help="specter-core URL")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fabric-in")
    f.add_argument("--host", default="127.0.0.1")
    f.add_argument("--port", type=int, default=8771)
    f.add_argument("--retain-plates-local", action="store_true")
    o = sub.add_parser("optic-status")
    o.add_argument("--name", choices=("optic", "cortex"), default="optic")
    o.add_argument("--url", required=True, help="Optic or Cortex URL on the car LAN")
    o.add_argument("--interval", type=float, default=5.0)
    args = p.parse_args(argv)
    try:
        if args.cmd == "fabric-in":
            asyncio.run(run_fabric_in(args.host, args.port, args.core, args.retain_plates_local))
        else:
            asyncio.run(run_optic_status(args.name, args.url, args.core, args.interval))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
