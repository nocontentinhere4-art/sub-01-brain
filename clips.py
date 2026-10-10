"""Daily clips of SUB-01's life for the official social accounts (#59).

One to three vertical clips a day (1080x1920, 15-40 s, MP4/H.264, no audio), each with a fixed corner label
"AI · fictional character · simulated brain" and an end card with the site name:
- `day`    "A day in 30 s": the desk screen and eye frames sampled during the day (and, with CLIPS_ROOM=1, a few
           frames of the room page captured once a day in a headless Chromium child), captions from the day log
           ("10:16 orders food on the phone · 14:34 reads about ...").
- `dream`  "Last night's dream": the diary's dream frames, its title and text as captions.
- `choice` "His brain chose this move": a chess position with the 5 candidate moves and the brain-response bars, or a
           browsing choice with its options card.

How it runs (the brain tick must never feel it):
- The server only *samples* (every SAMPLE_S, cheap reads of what it already has: the life log, the reading log, the
  chess vote, the decision log, one desk screenshot every SHOT_S) into /data/clips/days/<date>/.
- Everything heavy runs in child processes at `nice 19`: the optional room capture (Chromium) and the render (Pillow frames +
  ffmpeg `-threads 1`). A render has CPU_S (120) CPU-seconds in total, enforced with RLIMIT_CPU on Pillow + ffmpeg
  together. One child at a time, only when it is quiet (Tokyo night, or at most LOW_VIEWERS websockets).
  `analysis/bench_clips.py` measures the tick with and without a render on one CPU.
- Kept KEEP_DAYS (14) days in /data/clips/, then deleted.

Wording: never "he thinks/feels"; every caption goes through `safe()` (no finance words or money talk (lexicon), no
feeling or mind claims, no links); the phone (its apps) is never photographed or captured. Posting is manual from /admin/clips (download + a
ready caption), or automatic with TIKTOK_POST_TOKEN / YOUTUBE_* set: at most once a day per platform, the AI label in
the caption and the platform's AI-content flag set. Unset: nothing is ever posted. Posts are counted in costs.py ($0).
"""
import asyncio
import hashlib
import hmac
import html
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from lexicon import money_talk
from sleep import TZ
from state_io import append_jsonl, load_json, read_jsonl, save_json

LABEL = "AI · fictional character · simulated brain"
SITE = os.environ.get("SUB01_SITE_NAME", "SUB-01")
SITE_URL = os.environ.get("SUB01_SITE_URL", "")            # shown on the end card when set (e.g. after launch)
HASHTAGS = "#AI #AIgenerated #digitaltwin #Tokyo #simulation"
W, H = 1080, 1920
FPS = 30
TYPES = ("day", "dream", "choice")
TITLES = {"day": "A day in 30 s", "dream": "Last night's dream", "choice": "His brain chose this move"}
KEEP_DAYS = 14
CPU_S = 120                     # CPU-seconds per clip (render + ffmpeg), RLIMIT_CPU
WALL_S = 900                    # a child that takes longer is killed
NICE = 19
SAMPLE_S = 60                   # real seconds between samples of the logs
SHOT_S = 20 * 60                # real seconds between desk screenshots kept for the day clip
LOW_VIEWERS = int(os.environ.get("SUB01_CLIPS_LOW_VIEWERS", "20"))
QUIET_HOURS = range(1, 7)       # Tokyo night: clips are made then whatever the viewer count
ROOM_CAPTURES = 1               # room captures per day, only with CLIPS_ROOM=1 (see capture_room: ~380 CPU-s each)
ROOM_GAP_S = 2 * 3600
ROOM_CPU_S = 600                # RLIMIT_CPU per process of the capture child (Chromium's GPU process is the big one)
ROOM_FRAMES = 6                 # each capture: 6 frames, at most 2 a second (SwiftShader: a few seconds a frame)
ROOM_WALL_S = 90                # and at most this long once the room has loaded
SAFE_ACTIVITIES = {"research", "window", "eat", "watch_video", "play_chess", "sleep", "park", "buy_bread",
                   "order_food", "get_delivery", "chat"}                # never "phone" (its apps are not for a clip)
NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-(day|dream|choice)\.mp4$")

FINANCE = re.compile(
    r"\$|€|¥|\b(price[sd]?|market|markets|chart|charts|coin|coins|token|tokens|crypto\w*|bitcoin|btc|eth|ethereum|"
    r"sol|solana|pump\w*|dump\w*|buy\w*|bought|sell\w*|sold|trade[sd]?|trading|invest\w*|profit\w*|money|usd|dollars?|"
    r"wallet\w*|to the moon|mooning|hodl|gains?|financ\w*|stocks?|shares?|ticker\w*|mcap|airdrop\w*|nft\w*|memecoin\w*|"
    r"advice|returns?|rich|portfolio)\b", re.I)
CLAIMS = re.compile(r"\b(thinks?|thought|feels?|felt|feeling\w*|wants?|wanted|loves?|hates?|happy|sad|conscious\w*|"
                    r"alive|sentien\w*|self.?aware|understands?|knows?|believes?|dreams? of)\b", re.I)
LINKS = re.compile(r"https?://|www\.|@\w", re.I)


def safe(s, limit=120):
    """A caption line, or "" when it carries finance words or money talk (the shared lexicon), a mind claim or a link."""
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    if not s or FINANCE.search(s) or money_talk(s, chat=True) or CLAIMS.search(s) or LINKS.search(s):
        return ""
    return s if len(s) <= limit else s[:limit - 1].rsplit(" ", 1)[0] + "…"


def event_caption(what):
    """life.py's log line -> what the clip says: the motive before ':' is dropped ("hungry: orders food" -> "orders
    food"), and so is the plan note; finance and feeling lines are left out."""
    s = str(what or "").split(";")[0]
    s = s.split(":", 1)[1] if ":" in s else s
    return safe(s.strip(), 60)


