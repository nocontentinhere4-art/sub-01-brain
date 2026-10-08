"""Poly Haven helper.  ph.py info id...   |  ph.py model res id...  |  ph.py tex res id...
model: downloads the glTF (+bin, +textures) into assets/<id>/ ; tex: downloads diff/nor_gl/rough/arm jpgs into tex/<id>/"""
import sys, os, json, urllib.request
UA = {"User-Agent": "sub01-room-builder/1.0"}
ROOT = os.path.dirname(os.path.abspath(__file__))
def get(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read()
def save(u, p):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if not os.path.exists(p): open(p, "wb").write(get(u))
cmd = sys.argv[1]
if cmd == "info":
    for k in sys.argv[2:]:
        d = json.loads(get(f"https://api.polyhaven.com/info/{k}"))
        print(k, "poly", d.get("polycount"), "dim", d.get("dimensions"), "authors", list(d.get("authors", {}).keys()))
elif cmd == "model":
    res = sys.argv[2]
    for k in sys.argv[3:]:
        f = json.loads(get(f"https://api.polyhaven.com/files/{k}"))["gltf"][res]["gltf"]
        d = f"{ROOT}/assets/{k}"
        save(f["url"], f"{d}/{k}.gltf")
        for rel, inc in f.get("include", {}).items(): save(inc["url"], f"{d}/{rel}")
        print(k, "ok", sum(os.path.getsize(os.path.join(r, x)) for r, _, fs in os.walk(d) for x in fs))
elif cmd == "tex":
    res = sys.argv[2]
    for k in sys.argv[3:]:
        f = json.loads(get(f"https://api.polyhaven.com/files/{k}"))
        out = {}
        for m in ["Diffuse", "nor_gl", "Rough", "arm", "AO", "Displacement"]:
            if m in f and res in f[m]:
                fmt = "jpg" if "jpg" in f[m][res] else "png"
                save(f[m][res][fmt]["url"], f"{ROOT}/tex/{k}/{m}.{fmt}"); out[m] = fmt
        d = json.loads(get(f"https://api.polyhaven.com/info/{k}"))
        print(k, out, "dim", d.get("dimensions"), "authors", list(d.get("authors", {}).keys()))
