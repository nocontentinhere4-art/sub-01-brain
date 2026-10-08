"""One-time fetch of his small Kichijoji area from OpenStreetMap into web/tokyo_area.json (issue #43).

The room's map card and /life used to load raster tiles from tile.openstreetmap.org, which the OSMF tile usage policy
does not allow for a public site. This script makes one Overpass API query for a box of about 2 x 1.5 km around the
places in web/tokyo_routes.json (roads, footpaths, rail, buildings, parks, water), simplifies the geometry and writes
a small static file that both pages draw with Leaflet vector layers. Run it by hand and commit the result:

    python room_build/osm_area.py                      # writes web/tokyo_area.json
    python room_build/osm_area.py --raw cache.json     # also keep the raw Overpass answer (or reuse it if present)

Never run at server start. Data: (c) OpenStreetMap contributors, ODbL (https://www.openstreetmap.org/copyright).

Output format: coordinates are integers in 1e-5 degrees (about 1 m) relative to `origin` [lat, lng]; each shape is a
flat delta-encoded list [lat0, lng0, dlat1, dlng1, ...] (the first pair relative to `origin`, the rest to the
previous point). `layers` maps a layer name to a list of shapes; polygon layers are closed implicitly.
"""
import argparse
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTES = ROOT / "web" / "tokyo_routes.json"
OUT = ROOT / "web" / "tokyo_area.json"
ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"]
HALF_W_M, HALF_H_M = 1000, 750          # 2 x 1.5 km
SCALE = 1e5                             # 1e-5 degrees per unit

MAJOR = {"motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link", "trunk_link", "primary_link",
         "secondary_link", "tertiary_link"}
MINOR = {"residential", "unclassified", "living_street", "service", "road", "pedestrian"}
PATH = {"footway", "path", "steps", "cycleway", "track", "bridleway"}
GREEN_LEISURE = {"park", "garden", "playground", "pitch", "nature_reserve", "common"}
GREEN_LANDUSE = {"grass", "forest", "recreation_ground", "cemetery", "meadow", "village_green", "orchard"}
# simplification tolerance (metres) per layer
TOL = {"water": 1.5, "green": 2.0, "building": 1.0, "rail": 2.0, "major": 1.5, "minor": 1.5, "path": 1.5}


def bbox_around(places):
    lats = [p[0] for p in places.values()]
    lngs = [p[1] for p in places.values()]
    lat0, lng0 = (min(lats) + max(lats)) / 2, (min(lngs) + max(lngs)) / 2
    dlat = HALF_H_M / 111_320
    dlng = HALF_W_M / (111_320 * math.cos(math.radians(lat0)))
    return [round(lat0 - dlat, 5), round(lng0 - dlng, 5), round(lat0 + dlat, 5), round(lng0 + dlng, 5)]


def query(bbox):
    b = ",".join(str(x) for x in bbox)
    return f"""[out:json][timeout:120];
(
  way["highway"]({b});
  way["railway"~"^(rail|subway|light_rail)$"]({b});
  way["building"]({b});
  way["leisure"~"^({'|'.join(sorted(GREEN_LEISURE))})$"]({b});
  way["landuse"~"^({'|'.join(sorted(GREEN_LANDUSE))})$"]({b});
  way["natural"~"^(wood|water|scrub|grassland)$"]({b});
  way["waterway"~"^(river|stream|canal)$"]({b});
  relation["natural"="water"]({b});
  relation["leisure"="park"]({b});
  relation["building"]({b});
);
out geom;"""


def fetch(q):
    data = urllib.parse.urlencode({"data": q}).encode()
    last = None
    for url in ENDPOINTS:
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "sub-01 osm_area.py (one-time fetch)"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read())
        except Exception as e:  # try the next public instance
            print(f"{url}: {e}")
            last = e
    raise SystemExit(f"Overpass failed: {last}")


def classify(tags):
    if tags.get("natural") == "water" or "waterway" in tags:
        return "water"
    if tags.get("railway"):
        return "rail"
    hw = tags.get("highway")
    if hw:
        if hw in MAJOR:
            return "major"
        if hw in MINOR:
            return "minor"
        if hw in PATH:
            return "path"
        return None
    if tags.get("building"):
        return "building"
    if (tags.get("leisure") in GREEN_LEISURE or tags.get("landuse") in GREEN_LANDUSE
            or tags.get("natural") in {"wood", "scrub", "grassland"}):
        return "green"
    return None


LINES = {"rail", "major", "minor", "path"}


def dp(pts, tol_m, kx):
    """Douglas-Peucker on (lat, lng) points; kx scales longitude degrees to latitude degrees."""
    if len(pts) < 3:
        return pts
    tol = tol_m / 111_320
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ay, ax = pts[a][0], pts[a][1] * kx
        by, bx = pts[b][0], pts[b][1] * kx
        dy, dx = by - ay, bx - ax
        n = math.hypot(dx, dy)
        best, bi = -1.0, -1
        for i in range(a + 1, b):
            py, px = pts[i][0], pts[i][1] * kx
            d = abs(dx * (ay - py) - dy * (ax - px)) / n if n else math.hypot(px - ax, py - ay)
            if d > best:
                best, bi = d, i
        if best > tol:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(pts, keep) if k]