def tokyo_day(t):
    return datetime.fromtimestamp(t, TZ).date().isoformat()


def hhmm(t):
    return datetime.fromtimestamp(t, TZ).strftime("%H:%M")


def post_caption(kind, title=""):
    """The ready-made caption: <= 150 characters with the AI label, then hashtags. No finance wording."""
    lead = {"day": "A simulated day in his Tokyo room, in 30 seconds.",
            "dream": "Last night's dream, from his diary",
            "choice": "His brain model picks a move among 5 candidates from a simple move scorer."}[kind]
    if kind == "dream":
        t = safe(title, 60)
        lead = f"{lead}: {t}." if t else lead + "."
    text = f"{lead} {LABEL}"
    if len(text) > 150:
        text = f"{lead[:150 - len(LABEL) - 2].rstrip()}… {LABEL}"
    return text, HASHTAGS


# --- rendering (child process) -------------------------------------------------------------------------------------
FONT_PATHS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",
              "/Library/Fonts/Arial Unicode.ttf")
BOLD_PATHS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf")
BG, FG, ORANGE, DIM = (4, 4, 6), (236, 236, 242), (255, 106, 0), (120, 124, 140)


def font(size, bold=False):
    from PIL import ImageFont
    for p in (BOLD_PATHS if bold else ()) + FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def wrap(draw, text, f, width):
    lines, cur = [], ""
    for word in str(text).split():
        nxt = f"{cur} {word}".strip()
        if draw.textlength(nxt, font=f) <= width or not cur:
            cur = nxt
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def fit_photo(path):
    """A landscape or square picture on the vertical frame: a blurred cover behind, the picture whole in the middle."""
    from PIL import Image, ImageFilter
    canvas = Image.new("RGB", (W, H), BG)
    try:
        im = Image.open(path).convert("RGB")
    except (OSError, ValueError):
        return canvas
    small = im.copy()
    small.thumbnail((108, 192))
    s = max(W / small.width, H / small.height)
    cover = small.resize((max(1, int(small.width * s / 10)), max(1, int(small.height * s / 10))))
    cover = cover.filter(ImageFilter.GaussianBlur(3)).resize((W, H))
    canvas.paste(Image.eval(cover, lambda v: v * 2 // 5), (0, 0))
    s = min(W / im.width, H / im.height) if im.height > im.width else W / im.width
    im = im.resize((int(im.width * s), int(im.height * s)))
    canvas.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
    return canvas


def chrome(img, title, caption=None):
    """The parts every frame has: the corner label (fixed, top left, inside the platforms' safe area), the title,
    and an optional caption box in the lower third."""
    from PIL import ImageDraw
    d = ImageDraw.Draw(img, "RGBA")
    f = font(30, True)
    tw = d.textlength(LABEL, font=f)
    d.rectangle((48, 120, 48 + tw + 32, 172), fill=(0, 0, 0, 190))
    d.text((64, 128), LABEL, font=f, fill=FG)
    ft = font(46, True)
    d.rectangle((48, 192, 48 + d.textlength(SITE, font=ft) + 28, 252), fill=ORANGE)
    d.text((62, 196), SITE, font=ft, fill=(10, 10, 10))
    d.text((48, 272), title, font=font(52, True), fill=FG, stroke_width=3, stroke_fill=(0, 0, 0))
    if caption:
        fc = font(54, True)
        lines = wrap(d, caption, fc, W - 160)[:4]
        top = 1330 - 34 * len(lines)
        d.rectangle((48, top - 28, W - 48, top + 72 * len(lines) + 16), fill=(0, 0, 0, 170))
        for i, ln in enumerate(lines):
            d.text((80, top + 72 * i), ln, font=fc, fill=FG)
    return img


def end_card(kind):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f = font(150, True)
    tw = d.textlength(SITE, font=f)
    d.rectangle(((W - tw) / 2 - 40, 640, (W + tw) / 2 + 40, 840), fill=ORANGE)
    d.text(((W - tw) / 2, 652), SITE, font=f, fill=(10, 10, 10))
    y = 900
    for ln, size, col in ((SITE_URL, 44, FG), ("A brain model built from public MRI data,", 40, FG),
                          ("living as a fictional character in a Tokyo room.", 40, FG), (LABEL, 40, ORANGE),
                          ("Not a real person. Not advice of any kind.", 34, DIM)):
        if not ln:
            continue
        fl = font(size, size > 42)
        d.text(((W - d.textlength(ln, font=fl)) / 2, y), ln, font=fl, fill=col)
        y += size + 34
    return chrome(img, TITLES[kind])


def bars(d, x, y, w, rows, title):
    """Options with brain-response bars (the vote share `p`), the chosen one in orange."""
    d.text((x, y), title, font=font(36, True), fill=DIM)
    y += 60
    f = font(40, True)
    top = max([r.get("p", 0) for r in rows] + [1e-6])
    for r in rows[:6]:
        col = ORANGE if r.get("chosen") else FG
        d.text((x, y), (r.get("label") or "?")[:34], font=f, fill=col)
        d.text((x + w - 120, y), f"{100 * r.get('p', 0):.0f}%", font=f, fill=col)
        d.rectangle((x, y + 52, x + w, y + 64), fill=(40, 40, 52))
        d.rectangle((x, y + 52, x + max(6, int(w * r.get("p", 0) / top)), y + 64), fill=col)
        y += 88
    return y


def board_frame(slide, title):
    """The chess position (Unicode pieces) with the 5 candidates and the card's wording."""
    from PIL import Image, ImageDraw
    import chess
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    try:
        b = chess.Board(slide.get("fen") or chess.STARTING_FEN)
    except ValueError:
        b = chess.Board()
    sq, x0, y0 = 100, (W - 100 * 8) // 2, 370
    flip = slide.get("color") == "black"
    pf = font(84)
    for r in range(8):
        for c in range(8):
            file_, rank = (7 - c, r) if flip else (c, 7 - r)
            light = (file_ + rank) % 2 == 1
            d.rectangle((x0 + c * sq, y0 + r * sq, x0 + (c + 1) * sq, y0 + (r + 1) * sq),
                        fill=(214, 200, 170) if light else (120, 96, 72))
            p = b.piece_at(chess.square(file_, rank))
            if p:
                g = p.unicode_symbol(invert_color=False) if p.color == chess.BLACK else p.unicode_symbol()
                cx, cy = x0 + c * sq + sq / 2, y0 + r * sq + sq / 2
                d.text((cx, cy), g, font=pf, anchor="mm", fill=(250, 250, 250) if p.color else (20, 20, 20),
                       stroke_width=2, stroke_fill=(20, 20, 20) if p.color else (250, 250, 250))
    y = bars(d, 80, y0 + 8 * sq + 50, W - 160, slide.get("options", []), "brain response per candidate move")
    for ln in wrap(d, slide.get("card", ""), font(34), W - 160)[:3]:
        d.text((80, y + 10), ln, font=font(34), fill=DIM)
        y += 46
    return chrome(img, title)


def options_frame(slide, title):
    """A browsing choice: the page, the options the AI listed and the brain-response bars."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    y = 420
    d.text((80, y), "on the screen:", font=font(36, True), fill=DIM)
    for ln in wrap(d, slide.get("page", ""), font(50, True), W - 160)[:3]:
        y += 66
        d.text((80, y), ln, font=font(50, True), fill=FG)
    y = bars(d, 80, y + 110, W - 160, slide.get("options", []), "brain response per option")
    for ln in wrap(d, "An AI reads the page and lists options; his brain model picks. It does not understand what "
                      "it reads.", font(34), W - 160):
        d.text((80, y + 10), ln, font=font(34), fill=DIM)
        y += 46
    return chrome(img, title)


def render_frame(slide, kind):
    t = TITLES[kind]
    if slide["kind"] == "end":
        return end_card(kind)
    if slide["kind"] == "board":
        return board_frame(slide, t)
    if slide["kind"] == "options":
        return options_frame(slide, t)
    return chrome(fit_photo(slide.get("img", "")), t, slide.get("caption"))


def _limit(seconds):
    def pre():                                             # nice is inherited from the render child
        resource.setrlimit(resource.RLIMIT_CPU, (max(1, int(seconds)), max(1, int(seconds)) + 1))
    return pre


def cpu_used():
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


def render(spec, ffmpeg="ffmpeg", cpu_base=None):
    """spec {kind, out, slides: [{kind: photo|board|options|end, img, caption, seconds, ...}]} -> the MP4 at `out`.
    Frames are rendered once each and held for their `seconds` by ffmpeg's concat demuxer (the encoder sees still
    frames, cheap at -preset veryfast). The CPU left in this process's budget is handed to ffmpeg as its own limit."""
    base = cpu_used() if cpu_base is None else cpu_base      # the child passes 0: RLIMIT_CPU counts from its start
    kind, out = spec["kind"], Path(spec["out"])
    tmp = Path(tempfile.mkdtemp(prefix="clip-", dir=out.parent))
    try:
        lines = []
        for i, s in enumerate(spec["slides"]):
            p = tmp / f"{i:04d}.jpg"
            render_frame(s, kind).save(p, quality=90)
            lines += [f"file '{p.name}'", f"duration {float(s.get('seconds', 2.0)):.3f}"]
        lines.append(f"file '{p.name}'")                       # the concat demuxer needs the last file twice
        (tmp / "list.txt").write_text("\n".join(lines) + "\n")
        left = int(spec.get("cpu_s", CPU_S) - (cpu_used() - base))
        if left < 5:
            raise RuntimeError("CPU budget used up before encoding")
        part = out.with_suffix(".part.mp4")
        cmd = [ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
               "-vf", f"scale={W}:{H},fps={FPS},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "23", "-threads", "1", "-an", "-movflags", "+faststart", str(part.resolve())]
        subprocess.run(cmd, cwd=tmp, check=True, timeout=WALL_S, preexec_fn=_limit(left))
        os.replace(part, out)
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def child_env():
    """Children get no secrets: only what they need to run."""
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "PLAYWRIGHT_BROWSERS_PATH", "PYTHONPATH", "TZ", "SUB01_TZ",
            "SUB01_SITE_NAME", "SUB01_SITE_URL", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")
    return {k: os.environ[k] for k in keep if k in os.environ}


# --- room capture (child process) ----------------------------------------------------------------------------------
async def capture_room(url, out_dir, frames=ROOM_FRAMES, cookie=None, executable=None, proxy=None):
    """`frames` frames of the room page, at most 2 a second (vertical viewport, the 3D view only, without the cards below it).
    CDP screenshots, not the screencast: in a headless SwiftShader Chromium the screencast delivered 3 frames in 5 s,
    at irregular times (and Playwright's screenshot timed out waiting for animation frames).
    Cost, measured in the sandbox (4 cores, software WebGL): ~380 CPU-seconds and ~105 s for 6 frames of the loaded
    room, almost all in Chromium's GPU process. That is why it is off unless CLIPS_ROOM=1, once a day at most, and
    the day clip is built from the desk screenshots and eye frames otherwise. Saves JPEGs in out_dir; returns how many."""
    import base64
    from playwright.async_api import async_playwright
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path=executable, args=["--mute-audio"],
                                     proxy={"server": proxy, "bypass": "127.0.0.1,localhost"} if proxy else None)
        try:
            ctx = await b.new_context(viewport={"width": 540, "height": 960}, device_scale_factor=1,
                                      ignore_https_errors=bool(proxy))   # dev only: a TLS-intercepting proxy
            if cookie:
                await ctx.add_cookies([{"name": "sub01", "value": cookie, "url": url}])
            page = await ctx.new_page()
            for attempt in (1, 2):                                  # one reload if a library or model did not load
                await page.goto(url, wait_until="load", timeout=60000)
                try:
                    await page.wait_for_selector("#boot", state="detached", timeout=90000)   # the room's models are in
                    break
                except Exception:
                    if attempt == 2:
                        raise
            await page.wait_for_timeout(3000)                       # the first live state
            box = await page.evaluate("(() => { const c = [...document.querySelectorAll('canvas')].sort((a, b) => "
                                      "b.width * b.height - a.width * a.height)[0]; if (!c) return null; "
                                      "const r = c.getBoundingClientRect(); return {x: r.x, y: r.y, "
                                      "width: Math.min(r.width, innerWidth), height: Math.min(r.height, innerHeight)}; })()")
            stamp = time.strftime("%H%M%S")
            cdp = await ctx.new_cdp_session(page)
            shot = {"format": "jpeg", "quality": 85}
            if box:
                shot["clip"] = dict(box, scale=1)
            t_end = time.monotonic() + ROOM_WALL_S
            while n < frames and time.monotonic() < t_end:
                t0 = time.monotonic()
                data = (await cdp.send("Page.captureScreenshot", shot))["data"]
                (out_dir / f"room-{stamp}-{n:03d}.jpg").write_bytes(base64.b64decode(data))
                n += 1
                await asyncio.sleep(max(0.0, 0.5 - (time.monotonic() - t0)))
        finally:
            await b.close()
    return n


# --- the scheduler (in the server) ---------------------------------------------------------------------------------
class ClipMaker:
    def __init__(self, data_dir, clock=time.time, python=sys.executable, ffmpeg=None):
        self.dir = Path(data_dir) / "clips"
        self.days = self.dir / "days"
        self.days.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.python = python
        self.ffmpeg = ffmpeg or shutil.which("ffmpeg")
        self.state_path = self.dir / "state.json"
        self.state = load_json(self.state_path) or {}
        self.seen = set()
        self.last_shot = 0.0
        self.busy = False
        self.ledger = None                     # costs.Ledger: posts are counted there ($0)
        self.log = []                          # recent lines for the admin page

    def note(self, s):
        print("clips:", s, flush=True)
        self.log = (self.log + [f"{hhmm(self.clock())} {s}"])[-20:]

    def day_dir(self, day):
        d = self.days / day
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self):
        save_json(self.state_path, self.state)

    # --- sampling: cheap, on the event loop ------------------------------------------------------------------------
    def remember(self, day, row):
        key = json.dumps(row, sort_keys=True)[:400]
        if key in self.seen:
            return False
        self.seen.add(key)
        if len(self.seen) > 5000:
            self.seen = set(list(self.seen)[-2000:])
        append_jsonl(self.day_dir(day) / "moments.jsonl", row)
        return True

    def sample(self, live):
        """What happened since the last sample, from what the server already holds."""
        for e in list(getattr(live.life, "log", []))[-30:]:
            c = event_caption(e.get("what"))
            if c and e.get("t"):
                self.remember(tokyo_day(e["t"]), {"kind": "event", "t": round(e["t"]), "text": c})
        reader = getattr(live, "reader", None)
        for a in list(getattr(reader, "log", []) or [])[-10:]:
            title = safe(a.get("title"), 50)
            if title and a.get("t"):
                self.remember(tokyo_day(a["t"]), {"kind": "event", "t": round(a["t"]), "text": f"reads about {title}"})
        now = live.clock.now() if hasattr(live, "clock") else self.clock()
        g = getattr(live, "chess", None)
        if g is not None and getattr(g, "votes", None):
            v = g.votes[-1]
            pub = g.public()
            try:                                               # the position he chose in: before his last move
                b = g.board.copy()
                for _ in range(2 if b.turn == g.color else 1):
                    b.pop()
                pub["fen"] = b.fen()
            except (AttributeError, IndexError):
                pass
            opts = [{"label": safe(o.get("label"), 30) or "?", "p": o.get("p", 0), "chosen": o.get("chosen")}
                    for o in v.get("options", [])]
            self.remember(tokyo_day(now), {"kind": "chess", "move": v.get("move"), "fen": pub.get("fen"),
                                           "color": pub.get("color"), "options": opts, "plies": pub.get("plies")})
        for dec in list(getattr(live, "decision_log", []))[-5:]:
            page = safe(dec.get("page"), 90)
            opts = [{"label": safe(o.get("label"), 34), "p": o.get("p", 0), "chosen": o.get("chosen")}
                    for o in dec.get("options", [])]
            if page and opts and all(o["label"] for o in opts):        # one unsafe label: the whole card is left out
                self.remember(tokyo_day(now), {"kind": "choice", "t": dec.get("t"), "page": page, "options": opts})

    async def shoot(self, live):
        """One desk screenshot every SHOT_S (the picture the screens already have), or the newest eye frame."""
        if self.clock() - self.last_shot < SHOT_S or getattr(live.life, "activity", "") not in SAFE_ACTIVITIES:
            return
        self.last_shot = self.clock()
        now = live.clock.now()
        dest = self.day_dir(tokyo_day(now)) / f"shot-{hhmm(now).replace(':', '')}.jpg"
        shot = None
        if getattr(live, "browser", None) and getattr(live.life, "activity", "") in ("research", "watch_video"):
            try:
                shot = await asyncio.wait_for(live.browser.shot("desk"), 5)
            except Exception:
                shot = None
        if shot:
            dest.write_bytes(shot)
            return
        eye = getattr(live, "eye", None)
        if eye is not None:
            rows = read_jsonl(eye.log, last=1)
            if rows and rows[-1].get("img"):
                src = Path(eye.out) / Path(rows[-1]["img"]).name
                if src.exists():
                    shutil.copyfile(src, dest)

    # --- when -------------------------------------------------------------------------------------------------------
    def quiet(self, viewers):
        return datetime.fromtimestamp(self.clock(), TZ).hour in QUIET_HOURS or viewers <= LOW_VIEWERS

    def due(self, live):
        """(kind, date) of the next clip to make, or None. Day and choice clips are made for yesterday (the day is
        over); the dream clip once the night's diary entry is closed."""
        today = datetime.fromtimestamp(self.clock(), TZ).date()
        made = self.state.setdefault("made", {})
        yday = (today - timedelta(days=1)).isoformat()
        for kind in ("day", "choice"):
            if f"{yday}-{kind}" not in made and (self.days / yday / "moments.jsonl").exists():
                return kind, yday
        diary = getattr(live, "diary", None)
        if diary is not None:
            for n in diary.index(2):
                if n.get("closed") and n.get("frames") and f"{n['date']}-dream" not in made:
                    return "dream", n["date"]
        return None

    # --- specs --------------------------------------------------------------------------------------------------------
    def spec(self, kind, day, live=None):
        d = self.days / day
        rows = read_jsonl(d / "moments.jsonl") if (d / "moments.jsonl").exists() else []
        slides = getattr(self, f"slides_{kind}")(day, d, rows, live)
        if not slides:
            return None
        slides = fit_length(slides) + [{"kind": "end", "seconds": 3.0}]
        return {"kind": kind, "day": day, "out": str(self.dir / f"{day}-{kind}.mp4"), "slides": slides,
                "cpu_s": CPU_S}

    def slides_day(self, day, d, rows, live):
        events = sorted({r["t"]: r for r in rows if r["kind"] == "event"}.values(), key=lambda r: r["t"])
        if not events:
            return []
        if len(events) > 10:                                   # spread over the day
            events = [events[round(i * (len(events) - 1) / 9)] for i in range(10)]
        pics = sorted(d.glob("shot-*.jpg"))
        room = sorted(d.glob("room-*.jpg"))
        out = [{"kind": "photo", "img": str(p), "seconds": 0.5} for p in room[:12]]
        for i, e in enumerate(events):
            near = [p for p in pics if p.stem[5:] <= hhmm(e["t"]).replace(":", "")]
            img = near[-1] if near else (room[i % len(room)] if room else (pics[0] if pics else ""))
            out.append({"kind": "photo", "img": str(img), "caption": f"{hhmm(e['t'])} {e['text']}", "seconds": 2.6})
        out += [{"kind": "photo", "img": str(p), "seconds": 0.5} for p in room[12:24]]
        return out

    def slides_dream(self, day, d, rows, live):
        diary = getattr(live, "diary", None)
        n = diary.load(day) if diary is not None else None
        if not n or not n.get("frames"):
            return []
        title = safe(n.get("title"), 80)
        sentences = [x for x in (safe(t, 140) for t in re.split(r"(?<=[.!?])\s+", str(n.get("text") or ""))) if x]
        frames = n["frames"][-10:]
        out = []
        for i, f in enumerate(frames):
            img = diary.img / day / Path(f["img"]).name
            cap = title if i == 0 and title else (sentences[(i - 1) % len(sentences)] if sentences else "")
            out.append({"kind": "photo", "img": str(img), "caption": cap, "seconds": 3.2 if cap else 2.0})
        return out

    def slides_choice(self, day, d, rows, live):
        from chess_game import CARD
        games = [r for r in rows if r["kind"] == "chess" and r.get("options")]
        if games:
            pick = games[len(games) // 2]
            first = dict(pick, kind="board", card=CARD, options=[dict(o, chosen=False) for o in pick["options"]])
            return [dict(first, seconds=4.0), dict(pick, kind="board", card=CARD, seconds=8.0)]
        ch = [r for r in rows if r["kind"] == "choice"]
        if ch:
            pick = max(ch, key=lambda r: len(r["options"]))
            return [dict(pick, kind="options", options=[dict(o, chosen=False) for o in pick["options"]], seconds=5.0),
                    dict(pick, kind="options", seconds=9.0)]
        return []

    # --- children --------------------------------------------------------------------------------------------------------
    async def run_child(self, args, stdin=b""):
        """`python clips.py <args>` at nice 19, no secrets in its env; killed after WALL_S."""
        proc = await asyncio.create_subprocess_exec(
            self.python, str(Path(__file__).resolve()), *args, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=child_env(),
            preexec_fn=lambda: os.nice(NICE))
        try:
            out, _ = await asyncio.wait_for(proc.communicate(stdin), WALL_S)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return -9, "timeout"
        return proc.returncode, out.decode(errors="replace")[-400:]

    async def make(self, kind, day, live=None):
        spec = self.spec(kind, day, live)
        made = self.state.setdefault("made", {})
        if spec is None:
            made[f"{day}-{kind}"] = {"skipped": "nothing to show", "at": round(self.clock())}
            self.save()
            return None
        meta = {"kind": kind, "day": day, "title": TITLES[kind], "file": Path(spec["out"]).name}
        if kind == "dream" and getattr(live, "diary", None):
            meta["dream_title"] = safe((live.diary.load(day) or {}).get("title"), 80)
        meta["caption"], meta["hashtags"] = post_caption(kind, meta.get("dream_title", ""))
        meta["seconds"] = round(sum(s["seconds"] for s in spec["slides"]), 1)
        t0 = time.monotonic()
        code, out = await self.run_child(["render"], json.dumps(dict(spec, ffmpeg=self.ffmpeg)).encode())
        if code != 0 or not Path(spec["out"]).exists():
            made[f"{day}-{kind}"] = {"failed": out[-200:], "at": round(self.clock())}
            self.save()
            self.note(f"{day} {kind} failed ({code}): {out[-160:]}")
            return None
        meta["render_s"] = round(time.monotonic() - t0, 1)
        meta["cpu_s"] = _json_tail(out).get("cpu_s")
        meta["made_at"] = round(self.clock())
        save_json(self.dir / f"{day}-{kind}.json", meta, ensure_ascii=False)
        made[f"{day}-{kind}"] = {"ok": True, "at": round(self.clock())}
        self.save()
        self.note(f"made {meta['file']} ({meta['seconds']} s, {meta['render_s']} s wall, cpu {meta['cpu_s']} s)")
        return meta

    async def capture(self, live, port):
        """A short room screencast for the day clip: quiet, a safe activity, at most ROOM_CAPTURES a day."""
        now = live.clock.now()
        day = tokyo_day(now)
        caps = self.state.setdefault("room", {})
        n, last = caps.get(day, [0, 0])
        if n >= ROOM_CAPTURES or self.clock() - last < ROOM_GAP_S or getattr(live.life, "activity", "") in (
                "phone", "sleep"):
            return
        caps.clear()
        caps[day] = [n + 1, self.clock()]
        self.save()
        cookie = None
        if os.environ.get("SITE_PASSWORD"):                    # the gate's cookie (the same hash as the login sets)
            cookie = hashlib.sha256(("sub01:" + os.environ["SITE_PASSWORD"]).encode()).hexdigest()
        req = {"url": f"http://127.0.0.1:{port}/", "out": str(self.day_dir(day)), "cookie": cookie}
        code, out = await self.run_child(["capture"], json.dumps(req).encode())
        self.note(f"room capture {day}: {'ok' if code == 0 else 'failed'} {out[-120:].strip()}")

    # --- retention + listing ------------------------------------------------------------------------------------------
    def cleanup(self):
        """Clips and day samples are kept KEEP_DAYS Tokyo days (today included), then deleted."""
        cut = (datetime.fromtimestamp(self.clock(), TZ).date() - timedelta(days=KEEP_DAYS - 1)).isoformat()  # today + 13
        gone = 0
        for p in self.dir.glob("*-*-*-*.*"):
            if p.name[:10] < cut:
                p.unlink(missing_ok=True)
                gone += 1
        for p in self.days.iterdir() if self.days.exists() else ():
            if p.is_dir() and p.name < cut:
                shutil.rmtree(p, ignore_errors=True)
                gone += 1
        made = self.state.get("made", {})
        for k in [k for k in made if k[:10] < cut]:
            made.pop(k)
        return gone

    def clips(self):
        out = []
        for p in sorted(self.dir.glob("*.mp4"), reverse=True):
            m = NAME.match(p.name)
            if not m:
                continue
            meta = load_json(p.with_suffix(".json")) or {}
            cap, tags = post_caption(m.group(2), meta.get("dream_title", ""))
            out.append({"file": p.name, "day": m.group(1), "kind": m.group(2), "title": TITLES[m.group(2)],
                        "mb": round(p.stat().st_size / 1e6, 1), "caption": meta.get("caption", cap),
                        "hashtags": meta.get("hashtags", tags), "seconds": meta.get("seconds"),
                        "posted": self.state.get("posted", {}).get(p.name, {})})
        return out

    # --- auto-post ----------------------------------------------------------------------------------------------------
    async def autopost(self, http=None):
        """At most one post per platform per Tokyo day, of the newest clip not posted there yet. Nothing without
        tokens."""
        posters = enabled_posters()
        if not posters:
            return []
        today = tokyo_day(self.clock())
        done = []
        for name, poster in posters.items():
            if self.state.setdefault("last_post", {}).get(name) == today:
                continue
            todo = [c for c in self.clips() if name not in c["posted"]]
            if not todo:
                continue
            c = todo[0]
            text = f"{c['caption']} {c['hashtags']}"
            if LABEL not in text or FINANCE.search(c["caption"]):
                continue
            self.state["last_post"][name] = today                # once a day, also when it fails
            self.save()
            try:
                res = await poster(self.dir / c["file"], c["title"], text, http)
                ok = True
            except Exception as e:
                res, ok = {"error": repr(e)[:160]}, False
            self.state.setdefault("posted", {}).setdefault(c["file"], {})[name] = {"ok": ok, "at": round(self.clock()),
                                                                                  **res}
            self.save()
            if self.ledger is not None:
                self.ledger.record("clips", name, 1 if ok else 0, 0.0, f"{c['file']} {'posted' if ok else 'failed'}")
            self.note(f"{name}: {c['file']} {'posted' if ok else 'failed'} {res}")
            done.append((name, ok))
        return done

    # --- the loop -----------------------------------------------------------------------------------------------------
    async def run(self, live, port):
        if not self.ffmpeg:
            self.note("ffmpeg not found: sampling only, no clips")
        n = 0
        while True:
            await asyncio.sleep(SAMPLE_S if n else 5)
            n += 1
            self.sample(live)
            await self.shoot(live)
            viewers = len(getattr(live, "sockets", ()))
            if self.busy or not self.quiet(viewers):
                continue
            self.busy = True
            try:
                if n % 60 == 1:
                    self.cleanup()
                due = self.due(live) if self.ffmpeg else None
                if due:
                    await self.make(*due, live=live)
                else:
                    if os.environ.get("CLIPS_ROOM", "0") == "1":
                        await self.capture(live, port)
                    await self.autopost()
            finally:
                self.busy = False


def fit_length(slides, lo=12.0, hi=37.0):
    """15-40 s with the 3 s end card: slides are stretched or squeezed to fit."""
    total = sum(s["seconds"] for s in slides)
    k = lo / total if total < lo else hi / total if total > hi else 1.0
    return [dict(s, seconds=round(s["seconds"] * k, 3)) for s in slides]


def _json_tail(out):
    for ln in reversed(out.strip().splitlines()):
        try:
            return json.loads(ln)
        except ValueError:
            continue
    return {}


# --- auto-post (official APIs; off unless the tokens are set) -------------------------------------------------------
TIKTOK_API = os.environ.get("TIKTOK_API_BASE", "https://open.tiktokapis.com")
YOUTUBE_TOKEN_URL = os.environ.get("YOUTUBE_TOKEN_URL", "https://oauth2.googleapis.com/token")
YOUTUBE_UPLOAD = os.environ.get("YOUTUBE_UPLOAD_URL", "https://www.googleapis.com/upload/youtube/v3/videos")


def enabled_posters():
    out = {}
    if os.environ.get("TIKTOK_POST_TOKEN"):
        out["tiktok"] = post_tiktok
    if all(os.environ.get(k) for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")):
        out["youtube"] = post_youtube
    return out


async def _session(http):
    import aiohttp
    return (http, False) if http is not None else (aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)), True)


