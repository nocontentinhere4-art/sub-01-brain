"""Logged-in sessions for SUB-01's own TikTok and YouTube accounts (#60): view-only feeds.

The owner logs in once in a normal browser and exports the cookies (Cookie-Editor's JSON export, or a Playwright cookie
list / storage state). They go on Railway as `SUB01_SESSION_TIKTOK` and `SUB01_SESSION_YOUTUBE`. This module:
- parses both formats into Playwright cookies (`parse_cookies`);
- keeps only the cookies of that site's own domains (`SITES[...]["domains"]`), so a TikTok session never reaches
  YouTube or any other host, and drops expired ones;
- says whether the session is still logged in: one of the site's login cookies must be present and unexpired;
- falls back to logged out for good (until a restart with fresh cookies) when the session expires or a login wall shows
  (`Session.expire`), with one log line.

Nothing here ever logs, prints or returns a cookie value: `Session` has no value in its repr or `status()`, and errors
name the problem only. The cookies live in browser memory only (`browse_service.py` adds them to the site's own context);
Chromium's environment never carries them (`browse.CHROMIUM_ENV` is an allowlist).
"""
import json
import os
import re
import time
import urllib.parse

# one entry per site: the env var, the registrable domains its cookies may belong to (and its context serves), and the
# cookie names that mean "logged in" (any one of them, unexpired)
SITES = {
    "tiktok": {"env": "SUB01_SESSION_TIKTOK", "domains": ("tiktok.com",),
               "login": ("sessionid", "sessionid_ss", "sid_tt", "sid_guard")},
    "youtube": {"env": "SUB01_SESSION_YOUTUBE", "domains": ("youtube.com",),
                "login": ("SID", "__Secure-1PSID", "__Secure-3PSID", "SAPISID", "LOGIN_INFO")},
}
MAX_RAW = 64_000                          # bytes: a real export is a few KB
MAX_COOKIES = 200
NAME_OK = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]{1,256}$")      # RFC 6265 token
VALUE_BAD = re.compile(r"[\x00-\x1f\x7f;]")
SAMESITE = {"strict": "Strict", "lax": "Lax", "none": "None", "no_restriction": "None"}
# YouTube's Restricted Mode (#17/#53) stays on when he is logged in: the session's own PREF never replaces it
RESTRICTED_PREF = {"name": "PREF", "value": "f2=8000000", "domain": ".youtube.com", "path": "/", "secure": True}
# elements that only show when the site thinks nobody is signed in (checked on the page: the session has expired)
SIGNED_OUT_SELECTORS = {
    "tiktok": ['[data-e2e="top-login-button"]', '[data-e2e="nav-login-button"]', '#header-login-button'],
    "youtube": ['ytd-masthead a[href*="ServiceLogin"]', 'ytd-masthead ytd-button-renderer a[aria-label="Sign in"]',
                'ytm-topbar-menu-button-renderer a[href*="ServiceLogin"]', '#masthead a[href*="accounts.google.com"]'],
}
# JS for page.evaluate(SIGNED_OUT_JS, selectors): which of them are visible
SIGNED_OUT_JS = """sels => sels.filter(s => [...document.querySelectorAll(s)].some(e => {
  const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
  return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; }))"""


class SessionError(ValueError):
    """A session secret that cannot be used. The message never contains the secret."""


def host_in(host, domains):
    """True if `host` is one of `domains` or a subdomain of one."""
    h = (host or "").lower().strip(".")
    return any(h == d or h.endswith("." + d) for d in domains)


def site_for_host(host):
    """The SITES key whose domains contain `host`, or None."""
    for site, cfg in SITES.items():
        if host_in(host, cfg["domains"]):
            return site
    return None


def site_for_url(url):
    try:
        return site_for_host(urllib.parse.urlsplit(url).hostname or "")
    except ValueError:
        return None


def _one(c, now):
    """A Cookie-Editor or Playwright cookie dict -> a Playwright cookie, or None if it is expired."""
    if not isinstance(c, dict):
        raise SessionError("a cookie is not an object")
    name, value, domain = c.get("name"), c.get("value"), c.get("domain")
    if not isinstance(name, str) or not NAME_OK.match(name):
        raise SessionError("a cookie has no valid name")
    if not isinstance(value, str) or VALUE_BAD.search(value) or len(value) > 4096:
        raise SessionError("a cookie has no valid value")
    if not isinstance(domain, str) or not re.match(r"^\.?[a-z0-9.-]+$", domain.lower()) or ".." in domain:
        raise SessionError("a cookie has no valid domain")
    path = c.get("path") or "/"
    if not isinstance(path, str) or not path.startswith("/"):
        raise SessionError("a cookie has no valid path")
    # expiry: Playwright `expires` (-1 = session), Cookie-Editor `expirationDate` (absent with `session: true`)
    exp = c.get("expires", c.get("expirationDate"))
    if c.get("session") is True or exp is None:
        exp = -1
    try:
        exp = float(exp)
    except (TypeError, ValueError):
        raise SessionError("a cookie has no valid expiry") from None
    if 0 <= exp <= now:
        return None
    domain = domain.lower()
    if c.get("hostOnly") is True:               # Cookie-Editor: host-only -> no leading dot
        domain = domain.lstrip(".")
    elif c.get("hostOnly") is False and not domain.startswith("."):
        domain = "." + domain
    secure = bool(c.get("secure", False))
    same = SAMESITE.get(str(c.get("sameSite") or "").lower(), "Lax")
    if same == "None" and not secure:           # Chromium refuses SameSite=None without Secure
        same = "Lax"
    out = {"name": name, "value": value, "domain": domain, "path": path, "expires": exp if exp > 0 else -1,
           "httpOnly": bool(c.get("httpOnly", False)), "secure": secure, "sameSite": same}
    return out


