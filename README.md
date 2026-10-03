# specter-cluster

[![build](https://github.com/abstracts1123-cmyk/specter-cluster/actions/workflows/ci.yml/badge.svg)](https://github.com/abstracts1123-cmyk/specter-cluster/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![detection only](https://img.shields.io/badge/detection-only-b6f27a.svg)](docs/BOUNDARY.md)

**SPECTER is a detection and logging instrument.** It is an offline-first car computer: a Linux box
(Raspberry Pi 5 or similar) serves a browser instrument cluster to a display in the speedometer bay.
It warns about *publicly mapped* automated license plate readers, speed and red-light cameras, keeps a
passive wireless survey log, and shows heartbeat status from an optional local dashcam.

> It does not jam, hack, deauthenticate, conceal plates, route around stops, or upload anything.
> See [docs/BOUNDARY.md](docs/BOUNDARY.md).

An alert is not proof a camera is present. No alert is not proof the road is clear.

Topics: `alpr`, `openstreetmap`, `privacy`, `dashcam`, `raspberry-pi`, `wardriving`.

## Try it with no radio

```sh
pip install -e .
python -m specter.core --demo
```

Open <http://127.0.0.1:8770>. A simulated drive raises ADVISORY (< 400 m), NEAR (< 120 m) and PASSING
(< 40 m) on a sample pin, under the banner `SAMPLE PINS — NOT A LIVE MAP`. Press **SURVEY** on the bezel
for synthetic receive-only survey rows and the AIRCRAFT list.

## Install on the car computer

Debian, Ubuntu or Raspberry Pi OS, as your normal user (not root):

```sh
./install.sh
```

The script is safe to re-run. It installs only `python3-venv python3-gps gpsd gpsd-clients` via apt,
creates `~/.specter/venv`, copies `config.example.toml` to `~/.specter/config.toml` if missing, and adds a
user unit `specter.service` bound to `127.0.0.1:8770` (never `0.0.0.0`).

Kiosk command:

```sh
chromium --kiosk --app=http://127.0.0.1:8770
```

## Parts

| Process | What it does |
|---------|--------------|
| `specter-core` (`python -m specter.core`) | asyncio service: gpsd, optional dump1090 SBS on `127.0.0.1:30003`, optional BLE via bleak, offline camera GeoJSON, localhost websocket. |
| `cluster/` | Static HTML/CSS/JS speedometer cluster. No build step. Night and Day themes, 800×480 first, fluid to 1280×720. |
| `specter-bridge` | Optional. `fabric-in` accepts Predator Fabric JSON and drops plate text unless `--retain-plates-local`. `optic-status` polls an Optic or Cortex URL on the car LAN. |

The architecture is modelled on Assassin, Marksman, Predator, Optic, Cortex and Predator Fabric from V0LT.
No third-party source is vendored here, and ALPR itself is not reimplemented.

```sh
specter-bridge fabric-in                       # POST Fabric JSON to http://127.0.0.1:8771/fabric
specter-bridge optic-status --url http://192.168.1.50:8080 --name optic
```

## Alerts

| Level | Distance |
|-------|----------|
| CLEAR | — |
| ADVISORY | < 400 m |
| NEAR | < 120 m |
| PASSING | < 40 m |

Levels use hysteresis so a pin does not flap. Only pins within ±35° of GNSS course and 800 m count as
ahead. "Pins ahead" is awareness, not an evasion route. BLE `TRACKER?` fires once for a beacon seen over
more than 2 km of odometer; it can be a nearby car or phone.

## Data

Camera pins come from a local GeoJSON file. OpenStreetMap/DeFlock data is fetched only if you pass
`--fetch-osm` with an explicit `--bbox`. See [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) and
[docs/HARDWARE.md](docs/HARDWARE.md).

## Development

```sh
pip install -e ".[dev]"
ruff check .
pytest
```

Tests are network-free; non-loopback sockets are blocked in `tests/conftest.py`.

## License

Apache-2.0. See [LICENSE](LICENSE).
