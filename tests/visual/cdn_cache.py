"""The pages' CDN files (the room's three.js from jsdelivr, leaflet from unpkg, the brain page's three.js r128 from
cdnjs), fetched once with Python and served to the
headless browser from a local cache (issue #98, G8). Why: in a sandbox behind a TLS-inspecting proxy Chromium does not
trust the proxy's CA while Python (SSL_CERT_FILE) does; in CI it only saves repeated downloads. The cache directory is
not committed (tests/visual/.cdn_cache, see .gitignore)."""
import mimetypes
import re
import ssl
import urllib.request
from pathlib import Path

HOSTS = re.compile(r"^https://(cdn\.jsdelivr\.net|unpkg\.com|cdnjs\.cloudflare\.com)/")
TYPES = {".js": "application/javascript", ".mjs": "application/javascript", ".css": "text/css", ".json": "application/json",
         ".png": "image/png", ".svg": "image/svg+xml", ".woff2": "font/woff2"}


class CdnCache:
    def __init__(self, directory):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ctx = ssl.create_default_context()           # honours SSL_CERT_FILE; proxies come from the environment
        self.misses = 0
        self.hits = 0
        self.failed = []

    def path_for(self, url):
        m = HOSTS.match(url)
        host = m.group(1)
        rel = url[len("https://") + len(host) + 1:].split("?")[0]
        return self.dir / host / rel

    def fetch(self, url):
        p = self.path_for(url)
        if p.exists():
            self.hits += 1
            return p
        req = urllib.request.Request(url, headers={"User-Agent": "sub01-visual-qa/1.0"})
        with urllib.request.urlopen(req, context=self.ctx, timeout=60) as r:
            data = r.read()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        self.misses += 1
        return p

    def route(self, route):
        """A Playwright route handler: serve from the cache, fetching on a miss; fall through to the network on error."""
        url = route.request.url
        try:
            p = self.fetch(url)
        except Exception as e:                            # noqa: BLE001
            self.failed.append(f"{url}: {e!r}")
            return route.continue_()
        ct = TYPES.get(p.suffix.lower()) or mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        route.fulfill(path=str(p), content_type=ct, headers={"access-control-allow-origin": "*"})

    def install(self, page):
        page.route(HOSTS, self.route)
