"""Camera pins: GeoJSON loading, geometry, heading gate and level hysteresis.

Detection only. This module never transmits anything; the single network
function, ``fetch_osm``, runs only when the user passes ``--fetch-osm`` with an
explicit bounding box.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

EARTH_RADIUS_M = 6_371_000.0

ADVISORY_M = 400.0
NEAR_M = 120.0
PASSING_M = 40.0
AHEAD_RANGE_M = 800.0
AHEAD_DEG = 35.0
HOLD_DEG = 10.0  # extra heading slack for a pin that is already alerting
HYSTERESIS = 0.15  # a level is held until distance exceeds threshold * 1.15

SAMPLE_BANNER = "SAMPLE PINS \u2014 NOT A LIVE MAP"
KINDS = ("alpr", "speed", "redlight")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_QUERY = """[out:json][timeout:60];
(
  node["man_made"="surveillance"]["surveillance:type"="ALPR"]({{bbox}});
  way["man_made"="surveillance"]["surveillance:type"="ALPR"]({{bbox}});
);
out center;"""


class Level(IntEnum):
    CLEAR = 0
    ADVISORY = 1
    NEAR = 2
    PASSING = 3


_THRESHOLDS = {
    Level.ADVISORY: ADVISORY_M,
    Level.NEAR: NEAR_M,
    Level.PASSING: PASSING_M,
}


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlmb = math.radians(lon2 - lon1)
    y = math.sin(dlmb) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlmb)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angle_diff(a: float, b: float) -> float:
    """Smallest absolute difference between two compass angles, 0..180."""
    d = abs(a - b) % 360.0
    return 360.0 - d if d > 180.0 else d


def in_heading_gate(course: float | None, bearing: float, limit: float = AHEAD_DEG) -> bool:
    """True when the pin bearing is within +/-limit degrees of the GNSS course."""
    if course is None:
        return False
    return angle_diff(course, bearing) <= limit


def raw_level(distance_m: float) -> Level:
    """Level from distance alone, with no hysteresis."""
    if distance_m < PASSING_M:
        return Level.PASSING
    if distance_m < NEAR_M:
        return Level.NEAR
    if distance_m < ADVISORY_M:
        return Level.ADVISORY
    return Level.CLEAR


def next_level(distance_m: float, previous: Level) -> Level:
    """Level with hysteresis: escalate immediately, de-escalate only past a margin."""
    raw = raw_level(distance_m)
    if raw >= previous or previous == Level.CLEAR:
        return raw
    if distance_m <= _THRESHOLDS[previous] * (1.0 + HYSTERESIS):
        return previous
    return raw


@dataclass(frozen=True)
class Camera:
    id: int
    lat: float
    lon: float
    name: str = ""
    operator: str = ""
    kind: str = "alpr"
    direction: float | None = None
    source: str = ""
    observed: str = ""


@dataclass(frozen=True)
class CameraSet:
    cameras: tuple[Camera, ...]
    sample: bool
    rejected: int = 0

    @property
    def live(self) -> bool:
        """A sample set can never be live; this is derived, not configurable."""
        return not self.sample

    @property
    def banner(self) -> str:
        return SAMPLE_BANNER if self.sample else ""


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _parse_feature(index: int, feature: object) -> Camera | None:
    if not isinstance(feature, dict):
        return None
    geom = feature.get("geometry")
    if not isinstance(geom, dict) or geom.get("type") != "Point":
        return None
    coords = geom.get("coordinates")
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None
    lon, lat = _number(coords[0]), _number(coords[1])
    if lon is None or lat is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    props = feature.get("properties") or {}
    if not isinstance(props, dict):
        props = {}
    kind = str(props.get("kind", "alpr")).lower()
    if kind not in KINDS:
        kind = "alpr"
    direction = _number(props.get("direction"))
    return Camera(
        id=index,
        lat=lat,
        lon=lon,
        name=str(props.get("name", "")),
        operator=str(props.get("operator", "")),
        kind=kind,
        direction=None if direction is None else direction % 360.0,
        source=str(props.get("source", "")),
        observed=str(props.get("observed", "")),
    )


def parse_geojson(data: object, *, sample_hint: bool = False) -> CameraSet:
    """Parse a FeatureCollection. Features without usable coordinates are rejected."""
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise ValueError("camera file must be a GeoJSON FeatureCollection")
    features = data.get("features")
    if not isinstance(features, list):
        raise ValueError("FeatureCollection has no features list")
    cameras: list[Camera] = []
    rejected = 0
    for i, feat in enumerate(features):
        cam = _parse_feature(i, feat)
        if cam is None:
            rejected += 1
        else:
            cameras.append(cam)
    sample = (
        sample_hint
        or data.get("sample") is True
        or any(c.source.lower() == "sample" for c in cameras)
    )
    return CameraSet(tuple(cameras), sample=sample, rejected=rejected)


def load_cameras(path: str | Path) -> CameraSet:
    path = Path(path)
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return parse_geojson(data, sample_hint="sample" in path.name.lower())


# --- live evaluation ---------------------------------------------------------


@dataclass
class PinState:
    camera: Camera
    distance_m: float
    bearing: float
    level: Level
    ahead: bool


@dataclass
class Snapshot:
    level: Level = Level.CLEAR
    nearest: PinState | None = None
    ahead_count: int = 0
    escalations: list[PinState] = field(default_factory=list)


class CameraMonitor:
    """Tracks per-pin levels (with hysteresis) as GNSS fixes arrive."""

    def __init__(self, cameras: CameraSet | tuple[Camera, ...]):
        self.cameras = cameras.cameras if isinstance(cameras, CameraSet) else tuple(cameras)
        self._levels: dict[int, Level] = {}

    def update(self, lat: float, lon: float, course: float | None) -> Snapshot:
        snap = Snapshot()
        for cam in self.cameras:
            dist = haversine_m(lat, lon, cam.lat, cam.lon)
            prev = self._levels.get(cam.id, Level.CLEAR)
            if dist > AHEAD_RANGE_M * (1.0 + HYSTERESIS) and prev == Level.CLEAR:
                continue
            brg = bearing_deg(lat, lon, cam.lat, cam.lon)
            gate = AHEAD_DEG + (HOLD_DEG if prev != Level.CLEAR else 0.0)
            ahead = dist <= AHEAD_RANGE_M and in_heading_gate(course, brg, gate)
            in_zone = (
                dist < PASSING_M * (1.0 + HYSTERESIS) if prev == Level.PASSING else dist < PASSING_M
            )
            level = next_level(dist, prev) if (ahead or in_zone) else Level.CLEAR
            self._levels[cam.id] = level
            state = PinState(cam, dist, brg, level, ahead)
            if level > prev:
                snap.escalations.append(state)
            if ahead:
                snap.ahead_count += 1
            if level > snap.level:
                snap.level = level
            if (ahead or level > Level.CLEAR) and (
                snap.nearest is None or dist < snap.nearest.distance_m
            ):
                snap.nearest = state
        return snap


# --- optional OpenStreetMap fetch (explicit opt-in only) ----------------------


def parse_bbox(text: str) -> tuple[float, float, float, float]:
    """Parse 'south,west,north,east' and validate it."""
    try:
        s, w, n, e = (float(p) for p in text.split(","))
    except ValueError as exc:
        raise ValueError("bbox must be 'south,west,north,east'") from exc
    if not (-90 <= s < n <= 90 and -180 <= w < e <= 180):
        raise ValueError("bbox out of range or inverted")
    return s, w, n, e


def overpass_query(bbox: tuple[float, float, float, float]) -> str:
    return OVERPASS_QUERY.replace("{{bbox}}", ",".join(f"{v:.6f}" for v in bbox))


def osm_to_geojson(data: dict, observed: str = "") -> dict:
    """Convert an Overpass JSON response (``out center``) to a camera FeatureCollection."""
    features = []
    for el in data.get("elements", []):
        pos = el if "lat" in el else el.get("center")
        if not pos or "lat" not in pos or "lon" not in pos:
            continue
        tags = el.get("tags", {})
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [pos["lon"], pos["lat"]]},
                "properties": {
                    "name": tags.get("name", f"osm/{el.get('type', 'node')}/{el.get('id', '')}"),
                    "operator": tags.get("operator", ""),
                    "kind": "alpr",
                    "direction": _number(tags.get("direction")),
                    "source": "osm",
                    "observed": observed,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def fetch_osm(bbox: tuple[float, float, float, float], url: str = OVERPASS_URL) -> dict:
    """Fetch ALPR nodes for an explicit bbox. The only network call in the project."""
    import urllib.parse
    import urllib.request
    from datetime import date

    body = urllib.parse.urlencode({"data": overpass_query(bbox)}).encode()
    req = urllib.request.Request(url, data=body, headers={"User-Agent": "specter-cluster/0.1"})
    with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310 - fixed https URL
        payload = json.load(resp)
    return osm_to_geojson(payload, observed=date.today().isoformat())
