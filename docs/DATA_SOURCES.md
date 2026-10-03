# Data sources

SPECTER is offline-first. It reads local files and local sockets; nothing is fetched at runtime.

| Source | How | Network |
|--------|-----|---------|
| GNSS fix | `gpsd` on `127.0.0.1:2947` (JSON watch, read-only) | none |
| Camera pins | local GeoJSON (`~/.specter/cameras.geojson`, `--cameras`, or `cameras.path`) | none |
| ADS-B | `dump1090` SBS on `127.0.0.1:30003` (optional) | none |
| BLE | `bleak` passive scan (optional) | none |
| Wi-Fi survey | JSON-lines file from a passive capture tool you run (`survey.source`) | none |
| OUI notes | text file you supply (`survey.oui_notes`) | none |
| Dashcam heartbeat | `specter-bridge` on the car LAN (optional) | LAN only |

Private feeds are never scraped.

## Camera file format

A GeoJSON `FeatureCollection` of `Point` features (`[lon, lat]`). Properties:
`name`, `operator`, `kind` (`alpr`, `speed`, `redlight`), `direction` (degrees), `source`, `observed`.
Features with no usable coordinates are rejected and counted.

`data/cameras.sample.geojson` is **synthetic**. Any file with `"sample": true`, a feature with
`"source": "sample"`, or `sample` in its file name is treated as a sample and the cluster always shows
`SAMPLE PINS — NOT A LIVE MAP`. A sample set can never be labelled live.

## OpenStreetMap / DeFlock (explicit opt-in)

[DeFlock](https://maps.deflock.org/) shows ALPR locations that volunteers have mapped in OpenStreetMap.
That is **incomplete community data, not evidence**: pins can be missing, stale or wrong.

SPECTER only talks to the network when you run it with `--fetch-osm` **and** an explicit bounding box
(`south,west,north,east`). It then runs this Overpass query once, writes `~/.specter/cameras.geojson`, and exits:

```text
[out:json][timeout:60];
(
  node["man_made"="surveillance"]["surveillance:type"="ALPR"]({{bbox}});
  way["man_made"="surveillance"]["surveillance:type"="ALPR"]({{bbox}});
);
out center;
```

`{{bbox}}` is replaced by your bounding box. Example:

```sh
python -m specter.core --fetch-osm --bbox 40.70,-74.05,40.80,-73.90
```

Respect the Overpass usage policy: keep boxes small and do not loop. Speed and red-light cameras are
not covered by this query; add them to your own GeoJSON from sources you are permitted to use.

## Plate text

Predator Fabric events may contain plate text. `specter-bridge fabric-in` and the event bus drop it by
default. `--retain-plates-local` keeps it on the local bus only. Plates are never uploaded.
