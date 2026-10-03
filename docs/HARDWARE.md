# Hardware

SPECTER needs a small Linux computer, a GNSS receiver, and a display. Everything is receive-only.
There are no transmitters in this build list, and none will be added (see [BOUNDARY.md](BOUNDARY.md)).

## Required

| Part | Notes |
|------|-------|
| Raspberry Pi 5 (4 GB is plenty) or any Debian/Ubuntu box | Pi OS Bookworm 64-bit or later. Python 3.11+. |
| Quality 12 V to 5 V USB-C supply for the car | Use a supply rated for the Pi 5 (5 V / 5 A) and add a fuse in the 12 V feed. |
| USB GNSS receiver | u-blox 7/8/M10 class puck, 1 Hz or better, with a clear sky view on the dash. Read through `gpsd`. |
| Display, 800×480 or 1024×600 | HDMI or DSI. Sunlight-readable if you can; the Day theme helps. |
| Storage | 16 GB+ A1 card or small SSD. The survey DB rotates at 7 days. |

## Optional (all receive-only)

| Part | Used for |
|------|----------|
| RTL-SDR dongle + `dump1090` | ADS-B list on `127.0.0.1:30003`. Receive-only. |
| Bluetooth LE adapter (the Pi 5 built-in works) | BLE tracker persistence watcher (needs `pip install bleak`). |
| A Wi-Fi adapter you already operate a passive capture tool on | Feeds the survey log through a JSON-lines file. SPECTER does not drive it. |
| Predator / Optic / Cortex on the car LAN | Dashcam heartbeat tiles via `specter-bridge`. Not a dependency of the core. |

## Not on this list, by design

Transmitters of any kind aimed at a camera, reader or radio; signal jammers; HackRF or similar for injection;
Wi-Fi adapters used for deauthentication or association to infrastructure; plate covers or other concealment.

## Setup notes

1. Install gpsd and point it at the receiver: `/etc/default/gpsd` → `DEVICES="/dev/ttyACM0"`, `GPSD_OPTIONS="-n"`.
2. Check the fix: `cgps -s`.
3. Run `./install.sh`, then open `http://127.0.0.1:8770` in kiosk mode:
   `chromium --kiosk --app=http://127.0.0.1:8770`
   Add `--autoplay-policy=no-user-gesture-required` if you want the local alert tones without tapping SOUND.
4. Fonts: Share Tech Mono and Cormorant Garamond are used if installed locally, otherwise the cluster
   falls back to system monospace/serif. To bundle them, drop `ShareTechMono-Regular.woff2` and
   `CormorantGaramond-Regular.woff2` into `cluster/fonts/`. The cluster never fetches fonts from the network.