async def post_tiktok(path, title, text, http=None):
    """TikTok Content Posting API: TIKTOK_POST_MODE=draft (default, the inbox: the owner finishes it in the app) or
    direct (needs the video.publish scope; privacy TIKTOK_PRIVACY, default SELF_ONLY for unaudited apps). One chunk
    (clips are a few MB). Direct posts set is_aigc (TikTok's AI-generated content label)."""
    data = Path(path).read_bytes()
    direct = os.environ.get("TIKTOK_POST_MODE", "draft") == "direct"
    src = {"source": "FILE_UPLOAD", "video_size": len(data), "chunk_size": len(data), "total_chunk_count": 1}
    body = {"source_info": src}
    if direct:
        body["post_info"] = {"title": text[:2200], "privacy_level": os.environ.get("TIKTOK_PRIVACY", "SELF_ONLY"),
                             "is_aigc": True, "disable_comment": False}
    url = f"{TIKTOK_API}/v2/post/publish/{'video' if direct else 'inbox/video'}/init/"
    hdr = {"Authorization": f"Bearer {os.environ['TIKTOK_POST_TOKEN']}", "Content-Type": "application/json; charset=UTF-8"}
    http, own = await _session(http)
    try:
        async with http.post(url, json=body, headers=hdr) as r:
            j = await r.json(content_type=None)
            if r.status != 200 or (j.get("error") or {}).get("code", "ok") != "ok":
                raise RuntimeError(f"tiktok init {r.status}: {(j.get('error') or {}).get('code')}")
        up, pid = j["data"]["upload_url"], j["data"]["publish_id"]
        async with http.put(up, data=data, headers={"Content-Type": "video/mp4", "Content-Length": str(len(data)),
                                                    "Content-Range": f"bytes 0-{len(data) - 1}/{len(data)}"}) as r:
            if r.status not in (200, 201):
                raise RuntimeError(f"tiktok upload {r.status}")
        return {"publish_id": pid, "mode": "direct" if direct else "draft"}
    finally:
        if own:
            await http.close()