def parse_cookies(raw, now=None):
    """Cookies from an env value: a JSON list (Cookie-Editor export or Playwright cookies) or a Playwright storage
    state ({"cookies": [...]}). Expired cookies are dropped. Raises SessionError (without the content) if unusable."""
    now = time.time() if now is None else now
    if not isinstance(raw, str) or not raw.strip():
        raise SessionError("empty")
    if len(raw) > MAX_RAW:
        raise SessionError("too long")
    try:
        data = json.loads(raw)
    except ValueError:
        raise SessionError("not JSON") from None
    if isinstance(data, dict) and isinstance(data.get("cookies"), list):
        data = data["cookies"]
    if not isinstance(data, list):
        raise SessionError("not a cookie list")
    if len(data) > MAX_COOKIES:
        raise SessionError("too many cookies")
    return [c for c in (_one(c, now) for c in data) if c is not None]


def scope(cookies, domains):
    """Only the cookies whose domain is one of `domains` (or a subdomain); returns (kept, dropped_count)."""
    kept = [c for c in cookies if host_in(c["domain"], domains)]
    return kept, len(cookies) - len(kept)


class Session:
    """One site's logged-in session. `cookies()` is for the browser context only; nothing else shows a value."""

    def __init__(self, site, cookies=(), state="logged_out", reason="missing", dropped=0):
        self.site = site
        self._cookies = list(cookies)
        self.state = state                      # "logged_in" | "logged_out"
        self.reason = reason                    # why logged out: missing, invalid, expired, login_wall, ...
        self.dropped = dropped                  # cookies of other domains, not used
        self.since = time.time()

    def __repr__(self):
        return f"Session({self.site!r}, {self.state}, {len(self._cookies)} cookies)"

    __str__ = __repr__

    @property
    def logged_in(self):
        return self.state == "logged_in"

    def domains(self):
        return SITES[self.site]["domains"]

    def login_expires(self):
        """When the last login cookie expires (unix time), -1 for session cookies, None without one."""
        exps = [c["expires"] for c in self._cookies if c["name"] in SITES[self.site]["login"]]
        if not exps:
            return None
        return -1 if -1 in exps else max(exps)

    def check(self, now=None):
        """Logged out once no login cookie is left unexpired (checked before each use). Returns logged_in."""
        if self.logged_in:
            exp = self.login_expires()
            if exp is None or (exp != -1 and exp <= (time.time() if now is None else now)):
                self.expire("expired")
        return self.logged_in

    def cookies(self):
        """Copies of the cookies for `BrowserContext.add_cookies`, or [] when logged out. YouTube keeps Restricted
        Mode: the session's own PREF is replaced by the Restricted Mode one."""
        if not self.check():
            return []
        out = [dict(c) for c in self._cookies]
        if self.site == "youtube":
            out = [c for c in out if c["name"] != "PREF"] + [dict(RESTRICTED_PREF)]
        return out

    def expire(self, reason):
        """Fall back to logged out until the service restarts with fresh cookies. One log line, no cookie in it."""
        if self.logged_in:
            print(f"sessions: {self.site} logged out ({reason}); browsing it logged out", flush=True)
        self.state, self.reason, self._cookies, self.since = "logged_out", reason, [], time.time()

    def looks_signed_out(self, visible_selectors):
        """True if the page shows a sign-in button that only appears when logged out (SIGNED_OUT_JS's result)."""
        return bool(set(visible_selectors or ()) & set(SIGNED_OUT_SELECTORS.get(self.site, ())))

    def status(self):
        """For /api/browsing: state and reason only, never a cookie."""
        exp = self.login_expires() if self.logged_in else None
        return {"site": self.site, "state": self.state, "reason": None if self.logged_in else self.reason,
                "expires": None if exp in (None, -1) else int(exp)}


def load_session(site, environ=None, now=None):
    """The session of one site from its env var. Logged out (never an exception) when missing or unusable."""
    environ = os.environ if environ is None else environ
    cfg = SITES[site]
    raw = environ.get(cfg["env"], "")
    if not raw.strip():
        return Session(site, reason="missing")
    try:
        cookies = parse_cookies(raw, now)
    except SessionError as e:
        print(f"sessions: {cfg['env']} not usable ({e}); browsing {site} logged out", flush=True)
        return Session(site, reason="invalid")
    kept, dropped = scope(cookies, cfg["domains"])
    s = Session(site, kept, "logged_in", None, dropped)
    if dropped:
        print(f"sessions: {cfg['env']}: {dropped} cookies of other domains ignored", flush=True)
    if not s.check(now):
        s.reason = "expired"
        print(f"sessions: {cfg['env']} has no unexpired login cookie; browsing {site} logged out", flush=True)
    return s


def load_sessions(environ=None, now=None):
    return {site: load_session(site, environ, now) for site in SITES}


def secret_env_names():
    """Env vars that hold sessions (kept out of every child environment and every log)."""
    return tuple(cfg["env"] for cfg in SITES.values())
