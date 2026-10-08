"""Playwright driver for room_build/charfix/view.html: python shoot.py <spec.json> -- spec: {"out": dir, "jobs": [{"glb", "opt", "shots": [{"name", "p", "t", "fov"}]}]}"""
import base64, json, sys, threading, functools, http.server, socketserver
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[2]
spec = json.loads(Path(sys.argv[1]).read_text()); out = Path(spec["out"]); out.mkdir(parents=True, exist_ok=True)
H = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT)); H.log_message = lambda *a: None
srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None,
                           args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
    pg = b.new_page(viewport={"width": spec.get("w", 640), "height": spec.get("h", 640)})
    pg.on("console", lambda m: print("console:", m.text) if m.type == "error" else None)
    pg.goto(f"http://127.0.0.1:{port}/room_build/charfix/view.html?w={spec.get('w', 640)}&h={spec.get('h', 640)}"); pg.wait_for_function("window.ready")
    for job in spec["jobs"]:
        print(job["glb"], pg.evaluate("([u, o]) => load(u, o)", [job["glb"], job.get("opt", {})]))
        for js in job.get("pre", []): pg.evaluate(js)
        for s in job["shots"]:
            if "js" in s: pg.evaluate(s["js"])
            u = pg.evaluate("([p, t, f]) => shot(p, t, f)", [s["p"], s["t"], s.get("fov", 30)])
            (out / f"{s['name']}.png").write_bytes(base64.b64decode(u.split(",", 1)[1]))
    b.close()
srv.shutdown()
