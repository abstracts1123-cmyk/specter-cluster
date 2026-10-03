# BOUNDARY — what SPECTER refuses to do

**SPECTER is a detection and logging instrument. It will not jam anything and it will not hack anything.**
No jammer, no deauthentication, no camera attack, no concealment, no evasion routing, no plate upload.
These are refused permanently, not "not yet implemented". Pull requests that add any of them will be closed.

## Refusal list

| # | Refused | Alert-only equivalent that ships instead |
|---|---------|-------------------------------------------|
| 1 | **Jamming** of radio, GPS, cellular, radar, lidar or infrared, or any transmitter aimed at a camera, reader or radio. | A tone and a bezel alert *before* a publicly mapped camera. |
| 2 | **Damaging, blinding, dazzling, hacking, deauthenticating or disabling** a camera or its network. | Receive-only survey log of what was heard nearby. |
| 3 | **Plate covers, sprays, flips** or any other concealment. | Nothing. The plate stays readable. |
| 4 | **A route solver whose purpose is evading a stop** or interfering with an officer. | "Pins ahead" count within 800 m / ±35° of course. This is awareness, not a route. |
| 5 | **Wi-Fi cracking, association to camera backhaul, packet injection, deauth floods.** No aircrack-ng, mdk4 or HackRF dependency. | Passive survey: BSSID, SSID, RSSI, channel, GPS, timestamp. Never associates. |
| 6 | **Uploading plate reads or the precise track.** | Everything stays on the car computer's disk. Plate text is dropped by default. |

## How the code enforces this

- **Receive-only.** The only sockets opened are loopback clients (gpsd, dump1090) and the loopback server.
  The single outbound call is the OpenStreetMap fetch, which runs only with `--fetch-osm` and an explicit `--bbox`.
- **Loopback bind.** `specter-core` serves on `127.0.0.1:8770` and refuses other addresses without `--allow-lan`.
- **No plates on the wire.** The event bus strips any field containing "plate" unless the user runs with `--retain-plates-local`. Even then it stays on the local bus.
- **No position on the wire.** Websocket events carry speed, course and distance to pins, never latitude/longitude.
- **Survey is passive.** `specter/survey.py` stores rows handed to it by a capture tool the user runs. SPECTER never enters monitor mode, probes, associates or injects.
- **Aircraft are aircraft.** ADS-B rows are labelled `AIRCRAFT`, never `POLICE`.
- **No cloud.** No SMS, no webhook, no telemetry in the default config.

## Honest limits

- An alert is not proof a camera is present. No alert is not proof the road is clear.
- Community map data (DeFlock / OpenStreetMap) is incomplete and may be wrong.
- BLE `TRACKER?` is a guess. Other cars, phones and earbuds can follow you for miles.
- Following the law, including rules on monitoring devices and on recording wireless traffic where you live, is your responsibility.

## If a request crosses the line

The answer is the alert-only equivalent in the table above, plus a pointer to this file.
