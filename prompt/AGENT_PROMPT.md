# Agent prompt (condensed spec)

Build SPECTER: an offline-first car computer. A Linux box (Raspberry Pi 5 or similar) serves a browser
instrument on an 800×480 or 1024×600 display in the speedometer bay. SPECTER is a **detection and logging
instrument only**. Do not vendor third-party application source; mirror architecture only
(Assassin core, Marksman dashboard, Predator/Optic/Cortex/Predator Fabric dashcam stack). Do not
reimplement ALPR in v1.

## Processes
- `specter-core`: Python 3.11+ asyncio. gpsd; optional dump1090 SBS at `127.0.0.1:30003`; optional bleak BLE;
  offline camera GeoJSON; localhost websocket.
- `specter-cluster`: static HTML/CSS/JS, no build step. The speedometer UI.
- `specter-bridge`: optional. `fabric_in` drops plate text unless `--retain-plates-local`.
  `optic_status` polls a user-set Optic or Cortex URL on the car LAN.

## Hard boundary (refuse; record in `docs/BOUNDARY.md`, near the top)
- Jamming of radio, GPS, cellular, radar, lidar or infrared, or any transmitter aimed at a camera, reader or radio.
- Damaging, blinding, dazzling, hacking, deauthenticating or disabling a camera or its network.
- Plate covers, sprays, flips or other concealment.
- A route solver whose purpose is evading a stop.
- Wi-Fi cracking, association to camera backhaul, injection or deauth. No aircrack-ng, mdk4 or HackRF.
- Uploading plate reads or the precise track.

If a request crosses the line, ship the alert-only equivalent and note the refusal.

## Allowed behaviour
- Alert before a publicly mapped ALPR, speed or red-light camera from a local GeoJSON.
- Levels CLEAR, ADVISORY < 400 m, NEAR < 120 m, PASSING < 40 m, with hysteresis.
- Ahead-of-track: ±35° of GNSS course within 800 m. "Density ahead" is not an evasion route.
- ADS-B rows labelled `AIRCRAFT`, never `POLICE`.
- BLE: one beacon seen across more than 2 km of odometer raises `TRACKER?` once. Footnote false positives.
- Passive survey only: BSSID, SSID, RSSI, channel, GPS, timestamp; optional user OUI notes file;
  SQLite with 7-day rotation; no association.
- Dashcam tile is a heartbeat. Plate text discarded by default.
- Sample data banner, always: `SAMPLE PINS — NOT A LIVE MAP`.
- UI footnote: an alert is not proof a camera is present; no alert is not proof the road is clear.

## UI
Tokens: field `#07080b`, panel `#10141b`, brass `#c6a15b`, phosphor `#b6f27a`, alert `#ff3b30`, dim `#8b93a7`.
Share Tech Mono for figures; Cormorant Garamond for `SPECTER` only. Center bezel with outer ticks 0–120 mph and
an inner arc for threat distance; the speed numeral is the largest glyph. Decorative sweep labelled `COURSE`.
Left lug: next pin, bearing, meters. Right lug: five-deep alert stack, newest on top. Bottom rail: `OPTIC`,
`CORTEX`, `SURVEY`, `BLE`, `AIR`, `FABRIC (PLATES DROPPED)`. Engrave `SPECTER / MARKSMAN CLUSTER` and
`DET. ONLY`. Day theme: same layout, paper field, black figures. No crosshairs, skulls or "target locked".
800×480 first, fluid to 1280×720.

## Files
`README.md`, `LICENSE` (Apache-2.0), `docs/BOUNDARY.md`, `docs/HARDWARE.md`, `docs/DATA_SOURCES.md`,
`prompt/AGENT_PROMPT.md`, `pyproject.toml`, `requirements.txt`, `config.example.toml`, `install.sh`
(idempotent; Debian/Ubuntu/Pi OS; apt only `python3-venv python3-gps gpsd gpsd-clients`; venv at
`$HOME/.specter/venv`; user unit on `127.0.0.1:8770`; never `0.0.0.0`; print
`chromium --kiosk --app=http://127.0.0.1:8770`), `specter/{__init__,core,cameras,gps,adsb,ble_watch,survey,bus}.py`,
`cluster/{index.html,cluster.css,cluster.js}`, `data/cameras.sample.geojson`, `tests/test_cameras.py`,
`.github/workflows/ci.yml` (pytest + ruff on ubuntu-latest, no network).

## Data note
Document the Overpass ALPR query in `docs/DATA_SOURCES.md`. Fetch only with `--fetch-osm` and an explicit bbox.
Cite DeFlock (https://maps.deflock.org/) as incomplete OpenStreetMap community data, not evidence.

## Done when
`python -m specter.core --demo` works with no radio; the cluster at `http://127.0.0.1:8770` raises ADVISORY
then NEAR on a sample pin; the survey view shows synthetic receive-only rows; `docs/BOUNDARY.md` states the
jammer and hack refusal on its first screen; CI is green.