def clip_line(pts, box):
    """Split a polyline into runs inside the box, keeping one point beyond each edge so lines reach the border."""
    s, w, n, e = box
    inside = [s <= p[0] <= n and w <= p[1] <= e for p in pts]
    runs, cur = [], []
    for i, p in enumerate(pts):
        near = inside[i] or (i > 0 and inside[i - 1]) or (i + 1 < len(pts) and inside[i + 1])
        if near:
            cur.append(p)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return [r for r in runs if len(r) >= 2]


def join_rings(ways):
    """Join a relation's outer member ways (lists of points) into closed rings."""
    ways = [list(w) for w in ways if len(w) >= 2]
    rings = []
    while ways:
        ring = ways.pop()
        changed = True
        while ring[0] != ring[-1] and changed:
            changed = False
            for i, w in enumerate(ways):
                if w[0] == ring[-1]:
                    ring += w[1:]
                elif w[-1] == ring[-1]:
                    ring += w[-2::-1]
                elif w[-1] == ring[0]:
                    ring = w[:-1] + ring
                elif w[0] == ring[0]:
                    ring = w[:0:-1] + ring
                else:
                    continue
                ways.pop(i)
                changed = True
                break
        rings.append(ring)
    return rings


def encode(pts, origin):
    out = []
    py, px = round(origin[0] * SCALE), round(origin[1] * SCALE)
    for lat, lng in pts:
        y, x = round(lat * SCALE), round(lng * SCALE)
        if out and y == py and x == px:
            continue
        out += [y - py, x - px]
        py, px = y, x
    return out


def build(osm, bbox, places):
    origin = [bbox[0], bbox[1]]
    kx = math.cos(math.radians((bbox[0] + bbox[2]) / 2))
    m = 0.0005                                   # ~50 m margin for clipping
    box = [bbox[0] - m, bbox[1] - m, bbox[2] + m, bbox[3] + m]
    layers = {k: [] for k in ["green", "water", "stream", "building", "rail", "major", "minor", "path"]}
    for el in osm["elements"]:
        layer = classify(el.get("tags", {}))
        if not layer:
            continue
        if el["type"] == "way":
            shapes = [[(g["lat"], g["lon"]) for g in el.get("geometry", [])]]
            if layer == "water" and "waterway" in el.get("tags", {}):
                layer = "stream"
        else:
            outer = [[(g["lat"], g["lon"]) for g in mb.get("geometry", [])]
                     for mb in el.get("members", []) if mb.get("type") == "way" and mb.get("role", "outer") in ("outer", "")]
            shapes = join_rings(outer)
        for pts in shapes:
            if len(pts) < 2:
                continue
            if layer in LINES or layer == "stream":
                for run in clip_line(pts, box):
                    run = dp(run, TOL.get(layer, 1.5), kx)
                    layers[layer].append(encode(run, origin))
            else:
                if pts[0] == pts[-1]:
                    pts = pts[:-1]
                if len(pts) < 3:
                    continue
                lats, lngs = [p[0] for p in pts], [p[1] for p in pts]
                if max(lats) < box[0] or min(lats) > box[2] or max(lngs) < box[1] or min(lngs) > box[3]:
                    continue
                pts = dp(pts + [pts[0]], TOL[layer], kx)[:-1]
                if len(pts) >= 3:
                    layers[layer].append(encode(pts, origin))
    return {
        "attribution": "© OpenStreetMap contributors (ODbL)",
        "license": "https://www.openstreetmap.org/copyright",
        "source": "OpenStreetMap via one Overpass API query (room_build/osm_area.py)",
        "osm_base": osm.get("osm3s", {}).get("timestamp_osm_base", ""),
        "bbox": bbox,
        "origin": origin,
        "scale": SCALE,
        "places": places,
        "layers": layers,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--raw", type=Path, help="raw Overpass JSON: read it if it exists, else fetch and save it there")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    places = json.loads(ROUTES.read_text())["places"]
    bbox = bbox_around(places)
    if a.raw and a.raw.exists():
        osm = json.loads(a.raw.read_text())
    else:
        osm = fetch(query(bbox))
        if a.raw:
            a.raw.write_text(json.dumps(osm))
    area = build(osm, bbox, places)
    text = json.dumps(area, separators=(",", ":"), ensure_ascii=False)
    a.out.write_text(text)
    import gzip
    counts = ", ".join(f"{k} {len(v)}" for k, v in area["layers"].items())
    print(f"{a.out}: {len(text) / 1024:.0f} KB, {len(gzip.compress(text.encode())) / 1024:.0f} KB gzipped; {counts}")


if __name__ == "__main__":
    main()
