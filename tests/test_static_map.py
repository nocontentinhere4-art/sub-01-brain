"""Issue #43: the map cards draw a static OSM extract, never tiles from tile.openstreetmap.org."""
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
AREA = WEB / "tokyo_area.json"
GZ_BUDGET = 400 * 1024
sys.path.insert(0, str(ROOT / "room_build"))


def decode(shape, area):
    s = area["scale"]
    y, x = round(area["origin"][0] * s), round(area["origin"][1] * s)
    pts = []
    for i in range(0, len(shape), 2):
        y += shape[i]
        x += shape[i + 1]
        pts.append((y / s, x / s))
    return pts


def test_no_page_uses_osm_tile_servers():
    hits = [str(p.relative_to(ROOT)) for p in WEB.rglob("*")
            if p.is_file() and p.suffix in {".html", ".js", ".css", ".json", ".md"}
            and re.search(r"tile\.openstreetmap\.org|\{z\}/\{x\}/\{y\}|tileLayer", p.read_text(errors="ignore"))]
    assert hits == []


def test_area_loads_covers_places_and_fits_budget():
    raw = AREA.read_bytes()
    assert len(gzip.compress(raw)) < GZ_BUDGET
    area = json.loads(raw)
    s, w, n, e = area["bbox"]
    places = json.loads((WEB / "tokyo_routes.json").read_text())["places"]
    assert set(places) >= {"home", "bakery", "park", "shop"}
    for lat, lng in places.values():
        assert s < lat < n and w < lng < e
    for k in ("building", "minor", "major", "path", "green", "water", "rail"):
        assert area["layers"][k], k
    pts = [p for k in ("minor", "major") for sh in area["layers"][k] for p in decode(sh, area)]
    for name, (lat, lng) in places.items():         # a street within ~80 m of every place
        assert min((lat - a) ** 2 + ((lng - b) * 0.81) ** 2 for a, b in pts) < (80 / 111_320) ** 2, name
    assert "OpenStreetMap" in area["attribution"] and "ODbL" in area["attribution"]


def test_pages_draw_area_with_attribution():
    for page in ("room.html", "life.html"):
        t = (WEB / page).read_text()
        assert "tokyo_area.json" in t and "drawArea" in t, page
        assert "openstreetmap.org/copyright" in t and "contributors (ODbL)" in t, page


def test_encoding_roundtrip():
    import osm_area
    origin = [35.69676, 139.56439]
    pts = [(35.70715, 139.5716), (35.70545, 139.57455), (35.69985, 139.5742)]
    area = {"scale": osm_area.SCALE, "origin": origin}
    got = decode(osm_area.encode(pts, origin), area)
    assert all(abs(a - c) < 1e-9 and abs(b - d) < 1e-9 for (a, b), (c, d) in zip(pts, got))
    rings = osm_area.join_rings([[(0, 0), (0, 1)], [(1, 1), (0, 1)], [(1, 1), (0, 0)]])
    assert len(rings) == 1 and rings[0][0] == rings[0][-1]
