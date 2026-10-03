import json
import socket
from pathlib import Path

import pytest

from specter.cameras import (
    SAMPLE_BANNER,
    Camera,
    CameraMonitor,
    Level,
    angle_diff,
    bearing_deg,
    haversine_m,
    in_heading_gate,
    load_cameras,
    next_level,
    osm_to_geojson,
    overpass_query,
    parse_bbox,
    parse_geojson,
    raw_level,
)
from specter.gps import offset

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "cameras.sample.geojson"


def test_haversine_known_values():
    assert haversine_m(40.0, -100.0, 40.0, -100.0) == 0.0
    # one degree of latitude is ~111.19 km
    assert haversine_m(0.0, 0.0, 1.0, 0.0) == pytest.approx(111_195, rel=1e-3)
    # symmetric
    a, b = (40.7128, -74.0060), (51.5074, -0.1278)
    assert haversine_m(*a, *b) == pytest.approx(haversine_m(*b, *a))
    assert haversine_m(*a, *b) == pytest.approx(5_570_000, rel=5e-3)


def test_bearing_cardinals():
    assert bearing_deg(0, 0, 1, 0) == pytest.approx(0)
    assert bearing_deg(0, 0, 0, 1) == pytest.approx(90)
    assert bearing_deg(0, 0, -1, 0) == pytest.approx(180)
    assert bearing_deg(0, 0, 0, -1) == pytest.approx(270)


def test_angle_diff_wraps():
    assert angle_diff(350, 10) == 20
    assert angle_diff(10, 350) == 20
    assert angle_diff(0, 180) == 180


def test_heading_gate_edges():
    assert in_heading_gate(0, 35)
    assert in_heading_gate(0, 325)
    assert not in_heading_gate(0, 35.1)
    assert not in_heading_gate(0, 180)
    assert in_heading_gate(355, 20)  # wraps across north
    assert not in_heading_gate(None, 0)  # no course, no "ahead"


@pytest.mark.parametrize(
    ("dist", "level"),
    [(500, Level.CLEAR), (399, Level.ADVISORY), (119, Level.NEAR), (39, Level.PASSING)],
)
def test_raw_levels(dist, level):
    assert raw_level(dist) == level


def test_hysteresis_does_not_flap():
    # entering NEAR at 119 m, then jittering around the 120 m line stays NEAR
    level = next_level(119, Level.ADVISORY)
    assert level == Level.NEAR
    for d in (121, 125, 119, 130, 137):
        level = next_level(d, level)
        assert level == Level.NEAR
    # leaves NEAR only past 120 * 1.15 = 138 m, falling to ADVISORY
    assert next_level(139, Level.NEAR) == Level.ADVISORY
    # escalation is immediate
    assert next_level(39, Level.CLEAR) == Level.PASSING


def test_monitor_alerts_ahead_only():
    cam = Camera(id=0, lat=40.0, lon=-100.0, name="P")
    mon = CameraMonitor([cam])
    south = offset(40.0, -100.0, -300, 0)
    snap = mon.update(*south, course=0.0)  # driving toward the pin
    assert snap.level == Level.ADVISORY and snap.ahead_count == 1
    assert [p.level for p in snap.escalations] == [Level.ADVISORY]

    mon2 = CameraMonitor([cam])
    assert mon2.update(*south, course=180.0).level == Level.CLEAR  # driving away
    assert mon2.update(*south, course=None).level == Level.CLEAR  # no course


def test_monitor_ignores_distant_pins():
    cam = Camera(id=0, lat=40.0, lon=-100.0)
    far = offset(40.0, -100.0, -2000, 0)
    snap = CameraMonitor([cam]).update(*far, course=0.0)
    assert snap.level == Level.CLEAR and snap.ahead_count == 0 and snap.nearest is None


def test_density_ahead_counts_within_range_and_gate():
    cams = [
        Camera(0, *offset(40, -100, 700, 0)),
        Camera(1, *offset(40, -100, 900, 0)),  # past 800 m
        Camera(2, *offset(40, -100, 0, 700)),  # off to the side
    ]
    snap = CameraMonitor(cams).update(40.0, -100.0, 0.0)
    assert snap.ahead_count == 1


def test_geojson_rejects_features_without_coordinates():
    data = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": None, "properties": {}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": []}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [200, 0]}},
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-100, 40]},
                "properties": {"name": "ok", "kind": "speed", "direction": 450},
            },
        ],
    }
    cams = parse_geojson(data)
    assert len(cams.cameras) == 1 and cams.rejected == 3
    assert cams.cameras[0].kind == "speed" and cams.cameras[0].direction == 90
    with pytest.raises(ValueError):
        parse_geojson({"type": "Feature"})


def test_sample_file_cannot_be_labeled_live():
    cams = load_cameras(SAMPLE)
    assert len(cams.cameras) >= 3
    assert cams.sample and not cams.live
    assert cams.banner == SAMPLE_BANNER == "SAMPLE PINS \u2014 NOT A LIVE MAP"
    assert all(c.source == "sample" for c in cams.cameras)


def test_sample_stays_sample_even_if_file_claims_live(tmp_path):
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    data["sample"] = False
    data["live"] = True
    # source=sample on every feature still marks it as sample
    assert not parse_geojson(data).live
    # and so does a sample file name, even if features are relabeled
    for f in data["features"]:
        f["properties"]["source"] = "osm"
    path = tmp_path / "cameras.sample.geojson"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert not load_cameras(path).live
    other = tmp_path / "cameras.geojson"
    other.write_text(json.dumps(data), encoding="utf-8")
    assert load_cameras(other).live


def test_overpass_query_and_osm_conversion():
    q = overpass_query(parse_bbox("40,-101,41,-100"))
    assert '["surveillance:type"="ALPR"](40.000000,-101.000000,41.000000,-100.000000)' in q
    assert q.rstrip().endswith("out center;")
    with pytest.raises(ValueError):
        parse_bbox("41,-100,40,-101")
    gj = osm_to_geojson(
        {
            "elements": [
                {"type": "node", "id": 1, "lat": 40.1, "lon": -100.1, "tags": {"operator": "X"}},
                {"type": "way", "id": 2, "center": {"lat": 40.2, "lon": -100.2}},
                {"type": "way", "id": 3},
            ]
        }
    )
    cams = parse_geojson(gj)
    assert len(cams.cameras) == 2 and cams.live


def test_tests_cannot_reach_the_network():
    with pytest.raises(RuntimeError, match="blocked"):
        socket.create_connection(("93.184.216.34", 80), timeout=1)