async def post_youtube(path, title, text, http=None):
    """YouTube Data API v3 resumable upload of a Short (vertical, < 60 s). Privacy YOUTUBE_PRIVACY (default private:
    the owner publishes it), containsSyntheticMedia set (YouTube's altered or synthetic content disclosure)."""
    data = Path(path).read_bytes()
    http, own = await _session(http)
    try:
        async with http.post(YOUTUBE_TOKEN_URL, data={
                "client_id": os.environ["YOUTUBE_CLIENT_ID"], "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
                "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"], "grant_type": "refresh_token"}) as r:
            if r.status != 200:
                raise RuntimeError(f"youtube token {r.status}")
            token = (await r.json(content_type=None))["access_token"]
        meta = {"snippet": {"title": f"{title} #Shorts · {SITE} (AI)"[:100], "description": text,
                            "tags": ["AI", "digital twin", "Tokyo", "simulation"], "categoryId": "28"},
                "status": {"privacyStatus": os.environ.get("YOUTUBE_PRIVACY", "private"),
                           "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}}
        hdr = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
               "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(len(data))}
        async with http.post(f"{YOUTUBE_UPLOAD}?uploadType=resumable&part=snippet,status", json=meta,
                             headers=hdr) as r:
            if r.status != 200 or "Location" not in r.headers:
                raise RuntimeError(f"youtube init {r.status}")
            loc = r.headers["Location"]
        async with http.put(loc, data=data, headers={"Authorization": f"Bearer {token}",
                                                     "Content-Type": "video/mp4"}) as r:
            if r.status not in (200, 201):
                raise RuntimeError(f"youtube upload {r.status}")
            vid = (await r.json(content_type=None)).get("id")
        return {"video_id": vid}
    finally:
        if own:
            await http.close()


# --- /admin/clips -------------------------------------------------------------------------------------------------
COOKIE = "sub01_admin"


def admin_cookie(token):
    return hashlib.sha256(("sub01-admin:" + token).encode()).hexdigest()


def cookie_ok(request):
    token = os.environ.get("SUB01_ADMIN_TOKEN", "")
    return bool(token) and hmac.compare_digest(request.cookies.get(COOKIE, ""), admin_cookie(token))


PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>SUB-01 clips</title><style>body{{margin:0;padding:16px;background:#040406;color:#ececf2;
font-family:ui-monospace,Menlo,monospace}}h1{{font-size:20px}}.c{{border:1px solid #2a2a36;padding:12px;margin:12px 0;
max-width:720px}}video{{width:180px;float:right;margin-left:12px;background:#000}}textarea{{width:100%;height:84px;
background:#0c0c12;color:#ececf2;border:1px solid #2a2a36;font:inherit}}a,button{{background:#ececf2;color:#0a0a0a;
border:0;padding:8px 12px;font:inherit;text-decoration:none;display:inline-block;margin:6px 6px 0 0;cursor:pointer}}
small{{color:#8a8ea0}}.o{{background:#ff6a00;color:#0a0a0a;padding:2px 8px}}</style>
<h1><span class=o>SUB-01</span> clips</h1><small>Post them by hand on the official accounts, or let the APIs post
(TikTok: {tiktok}; YouTube: {youtube}). Every clip carries "{label}". Kept {keep} days.</small>{items}
<pre><small>{log}</small></pre>
<script>document.querySelectorAll('button[data-copy]').forEach(b=>b.onclick=()=>{{const t=document.getElementById(
b.dataset.copy);t.select();navigator.clipboard?navigator.clipboard.writeText(t.value):document.execCommand('copy');
b.textContent='copied'}})</script>"""
ITEM = """<div class=c><video src="/admin/clips/file/{file}" preload=none controls muted playsinline></video>
<b>{day} · {title}</b><br><small>{seconds} s · {mb} MB{posted}</small><br>
<textarea id=t{i} readonly>{caption} {hashtags}</textarea><br>
<a href="/admin/clips/file/{file}" download>download</a><button data-copy=t{i}>copy caption</button>
<small>{n} characters + hashtags</small><div style=clear:both></div></div>"""
LOGIN = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>SUB-01 clips</title><body style="margin:0;padding:16px;background:#040406;color:#ececf2;
font-family:ui-monospace,Menlo,monospace"><form method=post action=/admin/clips/login style="display:grid;gap:12px;
max-width:360px"><b>admin token</b><input name=token type=password autofocus style="background:#0c0c12;color:#ececf2;
border:1px solid #2a2a36;padding:10px;font:inherit"><button>open</button></form></body>"""


def add_routes(app, maker, is_admin):
    """GET /admin/clips (the page), GET /admin/clips/file/<name> (download), POST /admin/clips/login (the
    SUB01_ADMIN_TOKEN as a form field -> an HttpOnly cookie). Access: is_admin(request) (the token header, or the
    site password's cookie), or the admin cookie. Nothing without one of them."""
    from aiohttp import web
    no_store = {"Cache-Control": "no-store"}

    def ok(request):
        return is_admin(request) or cookie_ok(request)

    async def page(request):
        if not ok(request):
            return web.Response(text=LOGIN, content_type="text/html", status=401, headers=no_store)
        items = []
        for i, c in enumerate(maker.clips()):
            posted = "".join(f" · {k}: {'posted' if v.get('ok') else 'failed'}" for k, v in c["posted"].items())
            items.append(ITEM.format(i=i, n=len(c["caption"]), posted=posted, **{
                k: html.escape(str(v)) for k, v in c.items() if k != "posted"}))
        on = enabled_posters()
        body = PAGE.format(items="".join(items) or "<p>No clips yet: they are made at night (Tokyo).</p>",
                           tiktok="on" if "tiktok" in on else "off", youtube="on" if "youtube" in on else "off",
                           label=html.escape(LABEL), keep=KEEP_DAYS, log=html.escape("\n".join(maker.log[-10:])))
        return web.Response(text=body, content_type="text/html", headers=no_store)

    async def file(request):
        if not ok(request):
            raise web.HTTPUnauthorized(text="admin token required")
        name = request.match_info["name"]
        if not NAME.match(name) or not (maker.dir / name).exists():
            raise web.HTTPNotFound()
        return web.FileResponse(maker.dir / name, headers={**no_store,
                                                            "Content-Disposition": f'attachment; filename="sub01-{name}"'})

    async def login(request):
        token = os.environ.get("SUB01_ADMIN_TOKEN", "")
        got = str((await request.post()).get("token", ""))
        if not token or not hmac.compare_digest(got.encode(), token.encode()):
            return web.Response(text=LOGIN, content_type="text/html", status=401, headers=no_store)
        resp = web.HTTPFound("/admin/clips")
        resp.set_cookie(COOKIE, admin_cookie(token), max_age=7 * 86400, httponly=True, samesite="Strict",
                        path="/admin", secure=request.headers.get("X-Forwarded-Proto") == "https")
        raise resp

    app.router.add_get("/admin/clips", page)
    app.router.add_get("/admin/clips/file/{name}", file)
    app.router.add_post("/admin/clips/login", login)


# --- child entry points ---------------------------------------------------------------------------------------------
def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    req = json.loads(sys.stdin.read() or "{}")
    if cmd == "render":
        resource.setrlimit(resource.RLIMIT_CPU, (CPU_S, CPU_S + 1))
        t0 = time.monotonic()
        render(req, ffmpeg=req.get("ffmpeg") or "ffmpeg", cpu_base=0.0)
        kids = resource.getrusage(resource.RUSAGE_CHILDREN)
        print(json.dumps({"ok": True, "wall_s": round(time.monotonic() - t0, 1),
                          "cpu_s": round(cpu_used() + kids.ru_utime + kids.ru_stime, 1)}))
    elif cmd == "capture":
        resource.setrlimit(resource.RLIMIT_CPU, (ROOM_CPU_S, ROOM_CPU_S + 1))
        n = asyncio.run(capture_room(req["url"], req["out"], req.get("frames", ROOM_FRAMES), req.get("cookie"),
                                     req.get("executable"), req.get("proxy")))
        print(json.dumps({"ok": True, "frames": n}))
    else:
        print("usage: clips.py render|capture < request.json", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
