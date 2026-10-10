"""SUB-01 live: runs the whole-brain model in real time and feeds it Solana trades and chat messages.

    python live_server.py --mint <OUR token mint>   # real pump.fun / PumpSwap trades of our coin (env MINT; unset: no feed)
    python live_server.py --demo                                         # synthetic trades
    python live_server.py --demo --time-scale 60 --start 23:55           # one sim hour per real minute

Buys drive the reward + visual regions, sells drive salience + amygdala, large
trades hit the thalamus + attention network. Chat messages are stimuli (see chat.py).
A sleep circuit on the local Asia/Tokyo clock (sleep.py: Phillips-Robinson MA/VLPO flip-flop + REM-on/REM-off
oscillator) changes the rhythm, how much any stimulus gets through and the tonic neuromodulator levels;
during REM, stored messages and articles it read are replayed. Page on http://localhost:8765.
"""
import argparse
import asyncio
import base64
import struct
import json
import math
import os
import random
import re
import signal
import socket
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import aiohttp
import numpy as np
from aiohttp import web

from brain_sim import Brain
from chat import (RULES, TEACH_MAX_WORDS, TEACH_PER_DAY, NICK_MAX, Dedupe, RateLimiter, TeachLimits,
                  check as chat_check, check_teach, clean_nick, dedupe_key, stimulus as chat_stimulus)
from sleep import ROME, TZ, Clock, Memory, SleepEngine, Store, day_of, hhmm, next_bedtime, night_date
from eye import Eye, ReplicateLLM, load_env, market_mood
from diary import Diary
from real_baseline import RealBaseline
from life import LABEL as LIFE_LABEL, WORLD, Life
from twin.body import Body
from twin.neurochem import Neuromodulators
from research import Reader, reading_stimulus
from browse import Browser, card_title_ok, screen_showable
import audience
import brain_vote
import launchpad_eval
import chess_game
import clips
import music as music_mod
import costs
from browse_service import BrowserClient, BrowserDown, LocalBrowser
from search_sources import live_interest
import interests
import novelty
import screens
import search_sources
from readings import BrowseReadings
from screens import DA_LABEL, DopamineBursts, ScreensStatus
from eyes import Eyes
import mind as mind_mod
from tastes import PageWatch, Tastes
import state_io
from state_io import append_jsonl, load_json, read_jsonl, save_json

try:                                             # the GPU spiking brain is optional: the server runs without it
    from spiking import pod_manager as spiking_manager, server as spiking_server
except Exception as _e:
    spiking_manager = spiking_server = None
    print("spiking routes unavailable:", type(_e).__name__, flush=True)
from spiking.words import half_cue_ok              # torch-free, like pod_manager
from spiking import live as spiking_live           # numpy only: his spiking neurons in the day, a child process (#55)

HERE = Path(__file__).parent
START = time.monotonic()        # import time: the startup log line says how long the process took to listen (a deploy gap)
TICK = 0.05                     # seconds of simulated time per broadcast (real time)
BASELINE_DRIVE = 1.6            # excitability per z-unit of the recorded resting-state signal
GOOD = re.compile(r"\bgood\b!?", re.I)    # chat 'good!' -> dopamine pulse on the spiking pod
NOCACHE = {"Cache-Control": "no-cache"}   # pages change with deploys: always revalidate
NEURO_K = 3.0                   # excitability per unit of receptor-weighted gain change (gain stays in 0.5..1.5)
SAVE_S = 60                     # persist sleep state + memory every minute (real time)
TICK_RING = int(60 / TICK)      # tick durations kept for /api/health: the last minute
HEALTHY_S = 5.0                 # /healthz: 200 while the brain loop ticked within this many seconds, else 503
RESTING = "resting its eyes"    # what the pages say while the eye is over its daily cap
CHAT_INBOX = 10                 # chat messages waiting for his reply at most (C1); older ones are let go with a note
CHAT_PER_VIEWER = 3             # ... and at most this many from one viewer
CHAT_WAIT_S = 1200              # simulated seconds a message waits for him, unless he is at the desk answering
CHAT_RESERVE = 5                # hourly AI calls kept for chat: no page-read call starts while messages wait (C2)
CAP_LINE = "He has answered 40 messages today and is resting; back tomorrow."   # the in-world cap notice (C2)
GATED = web.AppKey("gated", bool)            # the app runs behind the password gate
ADMIN_PATHS = ("/api/costs", "/api/health")   # private even after launch: SUB01_ADMIN_TOKEN (or the password cookie)
REPLAY_AMP = 0.35               # replayed stimulus pattern, relative to the original message
RECALL_NOTE = "Recall by a simulated spiking network from a partial cue; a model, not a mind."
REPLAY_NOTE = "Replayed in his sleep: the stored pattern is played back into the brain model during REM."
RPC_WS = os.environ.get("SOLANA_WS", "wss://api.mainnet-beta.solana.com")   # e.g. a Helius wss URL (env, never logged)
DEXS = "https://api.dexscreener.com/latest/dex/tokens/{}"
PUMP_TRADE = bytes.fromhex("bddb7fd34ee661ee")   # pump.fun bonding curve TradeEvent
AMM_BUY = bytes.fromhex("67f4521f2cf57777")      # PumpSwap BuyEvent
AMM_SELL = bytes.fromhex("3e2f370aa503dc2a")     # PumpSwap SellEvent
# Anchor event discriminators are sha256("event:<Name>")[:8], so any program with a "TradeEvent" (e.g. Raydium
# LaunchLab) emits the same 8 bytes with another layout: an event only counts when the program that emitted it is
# pump.fun / PumpSwap, and when it is about our mint (bonding curve) or one of our pools (PumpSwap).
PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_AMM_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
MAX_TRADE_USD = 250_000.0       # a single trade above this is a decoding error or noise: ignored (logged <= 1/min)
POOLS_REFRESH_S = 600           # re-read our PumpSwap pool(s) from DexScreener (a bonding curve graduates live)
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
WS_HIGH_WATER = 512 * 1024      # per-socket write buffer before asyncio pauses it (and a send would wait)
WS_SNDBUF = 64 * 1024          # kernel send buffer of a websocket (instead of autotuned megabytes)
WS_SLOW_MIN = 16 * 1024         # a socket counts as slow when it holds > 1 s of its feed, but never below this
WIKI_DOWN_EVERY_S = 3600        # while the browser is wanted but down: at most one Wikipedia reading an hour (#89)
DA_BURST_K = 0.5                # phasic DA per unit burst (a strong buy's RPE gives ~0.4)
DA_REWARD = 8.0                 # reward-region drive per unit burst (a buy drives reward with 6-12)
WIKI_FALLBACK_S = 300           # the browser down this long (real seconds): Wikipedia feeds the readings (#79)
VIDEO_DRIVE = 6.0               # visual drive of a full scene change while he watches a video (a chat rule is 6-8)
SCREENS_SAVE_S = 60.0           # #89: /api/screens state saved at most this often (and at shutdown)
CHESS_THINK_S = (15.0, 45.0)    # simulated seconds he takes per move (the vote itself takes ~0.3 s of CPU)
CHESS_REPLY_S = (5.0, 15.0)     # ...and the opponent
CHESS_MIN_GAP_S = 0.7           # real seconds between moves at least (the accelerated demo clock)
CHESS_MAX_S = 90 * 60           # a game keeps him at the desk up to this long (simulated), then he gets up
MUSIC_BG_P = 0.4                # chance that an activity where music can play in the background gets some (#68)
MUSIC_NEXT_P = 0.5              # ...and that another background track follows the one that ended


# the novelty bonus (brain_vote.NOVELTY): a link or search not chosen in the last 7 days; with #40's new actions
NOVEL_ACTIONS = ("click", "open_video", "play_video", "next_page", "open_comments", "search", "site_search")


def target_key(option):
    """What novelty remembers: the link, or the query of a search (a site search for "bread" is not the web search)."""
    if option.get("href"):
        return option["href"]
    if option.get("target"):
        return f"{option['action']}:{option['target']}" if option["action"] == "site_search" else option["target"]
    return option["action"]


def b58decode(text):
    """Base58 (Solana addresses) -> bytes; ValueError on a bad character."""
    n = 0
    for c in text:
        n = n * 58 + B58.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(text) - len(text.lstrip("1"))) + raw


DEFAULT_CA = "6WCtKQfkWurd77tCCAYWuL5TwyAvuovTzworfnfupump"      # the coin's contract address (owner, 2026-10-11)
CITY_URL = os.environ.get("SUB01_CITY_URL", "https://city.subzerone.live/").strip()   # the city: his neighbourhood site


def coin_address(mint=""):
    """The coin's contract address for the pages (owner, 2026-10-11): SUB01_CA, else MINT, else DEFAULT_CA. The pages
    show it as it is, with a copy button and no market link: not advice, only the official address, so nobody has to
    trust one pasted in the chat (where addresses stay blocked). Not a Solana address (32 bytes of base58): nothing."""
    ca = (os.environ.get("SUB01_CA") or mint or DEFAULT_CA or "").strip()
    try:
        return ca if ca and len(b58decode(ca)) == 32 else ""
    except ValueError:
        return ""


def b58encode(b):
    n, out = int.from_bytes(b, "big"), ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


def emitted(logs):
    """'Program data:' lines with the program that emitted them (the innermost invoked program at that line)."""
    stack, out = [], []
    for line in logs:
        if line.startswith("Program data: "):
            out.append((stack[-1] if stack else None, line[14:]))
        elif line.startswith("Program "):
            p = line.split()
            if len(p) >= 3 and p[2] == "invoke":
                stack.append(p[1])
            elif len(p) >= 3 and p[2] in ("success", "failed:", "failed") and stack:
                stack.pop()
    return out


def decode_trades(logs, mint=None, pools=None):
    """Anchor events of pump.fun / PumpSwap in a transaction's logs -> [{kind, sol}].
    pump.fun bonding curve TradeEvent: mint (32), sol_amount u64, token_amount u64, is_buy bool, ... (lamports).
    PumpSwap Buy/SellEvent: timestamp, base_amount, quote limit, user base/quote reserves, pool base/quote reserves,
    quote_amount (u64 each), ..., pool pubkey at byte 120. Only events emitted by those two programs count; with
    `mint`, a TradeEvent must be about that mint; with `pools`, a PumpSwap event must be about one of those pools
    (a route through someone else's pool in the same transaction is not our trade). No pools known -> no PumpSwap."""
    out = []
    want_mint = b58decode(mint) if mint else None
    for prog, data in emitted(logs):
        try:
            b = base64.b64decode(data)
        except ValueError:
            continue
        if b[:8] == PUMP_TRADE and prog == PUMP_PROGRAM and len(b) >= 57:
            if want_mint is not None and b[8:40] != want_mint:
                continue
            sol, _, is_buy = struct.unpack_from("<QQ?", b, 40)
            out.append({"kind": "buy" if is_buy else "sell", "sol": sol / 1e9})
        elif b[:8] in (AMM_BUY, AMM_SELL) and prog == PUMP_AMM_PROGRAM and len(b) >= 152:
            if pools is not None and b58encode(b[120:152]) not in pools:
                continue
            f = struct.unpack_from("<8Q", b, 8)
            buy_base = b[:8] == AMM_BUY
            if f[5] < f[6]:          # smaller raw reserve = SOL side (9 decimals vs the token's 6), so SOL is the base
                sol, is_buy = f[1], not buy_base
            else:                    # the usual pump pool: base = the token, quote = WSOL
                sol, is_buy = f[7], buy_base
            out.append({"kind": "buy" if is_buy else "sell", "sol": sol / 1e9})
    return out


LITE_DROP = ("act", "wave", "groups", "slow")     # per-region brain activity: only the brain page draws it
ACT_LO, ACT_HI = 0.01, 10.0     # q=1: act on a log scale, one byte a region (~1.4 % steps), clipped to this range
# q=1 keeps only what web/index.html draws (one source of truth for the brain page's fields). S1: the coin's trades
# are a stimulus only (Live.apply), never in a tick: no trade tape, amounts or buy / sell words reach a page.
BRAIN_KEEP = ("type", "sync", "events", "sleep", "baseline", "slow", "life")
BRAIN_SLEEP = ("stage", "burst", "clock", "tz", "gain", "debt", "woken_tonight")
BRAIN_LIFE = ("doing", "walking")


# S4: a search or reading that started from the chat says so ("a viewer's wish in chat", "from chat"), never what the
# viewer wrote: the quoted text after the chat origin is cut from every `why` the server hands out (the screen card,
# the reading card, /api/reading), whatever the browser or the reader stored
CHAT_WHY = re.compile(r"^(.*?\bchat)\s*[:：]\s*[“\"'].*$", re.S)


def public_why(rec, copy=True):
    """`rec` (a status or reading dict, or None) with its `why` cut after a chat origin; copy=False edits it in place."""
    why = rec.get("why") if isinstance(rec, dict) else None
    if not isinstance(why, str) or not (m := CHAT_WHY.match(why)):
        return rec
    if copy:
        rec = dict(rec)
    rec["why"] = m.group(1)
    return rec


def quantise_act(act):
    """Per-region activity -> base64 of one byte a region, log-spaced between ACT_LO and ACT_HI."""
    a = np.clip(np.asarray(act, dtype=float), ACT_LO, ACT_HI)
    q = np.rint(255 * np.log(a / ACT_LO) / math.log(ACT_HI / ACT_LO)).astype(np.uint8)
    return base64.b64encode(q.tobytes()).decode()


def dequantise_act(text):
    """Inverse of quantise_act (what web/index.html does in JS)."""
    q = np.frombuffer(base64.b64decode(text), dtype=np.uint8)
    return (ACT_LO * (ACT_HI / ACT_LO) ** (q / 255.0)).tolist()


class Feed:
    """What a websocket client gets. Default (plain /ws): every tick, 20 a second, as before.
    /ws?rate=5 sends ~5 ticks a second, carrying the events of the skipped ticks;
    &lite=1 leaves out the per-region activity and the spiking frames (for pages that do not draw the brain, e.g. the room);
    &q=1 is the brain page's feed: `act` quantised to one byte a region (`aq`, see quantise_act) and only the
    fields the brain page draws (well under 1.5 KB a tick).
    Clients asking for the same (rate, lite, q) share one Feed (Live.feed_for), so a tick is serialised once per
    variant, not once per client."""

    RATES = (1.0, 20.0)                                 # ticks a second a client may ask for

    def __init__(self, rate=None, lite=False, q=False):
        if rate is not None:                            # clamped: a tiny rate would buffer events without bound
            rate = min(max(rate, self.RATES[0]), self.RATES[1])
        self.every = max(1, round(1.0 / (TICK * rate))) if rate else 1
        self.lite, self.q, self.n, self.events = lite, q and not lite, 0, []
        self.rx = None                                  # reactions summed over skipped ticks
        self.bps = 0.0                                  # bytes a second of this feed's ticks (slow-client check)
        self.phase = 0                                  # global tick (mod every) its sends land on; see Live.feed_for

    @property
    def key(self):
        return self.every, self.lite, self.q

    @classmethod
    def from_query(cls, query):
        try:
            rate = float(query.get("rate", ""))
        except ValueError:
            rate = None
        if rate is not None and not (math.isfinite(rate) and rate > 0):
            rate = None                                 # unusable: every tick, as plain /ws
        on = ("1", "true")
        return cls(rate, query.get("lite") in on, query.get("q") in on)

    def take(self, msg, data):
        """The text to send for `msg` (already serialised as `data`), or None to skip this tick."""
        if msg.get("type") != "tick":
            return None if self.lite and msg.get("type") == "spiking" else data    # the room does not draw them
        if self.every == 1 and not self.lite and not self.q:
            self.bps = len(data) / TICK
            return data
        out = msg
        if self.every > 1:
            self.events += msg.get("events") or []
            if msg.get("rx"):                          # viewers' reactions: summed over the skipped ticks
                self.rx = [a + b for a, b in zip(self.rx, msg["rx"])] if self.rx else list(msg["rx"])
            self.n += 1
            if (self.n - 1) % self.every:              # the first tick goes out at once, then every n-th
                return None
            out = msg | {"events": self.events}
            out.pop("rx", None)
            if self.rx:
                out["rx"] = self.rx
            self.events, self.rx = [], None
        if self.lite:
            out = {k: v for k, v in out.items() if k not in LITE_DROP}
        elif self.q:
            out = self.brain_view(out)
        text = json.dumps(out, separators=(",", ":"))
        self.bps = len(text) / (TICK * self.every)
        return text

    @staticmethod
    def brain_view(msg):
        out = {k: msg[k] for k in BRAIN_KEEP if k in msg}
        if "act" in msg:
            out["aq"] = quantise_act(msg["act"])
        if isinstance(out.get("sleep"), dict):
            out["sleep"] = {k: out["sleep"][k] for k in BRAIN_SLEEP if k in out["sleep"]}
        if isinstance(out.get("life"), dict):
            out["life"] = {k: out["life"][k] for k in BRAIN_LIFE if k in out["life"]}
        if isinstance(out.get("slow"), dict):
            out["slow"] = {"label": out["slow"].get("label")}
        if isinstance(out.get("baseline"), dict):
            out["baseline"] = {"run": out["baseline"].get("run")}
        return out


def local_accounts():
    """#89: per site "logged in" / "logged out" and why, read here when the browser process has not reported yet
    (the same sessions it loads from the environment). Never a cookie."""
    try:
        import sessions as SE
        out = {}
        for site, sess in SE.load_sessions().items():
            sess.check()
            out[site] = {"state": "logged in" if sess.logged_in else "logged out", "reason": sess.status()["reason"]}
        return out
    except Exception as e:                                  # pragma: no cover - reported, never raised
        return {"error": type(e).__name__}


class Live:
    def __init__(self, mint, demo, time_scale=1.0, data_dir=HERE / "data", start=None, trust_proxy=False):
        self.brain = Brain()
        self.mint, self.demo = mint, demo
        self.ca = coin_address(mint)       # shown on the pages (hello, /api/config); "" until the owner sets it
        self.trust_proxy = trust_proxy
        self.store = Store(data_dir)
        saved, mem = self.store.load()
        self.memory = Memory(mem)
        self.purge_blocked(saved)
        if start is None and saved and time_scale != 1:
            start = saved["t"]                                   # accelerated clock resumes where it stopped
        self.clock = Clock(time_scale, start)
        now = self.clock.now()
        self.engine = SleepEngine.from_dict(saved) if saved else SleepEngine(now)
        self.engine.t = min(self.engine.t, now)
        self.engine.update(now)
        self.limiter, self.dedupe = RateLimiter(), Dedupe()
        self.teach_limits = TeachLimits(path=Path(data_dir) / "teach.json")   # 1 per viewer/day, TEACH_PER_DAY in total
        self.gpu_test = False                      # main(): True when the spiking pod manager is enabled
        for m in self.memory.chat()[-200:]:
            self.dedupe.recent.append(dedupe_key(m["text"]))
        self.burst = 0.0
        self.sol_usd = 150.0
        self.init_sockets()
        self.pending = []           # trades waiting to be played into the brain
        self.seen = set()
        self.pool_name = "demo" if demo else (mint[:6] if mint else "no coin yet")   # MINT unset: no feed
        self.pools = set()                 # our PumpSwap pool address(es), from DexScreener (rpc_trades)
        self.absurd_logged = 0.0           # last time an absurd trade was logged (at most once a minute)
        self.stats = {"buys": 0, "sells": 0, "usd": 0.0}
        self.eye = None                  # set by main() with --eye
        self.diary = None                # dream diary, set by main() with --eye
        self.data_dir = Path(data_dir)
        self.ledger = costs.Ledger(data_dir)   # costs.py: every paid service per Tokyo day + the daily caps (#15)
        self.eye_resting = None          # why the eye is resting (a daily cap), else None
        self.tick_s = deque(maxlen=TICK_RING)  # run_brain body durations (s), the last minute: /api/health
        self.last_tick = None            # time.monotonic() at the end of the last brain tick: /healthz
        life_path = Path(data_dir) / "life.json"
        self.life_path = life_path
        self.body_path = Path(data_dir) / "body.json"
        bs = load_json(self.body_path, {})              # state_io: a torn file is kept aside, never a crash loop
        life_state = load_json(life_path)
        if not bs.get("body") and life_state and "hunger" in life_state:      # first start: carry the old hunger over
            bs["body"] = {"ghrelin": min(1.0, max(0.0, life_state["hunger"]))}
        self.body = Body(bs.get("body"))
        self.neuro = Neuromodulators(state=bs.get("neuro"))
        atlas = json.load(open(HERE / "out" / "atlas_names.json"))
        self.nm_idx = np.array([atlas.index(n) for n in self.brain.names])
        self.life = Life(life_state, body=self.body)
        self.time_scale = time_scale
        self.life.time_scale = time_scale
        self.reading_path = Path(data_dir) / "reading.json"
        self.reader = Reader(load_json(self.reading_path))
        self.browse_readings = BrowseReadings()   # #79: readings come from the pages he stays on
        self.screens_path = Path(data_dir) / "screens.json"   # #89: /api/screens' today and last survive a deploy
        self.screens = ScreensStatus(state=load_json(self.screens_path, {}))   # #89: what is really on his screens
        self.screens_saved = 0.0
        self.da_bursts = DopamineBursts()  # #89: a simulated dopamine-like burst when something new plays
        self.browse_wanted = False       # main(): --browse was asked for (then Wikipedia is capped while it is down)
        self.last_wiki_read = 0.0
        self.browser_down_since = None   # wall time the browser went down (Wikipedia is the fallback after a while)
        self.browsing_path = Path(data_dir) / "browsing.json"
        self.browser = None              # BrowserClient (main() with --browse): Chromium runs in its own process
        self.local_browser = None        # LocalBrowser when that process is our child (no BROWSE_SERVICE_URL)
        self.browsing_state = load_json(self.browsing_path, {})
        self.eyes = None                 # eyes.py: an AI lists options; the brain model picks (brain_vote.py)
        self.tastes = Tastes(Path(data_dir) / "tastes.json")
        self.pagewatch = PageWatch()
        self.decisions = {}              # device -> last decision record (shown in the screen card)
        self.decision_log = []
        self.targets = {}                # link / search -> wall time last chosen (novelty)
        seed = os.environ.get("BRAIN_DECIDES_SEED")
        self.vote_rng = np.random.default_rng(int(seed) if seed else None)
        self.baseline = None             # set by main() with --replay-real-session (else the fitted slow layer runs)
        self.eye_every = 90.0            # seconds between eye frames while awake (--eye-every)
        self.recent_trades = []          # (t, kind, usd) for the eye's market mood
        self.recent_replays = []         # REM replays for the eye's dreams
        self.recent_read_replays = []    # ...and titles of replayed readings
        self.last_groups = {}
        self.last_rel = {}               # group activity / mean, guides what it reads next
        self.last_frame = None
        self.spiking = None              # SpikingHub, set by spiking.server.attach in main()
        self.decider = None              # brain_vote.Backend (main()): a spiking network votes too, GPU or CPU (#55)
        self.mind = None                 # mind.py (main()): an AI reads and remembers for him; his brain model chooses
        self.chat_inbox = []             # {t, text, key, nick, tries}: messages he may answer at the computer, FIFO (C1)
        self.chat_served = {}            # viewer key -> sim t of their last answered message (round-robin, memory only)
        self.cap_noted = None            # Tokyo day the "resting, back tomorrow" chat line was posted (C2)
        self.replies = []                # his recent replies (AI-written), for the hello and /api/mind
        self.read_topics = {}            # page title -> topics an AI noted (the eye's dream scenes)
        self.interest = (0.0, None)      # (wall time, mind.next_interest()) cached for the browser
        self.search_rng = random.Random()  # which of his query sources the browser's next search comes from (#56)
        self.plan_rng = np.random.default_rng(int(seed) + 1 if seed else None)
        self.bg = set()                  # background tasks (mind reading), kept referenced until done
        self.chess = None                # chess_game.Game while he plays at the desk (#17)
        self.chess_last = None           # the last finished game (public view), for /api/chess
        self.chess_path = Path(data_dir) / "chess.jsonl"
        self.chess_rng = random.Random(int(seed) + 2 if seed else None)
        self.chess_vote_rng = np.random.default_rng(int(seed) + 3 if seed else None)   # not shared across threads
        # music (#68): his brain model picks tracks; pages show Spotify's official embed (no audio on the server)
        self.music = music_mod.Music(data_dir, api=music_mod.SpotifyAPI.from_env(),
                                     rng=random.Random(int(seed) + 4 if seed else None))
        self.music_watch = PageWatch()     # the stay response while a track plays feeds the tastes
        self.music_vote_rng = np.random.default_rng(int(seed) + 5 if seed else None)
        self.music_rng = random.Random(int(seed) + 6 if seed else None)
        self.music_bg = (None, False)      # (the activity start it was rolled for, background music wanted)
        self.music_busy = False            # a pick is being made (worker threads)
        # viewers (preview/interactive, audience.py): the vote on what he does next, the viewer count, the reactions
        self.votes = audience.Votes(rng=random.Random(int(seed) + 7 if seed else None))
        self.reactions = audience.Reactions()

    # --- trades -> stimuli ---------------------------------------------------
    def apply(self, tr):
        gain = self.engine.stimulus(self.clock.now(), "trade", tr["usd"])     # asleep: less gets through
        s = gain * min(15.0, 2.0 + 3.0 * math.log10(1.0 + tr["usd"]))
        b = self.brain
        if tr["kind"] == "buy":
            b.stimulate("reward", s)
            b.stimulate("visual", 0.5 * s)
            self.stats["buys"] += 1
        else:
            b.stimulate("salience", s)
            b.stimulate("fear", s)
            self.stats["sells"] += 1
        if tr["usd"] >= 1000:
            b.stimulate("relay", 10 * gain)
            b.stimulate("attention", 8 * gain)
        self.stats["usd"] += tr["usd"]
        self.neuro.on_trade(tr["kind"], tr["usd"], t=time.time())          # buys: dopamine RPE; sells: noradrenaline
        self.recent_trades = [x for x in self.recent_trades if time.time() - x[0] < 300] + [(time.time(), tr["kind"], tr["usd"])]

    async def lookup_pools(self, http):
        """Our token's name and PumpSwap pool(s) from DexScreener, refreshed every POOLS_REFRESH_S."""
        while True:
            try:
                async with http.get(DEXS.format(self.mint)) as r:
                    pairs = (await r.json()).get("pairs") or []
                if pairs:
                    self.pool_name = f"${pairs[0]['baseToken']['symbol']}"
                self.pools = {p["pairAddress"] for p in pairs if p.get("dexId") == "pumpswap" and p.get("pairAddress")}
            except Exception as e:
                print("pool lookup failed:", type(e).__name__, flush=True)
            await asyncio.sleep(POOLS_REFRESH_S)

    def take_trade(self, tr, sig):
        """A decoded trade -> the pending queue, unless it is absurd (a decoding error must never reach the brain)."""
        tr["usd"] = tr.pop("sol") * self.sol_usd
        if not (0.0 <= tr["usd"] <= MAX_TRADE_USD):
            now = time.time()
            if now - self.absurd_logged >= 60:
                self.absurd_logged = now
                print(f"ignored an absurd trade (${tr['usd']:,.0f} > ${MAX_TRADE_USD:,.0f}) in {sig[:16]}…", flush=True)
            return False
        tr["tx"], tr["who"], tr["at"] = sig, "", time.time()
        self.pending.append(tr)
        return True

    async def rpc_trades(self):
        """Stream every pump.fun / PumpSwap trade of OUR mint straight from Solana logs. No MINT: no feed at all."""
        if not self.mint:
            print("trade feed off: MINT is not set (no coin yet)", flush=True)
            return
        try:
            ok = len(b58decode(self.mint)) == 32
        except ValueError:
            ok = False
        if not ok:
            print("trade feed off: MINT is not a valid Solana address", flush=True)
            return
        async with aiohttp.ClientSession() as http:
            asyncio.create_task(self.lookup_pools(http))
            asyncio.create_task(self.sol_price(http))
            backoff = 2.0
            while True:
                try:
                    async with http.ws_connect(RPC_WS, heartbeat=30) as ws:
                        await ws.send_json({"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                                            "params": [{"mentions": [self.mint]}, {"commitment": "confirmed"}]})
                        backoff = 2.0
                        async for m in ws:
                            v = json.loads(m.data).get("params", {}).get("result", {}).get("value")
                            if not v or v.get("err"):
                                continue
                            for tr in decode_trades(v["logs"], self.mint, self.pools):
                                self.take_trade(tr, v["signature"])
                except Exception as e:                    # public RPCs refuse some cloud IPs: back off, don't hammer
                    if backoff == 2.0 or backoff >= 60:
                        print(f"rpc stream error, retrying every {backoff:.0f}s:", str(e).split(", url=")[0], flush=True)
                    await asyncio.sleep(backoff)
                    backoff = min(60.0, backoff * 2)

    async def sol_price(self, http):
        while True:
            try:
                async with http.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd") as r:
                    self.sol_usd = float((await r.json())["solana"]["usd"])
            except Exception:
                pass
            await asyncio.sleep(600)

    async def demo_trades(self):
        while True:
            await asyncio.sleep(random.expovariate(1.5))
            kind = "buy" if random.random() < 0.55 else "sell"
            usd = math.exp(random.gauss(3.5, 1.6))
            self.pending.append({"kind": kind, "usd": usd, "tx": "", "who": "demo", "at": time.time()})

    # --- chat -> stimuli + memory -----------------------------------------------
    @staticmethod
    def public(m):
        return {"text": m["text"], "t": hhmm(m["t"]), "networks": m["networks"], "emotion": m["emotion"],
                "asleep": m["asleep"], "stage": m["stage"]}

    def heard(self, t):
        """Recent chat texts (not readings), newest last."""
        return [m["text"] for m in self.memory.chat()[-5:] if t - m["t"] < 3 * 3600]

    def absorb_reading(self, art):
        """An article it opened becomes a stimulus (chat rules at half gain + language/attention) and a memory."""
        t = self.clock.now()
        stim, hits, emotion = reading_stimulus(art["title"], art.get("keywords", []))
        gain = self.engine.gain                               # asleep = attenuated, as for chat
        for g, a in stim.items():
            self.brain.stimulate(g, a * gain)
        m = self.memory.add(t, art["title"], self.engine.stage, stim, emotion, hits, source="reading",
                            title=art["title"], keywords=art.get("keywords", []), url=art.get("url", ""),
                            host=art.get("host", "en.wikipedia.org"), kind=art.get("kind", "wiki"),
                            via=art.get("via", "wikipedia"))
        art.update(networks=hits, emotion=emotion, gain=round(gain, 2))
        return m

    def tonight_chance(self, m):
        """Estimated chance this memory is replayed tonight (blocking: run in a worker thread)."""
        return round(self.memory.replay_chance(m, next_bedtime(self.clock.now())), 2)

    def reading_now(self, t):
        """The article on the desk for the tick; its tonight estimate only while it is about the coming night."""
        art = self.reader.current()
        if art and "tonight" in art and art.get("tonight_night") != night_date(next_bedtime(t)):
            art = {k: v for k, v in art.items() if k != "tonight"}
        return public_why(art)

    async def handle_chat(self, ws, key, text, nick=""):
        ok, reason = chat_check(text, key, self.limiter, self.dedupe)      # filter first; blocked = never stored
        if not ok:
            await ws.send_json({"type": "chat_ack", "ok": False, "reason": reason})
            return
        text = text.strip()
        t = self.clock.now()
        stim, hits, emotion = chat_stimulus(text)
        gain = self.engine.stimulus(t, "message")
        for g, a in stim.items():
            self.brain.stimulate(g, a * gain)
        m = self.memory.add(t, text, self.engine.stage, stim, emotion, hits)
        if self.eye:
            self.eye.hear(text, t)
        self.life.hear(text, t)
        self.music.hear(text, t)                           # "play …" / "metti …": a wish (filtered above)
        ack = {"type": "chat_ack", "ok": True, "queued": False}
        if getattr(self, "mind", None):                    # he may answer it later, at the computer (C1)
            why = await self.enqueue_chat(t, text, key, nick)
            ack.update(queued=True, will_reply=why is None, reason=why)
        if self.spiking:                                   # no-op when no GPU pod is connected
            self.spiking.forward_chat(text, emotion)
            if GOOD.search(text):
                self.spiking.forward_good()
        await ws.send_json(ack)
        await self.broadcast({"type": "chat", "gain": round(gain, 2), **self.public(m)})

    # --- the chat inbox (C1/C2): FIFO, one viewer at a time, a visible outcome for every message -----------------
    async def enqueue_chat(self, t, text, key, nick=""):
        """Queue a message for his reply at the computer; returns why a reply is not possible right now (or None).
        A viewer keeps at most CHAT_PER_VIEWER messages waiting: their oldest one is let go with a note."""
        nick, _ = clean_nick(nick)
        mine = [x for x in self.chat_inbox if x["key"] == key]
        for x in mine[:max(0, len(mine) + 1 - CHAT_PER_VIEWER)]:
            await self.chat_missed(x, "a newer message from the same viewer took its place")
        self.chat_inbox.append({"t": t, "text": text, "key": key, "nick": nick, "tries": 0})
        for x in self.chat_inbox[:-CHAT_INBOX]:
            await self.chat_missed(x, "too many messages were waiting")
        self.chat_inbox = self.chat_inbox[-CHAT_INBOX:]
        return (None if self.engine.stage == "AWAKE" else "asleep") or self.mind.reply_open()

    async def chat_missed(self, item, why):
        """The message leaves the inbox unanswered: viewers see why (room.html: a dim line under the message)."""
        if item in self.chat_inbox:
            self.chat_inbox.remove(item)
        await self.broadcast({"type": "chat_missed", "t": hhmm(self.clock.now()), "replying_to": item["text"],
                              "why": why, "tag": "not answered"})

    def next_message(self, t=None):
        """The message he answers next (C1): the viewer answered longest ago (or never) first, their oldest first."""
        served = self.chat_served
        return min(self.chat_inbox, key=lambda x: (served.get(x["key"], -1e18), x["t"]))

    def doing_now(self, t):
        """What he is really doing, for a reply's context (C4): the activity, the track playing, the article or the
        page on his screen. Built from state already in memory; no new calls."""
        life = self.life
        parts = [LIFE_LABEL.get(life.activity, life.activity)]
        now = getattr(getattr(self, "music", None), "now", None)
        if now and now.get("title"):
            parts.append(f"listening to “{now['title']}”" + (f" by {now['artist']}" if now.get("artist") else ""))
        art = self.reader.current() if life.activity == "research" and getattr(self, "reader", None) else None
        if art and art.get("title"):
            parts.append(f"reading “{art['title']}”")
        elif getattr(self, "browser", None) and (dev := self.screen_device()):
            st = self.browser.screens.get(dev) or {}
            if st.get("title") and card_title_ok(st.get("title", ""), st.get("host", "")):
                parts.append(f"on the {dev} screen: “{st['title']}”")
        return "; ".join(parts)[:160]

    def taught_on(self, day):
        return [m for m in self.memory.items if m.get("source") == "taught" and day_of(m["t"]) == day]

    async def handle_teach(self, ws, key, text, nick):
        """A viewer teaches him a word or a short phrase: the chat filter, then the limits; it becomes a stimulus (chat
        rules) and a memory with source "taught" (stronger replay weight, capped). The nickname is display only."""
        t = self.clock.now()
        day = day_of(t)
        ok, reason, text, nick = check_teach(text, nick, key, self.teach_limits, day,
                                             [m["text"] for m in self.taught_on(day)])
        if not ok:
            await ws.send_json({"type": "teach_ack", "ok": False, "reason": reason})
            return
        stim, hits, emotion = chat_stimulus(text)
        gain = self.engine.stimulus(t, "message")
        for g, a in stim.items():
            self.brain.stimulate(g, a * gain)
        m = self.memory.add(t, text, self.engine.stage, stim, emotion, hits, source="taught", nick=nick, replays=0)
        self.store.save(self.engine, self.memory)          # at most 30 a day: a restart never loses a taught item
        await ws.send_json({"type": "teach_ack", "ok": True})
        await self.broadcast({"type": "taught", "gain": round(gain, 2), **self.public(m), "nick": nick})

    def taught(self):
        """GET /api/taught: today's taught items and yesterday's, each with its nickname, how often it was replayed in
        his sleep and, when the GPU test is on and has run, the next-day recall result."""
        t = self.clock.now()
        today = day_of(t)
        yesterday = day_of(t - 86400)
        results = self.spiking.taught_results() if self.gpu_test and self.spiking else {}

        def row(m):
            day = day_of(m["t"])
            out = {"text": m["text"], "nick": m.get("nick", ""), "t": hhmm(m["t"]), "day": day,
                   "replayed": m.get("replays", 0)}
            if self.gpu_test:
                r = results.get((day, m["text"]))
                out["testable"] = half_cue_ok(m["text"])
                out["result"] = None if r is None else {
                    "recalled": bool(r.get("recalled")), "score": r.get("score"), "best_lure": r.get("threshold"),
                    "days_since": r.get("days_since"), "test_day": r.get("test_day")}
            return out
        taught_today = self.taught_on(today)
        return {"day": today, "gpu": self.gpu_test, "note": RECALL_NOTE if self.gpu_test else REPLAY_NOTE,
                "max_words": TEACH_MAX_WORDS, "nick_max": NICK_MAX, "per_day": TEACH_PER_DAY,
                "left": max(0, TEACH_PER_DAY - len(taught_today)),
                "today": [row(m) for m in taught_today], "yesterday": [row(m) for m in self.taught_on(yesterday)]}

    def nights(self):
        def summary(n):
            if not n:
                return None
            reading = sum(1 for r in n["replays"] if r.get("source") == "reading")
            taught = sum(1 for r in n["replays"] if r.get("source") == "taught")
            return {"date": n["date"], "sleep_onset": n["sleep_onset"], "woke_up": n["woke_up"],
                    "wakeups": n["wakeups"], "replays": n["replays"][-20:], "sleep_debt": n["sleep_debt"],
                    "n_replays": {"chat": len(n["replays"]) - reading - taught, "reading": reading, "taught": taught}}
        return {"type": "nights", "last": summary(self.engine.last_night), "tonight": summary(self.engine.night)}

    def init_sockets(self):
        """Websocket bookkeeping (also used alone by tests/test_feed.py)."""
        self.clients = set()
        self.feeds = {}             # websocket -> Feed (its tick rate and fields), shared per variant
        self.variants = {}          # Feed.key -> the one Feed all clients of that variant share
        self.transports = {}        # websocket -> its transport (write-buffer size for the slow-client check)
        self.sockets = set()        # every accepted websocket, also while its hello is being sent
        self.ws_per_ip = {}         # client address -> open websockets (only counts, kept in memory)
        # viewers (audience.py): per connection, set in ws_handler, so here with the rest of the websocket state
        self.viewer_fp = audience.Fingerprints()   # the process's salt (memory only): a connection's ids, never raw
        self.viewer_ids = {}        # websocket -> its salted hashes (cookie, IP + UA), dropped with the connection
        self.viewer_addr = {}       # websocket -> its address's salted hash (per-address caps: votes, reactions)
        self.max_ws = int(os.environ.get("SUB01_MAX_WS", 400))
        # per address: 12, not 4 - a viewer with a few tabs, and the phones of a whole carrier behind one NAT address,
        # were refused with "full" (2026-10-09: the room stuck at "connecting…" for the owner's own tabs). The total cap
        # still bounds the process; both are env-tunable
        self.max_ws_ip = int(os.environ.get("SUB01_MAX_WS_PER_IP", 12))
        self.ws_stats = {"lag": [], "late": [], "skipped": 0, "refused": 0, "t0": None, "ticks": 0,
                         "at": time.monotonic(), "every": float(os.environ.get("SUB01_WS_STATS_S", 300))}

    async def broadcast(self, msg):
        """Send to every client: serialised once, then once per feed variant; a slow client skips ticks."""
        data = json.dumps(msg)
        tick = msg.get("type") == "tick"
        if tick:
            self.note_tick()
        outs = {}
        for ws in list(self.clients):
            feed = self.feeds.get(ws)
            if feed is None:
                out = data
            else:
                if feed.key not in outs:
                    outs[feed.key] = feed.take(msg, data)
                out = outs[feed.key]
            if out is None:
                continue
            if self.backlogged(ws, feed, tick):
                self.ws_stats["skipped"] += 1
                continue
            try:
                await ws.send_str(out)          # returns at once: the buffer never reaches WS_HIGH_WATER (backlogged)
            except Exception:
                self.drop_client(ws)

    def backlogged(self, ws, feed, tick):
        """True if this socket still holds more than ~1 s of its feed: skip the tick instead of queueing it.
        Other messages (chat, eye, ...) are rare and small; they only wait out a socket that is half full."""
        tr = self.transports.get(ws)
        if tr is None:
            return False
        try:
            held = tr.get_write_buffer_size()
        except Exception:
            return False
        if not tick:
            return held > WS_HIGH_WATER // 2
        return held > min(max(feed.bps if feed else 0.0, WS_SLOW_MIN), WS_HIGH_WATER // 2)

    def note_tick(self):
        """Brain tick lag, as broadcast sees it, two ways: `late`, how late this tick's step started against its
        50 ms slot (what sends to viewers can delay: a tick only starts late if the last one overran), and `jitter`,
        how late this broadcast is against the fastest one on the 50 ms grid (adds the step's own variation).
        Logged every SUB01_WS_STATS_S seconds (default 300) with the socket counts; tests/load_ws.py reads it."""
        st, now = self.ws_stats, time.monotonic()
        st["ticks"] += 1
        due = (st["t0"] if st["t0"] is not None else now) + st["ticks"] * TICK
        if now < due:
            st["t0"], due = now - st["ticks"] * TICK, now
        if len(st["lag"]) < 20000:                     # bounded even with a long SUB01_WS_STATS_S
            st["lag"].append(now - due)
            st["late"].append(max(0.0, getattr(self, "tick_late", 0.0)))
        if now - st["at"] >= st["every"]:
            pct = lambda xs, p: 1000 * xs[min(len(xs) - 1, int(p * len(xs)))]
            late, lag = sorted(st["late"]), sorted(st["lag"])
            n = {}
            for f in self.feeds.values():
                n[f.key] = n.get(f.key, 0) + 1
            variants = " ".join(f"{e}{'L' if lite else ''}{'Q' if q else ''}:{n.get((e, lite, q), 0)}"
                                for (e, lite, q) in sorted(self.variants))
            print(f"ws stats: {len(self.sockets)} sockets ({variants or '-'}) · tick late p50 {pct(late, 0.5):.1f} "
                  f"p95 {pct(late, 0.95):.1f} max {1000 * late[-1]:.1f} ms · jitter p50 {pct(lag, 0.5):.1f} "
                  f"p95 {pct(lag, 0.95):.1f} max {1000 * lag[-1]:.1f} ms · over {len(lag)} ticks · skipped "
                  f"{st['skipped']} sends to slow clients · refused {st['refused']} (full)", flush=True)
            st.update(lag=[], late=[], skipped=0, refused=0, at=now)

    def feed_for(self, query):
        """The shared Feed for this query's (rate, lite, q) variant. A new variant gets the tick phase that collides
        least with the others' sends (e.g. 10/s on even ticks, the room's two 5/s feeds on ticks 1 and 3 of 4),
        so one tick does not carry every client's send."""
        feed = Feed.from_query(query)
        if feed.key in self.variants:
            return self.variants[feed.key]
        e = feed.every
        if e > 1:
            busy = [sum(1 for v in self.variants.values() for t in range(60)
                        if t % e == ph and (t - v.phase) % v.every == 0) for ph in range(e)]
            feed.phase = busy.index(min(busy))
            feed.n = (self.ws_stats["ticks"] - feed.phase + 1) % e     # its sends land on ticks == phase (mod e)
        self.variants[feed.key] = feed
        return feed

    def drop_client(self, ws):
        self.clients.discard(ws)
        self.transports.pop(ws, None)
        feed = self.feeds.pop(ws, None)
        if feed is not None and feed not in self.feeds.values():
            self.variants.pop(feed.key, None)            # last client of this variant: its buffers go with it

    def purge_blocked(self, saved):
        """Messages the chat filter blocks today (chat.blocked: trading pushes, adult requests, insults...) that were
        accepted before the rule existed are dropped from his memory, so they are neither in the history the page
        gets on hello nor replayed in his sleep (2026-10-09: "watch porno" from 22:31 came back as a night replay
        and in the diary), and from the saved nights' replay lists."""
        from chat import message_blocked as blocked
        n0 = len(self.memory.items)
        self.memory.items = [m for m in self.memory.items
                             if m.get("source", "chat") != "chat" or not blocked(str(m.get("text", "")))]
        dropped = n0 - len(self.memory.items)
        for night in ([saved.get("night"), saved.get("last_night")] if saved else []):
            if night and isinstance(night.get("replays"), list):
                before = len(night["replays"])
                night["replays"] = [r for r in night["replays"]
                                    if r.get("source") in ("reading", "taught") or not blocked(str(r.get("text", "")))]
                dropped += before - len(night["replays"])
        if dropped:
            print(f"memory: {dropped} blocked messages purged", flush=True)

    def client_ip(self, request):
        """The address the rate limits and the vote's per-address cap key on. Behind the reverse proxy (--trust-proxy)
        it is the entry the proxy itself appended to X-Forwarded-For: the rightmost one. Anything before it is what the
        client sent in its own header (one hop: a client cannot choose its key by sending "X-Forwarded-For: 1.2.3.4").
        X-Real-IP, when the proxy sets it instead, is that same address. Without --trust-proxy the headers are ignored.
        A proxy chain of more than one trusted hop would need the trusted count configured; Railway adds one."""
        key = request.remote
        if self.trust_proxy:
            xff = [p.strip() for p in request.headers.get("X-Forwarded-For", "").split(",") if p.strip()]
            real = request.headers.get("X-Real-IP", "").strip()
            key = xff[-1] if xff else real or key
        return key

    def sleep_tick(self):
        """Advance the sleep engine, apply its parameters to the model, run REM replays and bursts."""
        b, e = self.brain, self.engine
        t = self.clock.now()
        out = []
        for ev in e.update(t, dt_real=TICK):
            if ev["type"] == "replay":
                m = self.memory.pick(t, e.night_start(), replayed=e.replay_counts(), avoid=e.last_replay_key())
                if m is None:
                    continue
                b.stimulate("memory", 6.0)                                   # hippocampus drives the replay
                for g, a in m["stimulus"].items():
                    b.stimulate(g, REPLAY_AMP * a)
                e.record_replay(t, m)
                src = m.get("source", "chat")
                if src == "taught":
                    m["replays"] = m.get("replays", 0) + 1                   # shown on the teach card
                if src == "reading":
                    topics = getattr(self, "read_topics", {}).get(m["text"])   # what an AI noted about it
                    text = f"{m['text']} ({', '.join(topics[:3])})" if topics else m["text"]
                    self.recent_read_replays = (self.recent_read_replays + [text])[-8:]
                else:
                    self.recent_replays = (self.recent_replays + [m["text"]])[-8:]
                out.append({"type": "replay", "t": hhmm(t), "text": m["text"], "networks": m["networks"],
                            "received": hhmm(m["t"]), "source": src})
            else:
                out.append(ev | {"t": hhmm(t)})
                if ev["type"] == "sleep":
                    self.tastes.replay()                                     # overnight replay of today's stays
                if ev.get("natural"):
                    self.store.save(e, self.memory)                          # night closed: write it now
        if self.spiking:
            self.spiking.forward_sleep(e.stage)
        p = e.params
        b.set_rhythm(p["f_hz"], p["coupling"], p["noise"])
        b.a = p["a"]
        if e.stage == "REM" and random.random() < TICK / 4.0:              # brief REM bursts (~every 4 s)
            self.burst = 1.0
            b.stimulate("relay", 4.0)
            b.stimulate("visual", 3.0)
        self.burst *= math.exp(-TICK / 0.4)
        return out

    # --- simulation loop -------------------------------------------------------
    async def run_brain(self):
        b = self.brain
        steps = int(TICK / b.dt)
        gidx = {k: v for k, v in b.group_idx.items() if v}
        next_t = last_save = time.time()
        while True:
            t0 = time.perf_counter()                                  # tick timing (#15): /healthz, /api/health
            now = time.time()
            self.tick_late = now - next_t                             # this tick's start vs its 50 ms slot (ws stats)
            events = self.sleep_tick()
            gain = {"AWAKE": 1.0, "REM": 0.7}.get(self.engine.stage, 0.3)
            if self.baseline:                                         # replaying a real recorded session (optional)
                b.drive = BASELINE_DRIVE * gain * np.clip(self.baseline.advance(TICK), -2.0, 3.0)
            else:                                                     # spontaneous slow layer fitted to his data
                b.slow_gain = gain
            due = [t for t in self.pending if t["at"] <= now]
            self.pending = [t for t in self.pending if t["at"] > now]
            for tr in due:
                self.apply(tr)
            acc = np.zeros(b.n)
            for _ in range(steps // 5):
                z = b.step(5)
                acc += np.abs(z)
            act = acc / (steps // 5)
            wave = {k: float(z.real[i].mean()) for k, i in gidx.items()}
            st = b.state()
            msg = {"type": "tick", "act": np.round(act, 3).tolist(), "wave": wave,     # (S1: no trades, counts or
                   "groups": (groups := {k: round(float(act[i].mean()), 3) for k, i in gidx.items()}),  # coin name)
                   "sync": round(st["sync"], 3), "events": events,
                   "sleep": self.engine.status() | {"burst": round(self.burst, 2)},
                   "baseline": self.baseline.status() if self.baseline else None,
                   "slow": b.slow.status() if b.slow_on else None}
            self.last_groups = groups
            base = sum(groups.values()) / max(1, len(groups))
            rel = self.last_rel = {k: v / max(base, 1e-6) for k, v in groups.items()}
            # neuromodulators x receptor maps -> regional excitability; the body -> interoceptive drive to the insula
            levels = self.neuro.update(TICK, self.engine.modulators)      # tonic levels read from the sleep circuit
            b.neuromod = NEURO_K * (self.neuro.region_gain(levels)[self.nm_idx] - 1.0)
            amyg = max(0.0, rel.get("fear", 1.0) - 1.0)
            body_levels = dict(levels, NE=min(levels["NE"], 1.5))       # the market can quicken his pulse, not race it
            self.body.update(TICK * self.time_scale, body_levels, min(amyg, 0.4), self.engine.stage,
                             exertion=self.life.exertion())
            for grp, amt in self.body.intero_drive().items():
                b.stimulate(grp, amt * TICK / 2.0)                    # settles at `amt` (stimuli decay with tau 2 s)
            hot = min(1.0, sum(1 for x in self.recent_trades if now - x[0] < 60) / 10)
            tsim = self.clock.now()
            self.life.update(tsim, TICK, TICK * self.time_scale, self.engine.stage, rel, hot,
                             self.engine.pressure(tsim))
            self.life.music = self.music.tick_view()
            msg["life"] = self.life.snapshot()
            if self.music.now:
                self.music_watch.feed(rel, now, TICK)
            msg["neuro"] = {k: round(v, 2) for k, v in levels.items()}
            if self.life.activity == "research" and not self.life.path:
                msg["life"]["reading"] = self.reading_now(tsim)
            if self.browser and (dev := self.screen_device()):
                msg["life"]["screen"] = self.screen_status(dev)
                self.pagewatch.feed(rel, now, TICK)
            await self.audience_tick(msg, tsim, rel, hot)
            await self.broadcast(msg)
            if events:
                await self.broadcast(self.nights())
            if now - last_save >= SAVE_S:
                await self.save_state()                               # written off the loop; a disk error is logged
                last_save = now
            self.tick_s.append(time.perf_counter() - t0)
            self.last_tick = time.monotonic()
            next_t += TICK
            await asyncio.sleep(max(0.0, next_t - time.time()))

    def state_files(self):
        """What the periodic save writes: [(path, object, json.dumps kwargs)]. The same files and formats as
        Store.save (state.json, nights/<date>.json) plus life.json, body.json and reading.json."""
        night = {"indent": 1, "ensure_ascii": False}
        files = [(self.store.root / "state.json", {"engine": self.engine.to_dict(), "memory": self.memory.items}, night)]
        for n in (self.engine.night, self.engine.last_night):
            if n is not None:
                files.append((self.store.root / "nights" / f"{n['date']}.json", n, night))
        files += [(self.life_path, self.life.to_dict(), {}),
                  (self.body_path, {"body": self.body.to_dict(), "neuro": self.neuro.to_dict()}, {}),
                  (self.reading_path, self.reader.to_dict(), {"ensure_ascii": False})]
        return files

    async def save_state(self):
        """The periodic save (every SAVE_S, from the brain loop): serialised on the event loop, because the objects keep
        changing under the loop, then written (tmp + fsync + rename, one file at a time) in a worker thread, so the
        20 Hz loop never waits on the volume's fsync. A full or failing disk is logged, never fatal: before this an
        OSError here ended the brain loop and with it the process (a Railway restart, a 502 window)."""
        loop = asyncio.get_running_loop()
        try:
            data = [(path, json.dumps(obj, **kw)) for path, obj, kw in self.state_files()]
            await loop.run_in_executor(None, write_json_files, data)
        except (OSError, TypeError, ValueError) as e:
            print("state: periodic save failed:", repr(e)[:160], flush=True)

    # --- the computer: what it reads -------------------------------------------------
    def wiki_fallback(self):
        """#79: Wikipedia feeds the readings only when the browser cannot: off (no playwright, BROWSE=0), or down /
        restarting for more than WIKI_FALLBACK_S."""
        if not self.browser:
            return True
        down = self.browser_down_since
        return down is not None and time.time() - down > WIKI_FALLBACK_S

    async def run_research(self):
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(5)
            t = self.clock.now()
            if self.life.activity != "research" or self.life.path or not self.reader.due(t) or not self.wiki_fallback():
                continue
            if getattr(self, "browse_wanted", False) and time.time() - getattr(self, "last_wiki_read", 0.0) < WIKI_DOWN_EVERY_S:
                continue                                        # the browser is wanted but down: Wikipedia stays rare
            self.last_wiki_read = time.time()
            art = await loop.run_in_executor(None, self.reader.read, t, self.heard(t), dict(self.last_rel))
            if art:
                art.update(host="en.wikipedia.org", kind="wiki", via="wikipedia")
                self.remember({"url": art.get("url", ""), "title": art["title"], "host": "en.wikipedia.org",
                               "text": art.get("extract", "")})
                await self.take_reading(art)

    async def take_reading(self, art):
        """A reading (a page he stayed on, or the Wikipedia fallback) becomes a stimulus and a memory, is estimated
        for tonight's replay and goes out on the feed with its host and kind."""
        loop = asyncio.get_running_loop()
        public_why(art, copy=False)                        # S4: the reason never quotes a viewer (also in the log)
        m = self.absorb_reading(art)
        if art.get("via") == "browser":
            self.reader.record(art)                        # "on his mind" and /api/reading show it
        print(f"reading ({art.get('via', 'wikipedia')}, {art.get('kind', 'wiki')}): {art['title'][:60]!r}", flush=True)
        try:
            art["tonight"] = await loop.run_in_executor(None, self.tonight_chance, m)
            art["tonight_night"] = night_date(next_bedtime(self.clock.now()))
        except Exception as e:                             # an estimate must never stop the reading
            print("research: replay estimate failed:", repr(e)[:120], flush=True)
        await self.broadcast({"type": "reading", **art})
        return m

    # --- the screens: a real browser on the open web (desk + phone) -------------------
    def screen_device(self):
        if self.life.path or self.engine.stage != "AWAKE":
            return None
        return {"research": "desk", "phone": "phone", "watch_video": "desk"}.get(self.life.activity)

    def screen_status(self, dev):
        """The public status of a screen: the browser's last status for it, or the restarting-style placeholder
        (device only) while the browser restarts and when the status must not be shown (S2: a title the card filter
        refuses, a finance / trading page)."""
        if self.browser.restarting:
            return {"device": dev, "restarting": True}
        st = public_why(self.browser.screens.get(dev))      # S4: "from chat", never the viewer's words
        dec = self.decisions.get(dev)
        if st and not screen_showable(st):                   # S2: a refused title or a finance page: the placeholder
            return {"device": dev, "restarting": True}        # (device only: no title, url, id or screenshot)
        if st and (m := screens.TIKTOK_ID.search(str(st.get("url") or ""))):     # #89: viewers may play it in
            st = dict(st, embed={"src": screens.TIKTOK_EMBED.format(m.group(1)),     # TikTok's official player
                                 "label": "TikTok (official embed)"})
        elif st and (m := screens.YT_ID.search(str(st.get("url") or ""))):        # ... or YouTube's
            import youtube_api
            st = dict(st, embed={"src": youtube_api.viewer_embed(m.group(1)), "label": "YouTube (official embed)"})
        # the options belong to the page they were considered on and to the page the choice led to, no later one
        if st and dec and (st.get("url") == dec.get("page_url") or st.get("id") == dec.get("status_id")
                           or (st.get("video") and st.get("url") == dec.get("led_to"))):   # a chosen video playing
            st = dict(st, decision={k: dec.get(k) for k in ("options", "reason", "eyes", "ms", "temperature", "page",
                                                            "outcome", "watch_min")})
        return st

    async def run_browse(self):
        """Drive the screens through the browser service; if it is down the brain and the page carry on."""
        idle_since, last_save, last_sync, ready, open_dev = time.time(), time.time(), time.time(), False, None
        fails = 0                                               # consecutive outages: the restart backoff (#89)
        while True:
            await asyncio.sleep(1)
            dev = self.screen_device()
            now = time.time()
            try:
                if dev is None:
                    if (sc := getattr(self, "screens", None)) is not None:
                        sc.idle("he is not at a screen (asleep or away): the browser starts when he picks one up")
                    if open_dev and now - idle_since > 120:     # put away: the service frees the memory
                        self.end_page()
                        br = getattr(self, "browse_readings", None)
                        if br and (art := br.flush(self.clock.now())):
                            await self.take_reading(art)
                        await self.browser.close()
                        open_dev = None
                    continue
                idle_since = now
                if self.local_browser:
                    proc = await self.local_browser.ensure()
                    if proc == "down":
                        raise BrowserDown("browser process did not start")
                    if proc != "ok":                            # a new process: give it the saved log again
                        ready, open_dev = False, None
                        self.end_page()
                if not ready:
                    await self.browser.init(self.local_browser.init_state(self.browsing_state) if self.local_browser
                                            else self.browsing_state)   # #89: with the pages that blew the cap
                    ready = True
                    await self.sync_browsing()                  # #89: searches / accounts known right away
                if open_dev and open_dev != dev:
                    self.end_page()
                    await self.browser.close(open_dev)
                open_dev = dev
                t = self.clock.now()
                art = self.reader.current()
                interest = live_interest(self, art, self.search_rng)   # #56: notes, reading, taught words, tastes
                mode = "video" if self.life.activity == "watch_video" else None
                d = await self.browser.step(dev, self.heard(t), interest, mode)
                st = await self.decide(dev, d["decide"], interest) if d.get("decide") else d.get("status")
                if st and (st.get("video") or {}).get("watching"):
                    self.video_drive(st["video"])
                self.browser_down_since = None
                fails = 0
                if st:
                    await self.on_screen(st)                    # #89: the screens status and the dopamine-like burst
                    self.reader.saw(st, t)                      # #56: "on his mind" is what he is actually reading
                    br = getattr(self, "browse_readings", None)
                    if br and (art := br.seen(st, t)):          # #79: a page he stayed on becomes the reading
                        await self.take_reading(art)
                if st:
                    await self.broadcast({"type": "screen", **self.screen_status(dev)})
                if now - last_sync > 30:                        # the log shown on /api/browsing stays fresh
                    await self.sync_browsing()
                    last_sync = now
                if now - last_save > 300:
                    save_json(self.browsing_path, self.browsing_state, ensure_ascii=False)
                    last_save = now
            except BrowserDown as e:
                if getattr(self, "browser_down_since", None) is None:
                    self.browser_down_since = time.time()       # Wikipedia takes over after WIKI_FALLBACK_S
                if br := getattr(self, "browse_readings", None):
                    br.flush(self.clock.now())
                if (sc := getattr(self, "screens", None)) and sc.browser_down(e):
                    print("browser down:", e, "(restarting with backoff)", flush=True)   # once per outage
                if not self.browser.restarting:
                    self.browser.restarting = True
                    if dev:
                        await self.broadcast({"type": "screen", "device": dev, "restarting": True})
                self.end_page()
                ready, open_dev = False, None
                fails = min(fails + 1, 5)
                await asyncio.sleep(min(120, 5 * 2 ** (fails - 1)))   # 5, 10, 20, 40, 80 s

    async def on_screen(self, st):
        """#89: a screen status updates the screens status; a new clip or page gives a dopamine-like burst (novelty +
        predicted interest - expectation, habituating over a scroll session) that drives the reward regions."""
        sc = getattr(self, "screens", None)
        if sc is None:
            return None
        kind = sc.seen(st)
        note = getattr(self.browser, "feed_note", None)
        if note:
            sc.note(note)
        if kind and time.time() - getattr(self, "screens_saved", 0.0) > SCREENS_SAVE_S:
            self.save_screens()
        da = getattr(self, "da_bursts", None)
        if not kind or da is None:
            return None
        import interests
        title = str(st.get("title") or "")
        topic = interests.topic_of(title, st.get("host", "")) or (
            "video:" + novelty.title_key(title) if kind in ("shorts", "tiktok", "youtube") else st.get("host"))
        try:
            interest = self.tastes.predict(Tastes.topics({"label": title, "networks": {}}, ""))
        except Exception:
            interest = 0.0
        b = da.on_new(kind, topic, interest)
        if not b or b["size"] <= 0:
            return b
        gain = self.engine.gain
        self.neuro.burst(DA_BURST_K * b["size"])
        cpu = getattr(getattr(self, "decider", None), "cpu", None)
        if cpu is not None and hasattr(cpu, "burst"):          # the neurons panel's dopamine reading moves too
            cpu.burst(min(1.0, b["size"]))
        self.brain.stimulate("reward", DA_REWARD * b["size"] * gain)
        await self.broadcast({"type": "dopamine", "size": b["size"], "rpe": b["rpe"], "novelty": b["novelty"],
                              "interest": b["interest"], "expect": b["expect"], "n": b["n"], "kind": kind,
                              "habituation": b["habituation"], "why": b["label"], "label": DA_LABEL,
                              "da": round(self.neuro.levels["DA"], 3)})
        return b

    def save_screens(self):
        """#89: /api/screens' counts, last pages and notes, kept across deploys (a small file, at most every minute)."""
        sc, path = getattr(self, "screens", None), getattr(self, "screens_path", None)
        if sc is None or path is None:
            return
        try:
            save_json(path, sc.to_dict(), ensure_ascii=False)
            self.screens_saved = time.time()
        except OSError as e:
            print("screens: could not save:", repr(e)[:120], flush=True)

    def screens_view(self):
        """GET /api/screens: the browser up/down and why, the last 10 pages with kind and host, today's share by kind,
        the feed's notes, and the recent dopamine-like bursts."""
        out = self.screens.public(card_title_ok)
        out["dopamine"] = {"label": DA_LABEL, "bursts": [{"t": round(b["t"]), "size": b["size"], "kind": b["kind"],
                                                         "n": b["n"]} for b in self.da_bursts.trace[-60:]],
                           "da": round(self.neuro.levels["DA"], 3)}
        out["sources"] = self.browsing_sources()
        out["youtube"] = self.youtube_view()                  # key set? units today (also while the browser idles)
        out["feeds"] = {site: {k: d.get(k) for k in ("t", "reason", "video_links", "captcha", "login_prompt")}
                        for site, d in (getattr(self.browser, "diag", None) or {}).items()} if self.browser else {}
        out["music"] = self.music_line()
        return out

    def browsing_view(self):
        """GET /api/browsing: the pages shown, searches per source, accounts. #89: before the browser process has
        reported (it starts only when he picks up a screen, so after a redeploy while he sleeps it had not), the
        counts saved with the browsing log and the accounts read here, with synced: false; they were null."""
        if not self.browser:
            return {"on": False, "log": [], "searches": None, "accounts": None, "synced": False, "browser": None}
        log = self.browser.log or self.browsing_state.get("log", [])
        searches = getattr(self.browser, "searches", None)
        accounts = getattr(self.browser, "accounts", None)
        synced = searches is not None
        if searches is None and (st := self.browsing_state.get("searches")):
            searches = dict(search_sources.Limits(state=st).public(),
                            variety=interests.Variety(state=st.get("variety")).public())
        if accounts is None:
            accounts = local_accounts()
        sc = getattr(self, "screens", None)
        return {"on": True, "log": log[-30:], "searches": searches, "accounts": accounts, "synced": synced,
                "browser": sc.public()["browser"] if sc else None}

    def youtube_view(self):
        """The YouTube Data API's state for /api/screens: from the browser process when it has reported, else from the
        saved browsing state and this process's environment (key set or not, units used today, errors)."""
        v = getattr(self.browser, "youtube", None) if self.browser else None
        if v:
            return v
        import youtube_api
        return youtube_api.Quota(state=(getattr(self, "browsing_state", None) or {}).get("youtube")).public()

    def browsing_sources(self):
        """Search sources set aside after repeated failures (#89), from the browser or the saved state."""
        sv = getattr(self.browser, "searches", None) if self.browser else None
        if sv is None:
            st = (getattr(self, "browsing_state", None) or {}).get("searches")
            sv = search_sources.Limits(state=st).public() if st else {}
        return {"blocked": [dict(v, source=k, until=screens.hhmm(v["until"]))
                            for k, v in (sv.get("blocked") or {}).items()]}

    def music_line(self):
        """#89: what he is listening to, with the official Spotify embed, and where the tracks come from."""
        m = getattr(self, "music", None)
        if m is None:
            return None
        now = m.public(m.now)
        api = None if not m.api else ("down: " + m.api_down if m.api_down else "ok")
        src = ("Spotify keys not set: playing from the curated list" if api is None else
               f"Spotify search {api}: playing from the curated list" if api != "ok" else "Spotify")
        return {"now": {k: now.get(k) for k in ("title", "artist", "embed", "embed_height", "url", "why")} if now
                else None, "source": src, "label": "Spotify (official embed)"}

    def video_drive(self, video):
        """While he watches a video: the change between the last two screenshots drives the visual network (no
        audio: the video is muted). Scaled like every stimulus by the sleep engine's gain."""
        try:
            scene = min(1.0, max(0.0, float(video.get("scene") or 0.0)))
        except (TypeError, ValueError):
            return 0.0
        amp = VIDEO_DRIVE * scene * self.engine.gain
        if amp > 0:
            self.brain.stimulate("visual", amp)
        return amp

    async def sync_browsing(self):
        s = await self.browser.state()
        if s.get("log") or not self.browsing_state.get("log"):
            self.browsing_state = {"log": s.get("log", []), "used": s.get("used", []), "searches": s.get("searches"),
                                   "visited": s.get("visited") or self.browsing_state.get("visited"),
                                   "youtube": s.get("youtube_state") or self.browsing_state.get("youtube"),
                                   "heavy": s.get("heavy") or self.browsing_state.get("heavy"),
                                   "walled": s.get("walled") or self.browsing_state.get("walled")}

    def end_page(self):
        """He leaves the page: its measured brain response updates his tastes."""
        res = self.pagewatch.finish()
        delta = self.tastes.learn(*res) if res else None
        if getattr(self, "decider", None):                    # the stay's prediction error = its dopamine (#55)
            self.decider.outcome(res[1] if res else None, delta)

    def novel(self, option):
        return option["action"] in NOVEL_ACTIONS and time.time() - self.targets.get(target_key(option), 0) > 7 * 86400

    async def decide(self, dev, page, interest=None):
        """The eyes list options for the page; the brain model votes; the browser carries the choice out."""
        loop = asyncio.get_running_loop()
        try:
            if br := getattr(self, "browse_readings", None):           # the excerpt of a later reading (#79)
                br.text(page.get("url"), page.get("text"))
            opts, meta = await asyncio.wait_for(loop.run_in_executor(None, self.eyes.propose, page, interest), 60)
        except asyncio.TimeoutError:                           # the AI is too slow: the page's own links
            from eyes import local_options
            opts, meta = local_options(page, interest), {"source": "local", "why_local": "AI too slow"}
        if getattr(self, "mind", None):
            self.remember(page)                                # an AI notes what the page says (off the loop)
        if not opts:
            return await self.browser.act(dev, {"action": "leave"}, "nothing safe to do on this page", interest)
        try:
            return await self._vote_and_act(dev, page, opts, meta, interest)
        except BrowserDown:
            raise
        except Exception as e:                                 # a failing vote must not stall the screens
            print("decide failed:", repr(e)[:160], flush=True)
            return await self.browser.act(dev, {"action": "leave"}, "the brain vote failed; wandered on", interest)

    async def _vote_and_act(self, dev, page, opts, meta, interest):
        loop = asyncio.get_running_loop()
        t = self.clock.now()
        mood = {"boredom": self.life.boredom, "pressure": self.engine.pressure(t), "tired": self.engine.tired}
        gain = self.engine.gain
        topics = [Tastes.topics(o, page.get("title", "")) for o in opts]
        here = (self.pagewatch.cur or {}).get("topics")        # the page he is on: its taste is the leave row's (negated there)
        tastes = [self.tastes.predict(here if here and o.get("action") == "leave" else tp, vote=True)
                  for o, tp in zip(opts, topics)]
        recent = list(getattr(self, "recent_picks", None) or [])   # repeat_key of the last choices: the repeat penalty
        clone = self.brain.clone()                            # snapshot on the event loop, simulated in a thread
        decider = getattr(self, "decider", None)
        sp = await decider.ask([o["label"] for o in opts], "browse") if decider else None   # GPU, else CPU, <= ~3.5 s
        dec = await loop.run_in_executor(None, lambda: brain_vote.vote(
            clone, opts, gain, mood, tastes, [self.novel(o) for o in opts], self.vote_rng, spiking=sp, recent=recent))
        chosen = opts[dec["chosen"]]
        self.recent_picks = (recent + [brain_vote.repeat_key(chosen)])[-brain_vote.REPEAT_N:]
        brain_vote.apply(self.brain, chosen, gain)             # the live brain receives the chosen stimulus
        act = {k: chosen.get(k) for k in ("action", "target", "label", "href")}
        if chosen.get("action") in brain_vote.VIDEO_ACTIONS:     # how long he watches: boredom + the brain's response
            mins = brain_vote.watch_minutes(mood["boredom"], dec["options"][dec["chosen"]]["value"])
            act["watch_s"] = mins * 60 / max(1e-6, self.time_scale)
            dec["watch_min"] = mins
        self.end_page()
        self.pagewatch.start(topics[dec["chosen"]], time.time())
        if decider:
            decider.followed(sp, dec["chosen"], [o["label"] for o in opts], "browse")
        now = time.time()
        self.targets = {k: v for k, v in self.targets.items() if now - v < 7 * 86400}
        self.targets[target_key(chosen)] = now
        title = page.get("title", "")[:120]
        dec.update(device=dev, t=hhmm(t), page=title if card_title_ok(title, page.get("host", "")) else page.get("host", ""), eyes=meta,
                   page_url=page.get("url"))
        self.decisions[dev] = dec
        self.decision_log = (self.decision_log + [dec])[-30:]
        await self.broadcast({"type": "decision", **dec})
        st = await self.browser.act(dev, act, dec["reason"], interest)
        dec["status_id"] = (st or {}).get("id")
        dec["led_to"] = (st or {}).get("url")
        dec["outcome"] = self.outcome(chosen, st)
        return st

    @staticmethod
    def outcome(chosen, st):
        """What the chosen action led to, said plainly on the card: the voted page, a redirect, or not shown."""
        import urllib.parse
        if not st:
            return "could not be carried out"
        if st.get("missed"):
            return st["missed"]
        href = chosen.get("href")
        if href and st.get("url") and st["url"].split("#")[0] != href.split("#")[0]:
            host = urllib.parse.urlsplit(st["url"]).hostname or ""
            return f"redirected to {host.removeprefix('www.')}"
        return "opened" if href else "done"

    # --- chess at the desk (#17): his brain model picks among the scorer's 5 candidate moves --------------------------
    def chess_view(self):
        """GET /api/chess: the game on the board (or the last one), recent games, what the card says."""
        g = self.chess.public() if self.chess else self.chess_last
        return {"playing": self.chess is not None, "game": g, "games": tail_jsonl(self.chess_path, 10)[::-1],
                "card": chess_game.CARD, "note": chess_game.NOTE}

    def chess_pace(self, his):
        lo, hi = CHESS_THINK_S if his else CHESS_REPLY_S
        return max(CHESS_MIN_GAP_S, self.chess_rng.uniform(lo, hi) / max(1e-6, self.time_scale))

    async def run_chess(self):
        while True:
            await asyncio.sleep(0.25 if self.life.activity == "play_chess" else 1.0)
            await self.chess_step()

    async def chess_step(self):
        """One step of the game while he sits at the desk to play: a new game, his move (the brain vote, in a worker
        thread), the opponent's move (depth-2 search, in a worker thread), or the end of the game."""
        loop = asyncio.get_running_loop()
        t = self.clock.now()
        playing = self.life.activity == "play_chess" and not self.life.path and self.engine.stage == "AWAKE"
        g = self.chess
        if g is None:
            if playing:
                level = chess_game.level_for(tail_jsonl(self.chess_path, chess_game.LEVEL_GAMES))   # W/D/L-tuned
                g = self.chess = chess_game.Game(t, rng=self.chess_rng, level=level)
                g.next_at = time.time() + self.chess_pace(g.his_turn)
                await self.broadcast({"type": "chess", **g.public()})
            return
        if not playing:
            g.stop("he got up")
            return await self.finish_chess(g, t)
        if g.over:
            return await self.finish_chess(g, t)
        if self.life.until - t < 120 and t - g.started < CHESS_MAX_S:
            self.life.until = t + 120                           # a game in progress keeps him at the desk
        if time.time() < g.next_at:
            return
        if g.his_turn:
            opts = await loop.run_in_executor(None, g.candidates)
            mood = self.mood(t)
            gain = self.engine.gain
            clone = self.brain.clone()                          # snapshot on the event loop, simulated in a thread
            dec = await loop.run_in_executor(None, lambda: brain_vote.vote(clone, opts, gain, mood,
                                                                             rng=self.chess_vote_rng))
            if self.chess is not g or g.over:
                return
            chosen = opts[dec["chosen"]]
            brain_vote.apply(self.brain, chosen, gain)          # the live brain receives the chosen move's stimulus
            san = g.push(chosen["target"])
            g.votes.append({"move": san, "reason": dec["reason"], "ms": dec["ms"], "temperature": dec["temperature"],
                            "options": [{"label": o["label"], "score": c["score"], "p": o["p"], "value": o["value"],
                                         "networks": o["networks"], "chosen": o["chosen"]}
                                        for o, c in zip(dec["options"], opts)]})
        else:
            m = await loop.run_in_executor(None, g.opponent)
            if self.chess is not g or g.over or m is None:
                return
            g.push(m)
        g.next_at = time.time() + self.chess_pace(g.his_turn)
        await self.broadcast({"type": "chess", **g.public()})
        if g.over:
            await self.finish_chess(g, t)

    async def finish_chess(self, g, t):
        """The game is over (or he got up): one row in chess.jsonl; he leaves the board."""
        if self.chess is not g:
            return
        self.chess, self.chess_last = None, g.public()
        try:
            append_jsonl(self.chess_path, g.record(t))
        except OSError as e:
            print("chess: could not log the game:", repr(e)[:120], flush=True)
        if self.life.activity == "play_chess":
            self.life.end_activity(t)
        await self.broadcast({"type": "chess", **self.chess_last, "finished": True})
        await self.apply_held_vote(t)                           # L4: a vote held during the game is applied now

    async def apply_held_vote(self, t):
        """A vote result waiting while he played chess (audience_tick holds it: votes never cut a game, L4) becomes
        his nudge once the game is over, when he is awake and the activity is possible."""
        v = getattr(self, "votes", None)
        p = v.pending if v else None
        if not p:
            return
        ok = self.engine.stage == "AWAKE" \
            and self.life.scores(t, self.last_rel, 0.0, self.engine.pressure(t)).get(p["act"], 0.0) > 0
        got = v.take_pending(t, ok)
        if got and self.life.apply_vote(got["act"], t):
            await self.broadcast({"type": "vote_applied", "act": got["act"], "label": got["label"],
                                  "round": got["round"], "t": hhmm(t)})

    # --- music (#68): his brain model picks among 3-5 candidate tracks; the pages show Spotify's own embed ------------
    def music_context(self, t):
        """His tastes, words taught in the last 2 days and what he has been reading about: they tilt the genres."""
        fav = [f["topic"] for f in self.tastes.top(8)["favoured"] if f["kind"] == "word"]
        taught = [m["text"] for m in self.memory.items if m.get("source") == "taught" and t - m["t"] < 2 * 86400]
        interests = [i.get("query", "") for i in (self.interest[1] or []) if isinstance(i, dict)]
        return fav, taught[-10:], interests

    async def run_music(self):
        while True:
            await asyncio.sleep(1.0)
            await self.music_step()

    async def music_step(self):
        """Start, end or change his track: in the listen_music activity, or now and then in the background while he
        reads, plays chess, sits in the park or walks outside."""
        t = self.clock.now()
        life, now = self.life, self.music.now
        awake = self.engine.stage == "AWAKE"
        listening = awake and life.activity == "listen_music" and not life.path
        started = life.started[-1] if life.started else None
        if self.music_bg[0] != started:                         # a new activity: is there music in the background?
            self.music_bg = (started, self.music_rng.random() < MUSIC_BG_P)
        bg = awake and self.music_bg[1] and life.music_bg_ok()
        if now:
            ends = self.music.ends()
            if not awake:
                return await self.music_stop(t, "fell asleep")
            if now["mode"] == "activity" and not listening:
                return await self.music_stop(t, "took the headphones off")
            if now["mode"] == "background" and not bg and not listening:
                return await self.music_stop(t, "stopped the music")
            if t < ends:
                return
            await self.music_stop(t, "the track ended")
            if not listening:
                if self.music_rng.random() >= MUSIC_NEXT_P:
                    self.music_bg = (started, False)
                return
        if listening:
            await self.music_pick(t, "activity")
        elif bg:
            await self.music_pick(t, "background")

    async def music_pick(self, t, mode):
        if self.music_busy:
            return
        self.music_busy = True
        try:
            loop = asyncio.get_running_loop()
            ctx = self.music_context(t)
            tracks = await loop.run_in_executor(None, lambda: self.music.candidates(t, *ctx))
            if not tracks or self.music.now:
                return
            opts = self.music.options(tracks)
            topics = [self.music.topics(o, x) for o, x in zip(opts, tracks)]
            tastes = [self.tastes.predict(tp) for tp in topics]
            novel = [self.music.novel(x["id"]) for x in tracks]
            gain, mood, clone = self.engine.gain, self.mood(t), self.brain.clone()
            dec = await loop.run_in_executor(None, lambda: brain_vote.vote(clone, opts, gain, mood, tastes, novel,
                                                                             rng=self.music_vote_rng))
            if not dec or self.music.now:
                return
            k = dec["chosen"]
            brain_vote.apply(self.brain, opts[k], gain)          # the live brain receives the chosen track's stimulus
            pub = self.music.play(tracks[k], dec, self.clock.now(), mode)
            self.music_watch.start(topics[k], time.time())
            if getattr(self, "mind", None):                      # the mind's day notes (and so the diary) know it
                try:
                    self.mind.memory.add("music", summary=f"listened to “{pub['title']}” by {pub['artist']}"[:200],
                                         topics=[pub["genre_label"]] if pub.get("genre_label") else [])
                except Exception as e:
                    print("music: mind note failed:", repr(e)[:120], flush=True)
            await self.broadcast({"type": "music", "playing": True, **pub})
        finally:
            self.music_busy = False

    async def music_stop(self, t, why):
        res = self.music_watch.finish()
        response = None
        if res:
            self.tastes.learn(*res)                              # the stay response: his music taste forms over days
            response = res[1]
        row = self.music.stop(t, why, response)
        if row:
            await self.broadcast({"type": "music", "playing": False, "ended": why, "id": row["id"]})

    # --- the mind: an AI reads and remembers for him; his brain model chooses (mind.py) ---------------
    def encoding(self):
        """The brain's response at encoding (importance of a memory): reward / attention / fear vs their mean."""
        rel = self.last_rel
        return {g: rel.get(g, 1.0) - 1.0 for g in ("reward", "attention", "fear")}

    def remember(self, page):
        """mind.read(page) in a worker thread, in the background: neither the browsing nor the brain loop waits."""
        if not self.mind or not page.get("title"):
            return
        page = {k: page.get(k, "") for k in ("url", "title", "host", "text")}
        # C2: with messages waiting and few hourly calls left, the page gets a keyword trace, the call is kept for chat
        ai = not (self.chat_inbox and self.mind.calls_left() <= CHAT_RESERVE)
        task = asyncio.get_running_loop().create_task(self._remember(page, self.encoding(), ai))
        self.bg.add(task)
        task.add_done_callback(self.bg.discard)

    async def _remember(self, page, brain, ai=True):
        try:
            it = await asyncio.get_running_loop().run_in_executor(None, lambda: self.mind.read(page, brain, ai=ai))
        except Exception as e:                                   # notes are optional: never stop the screens
            print("mind: read failed:", repr(e)[:120], flush=True)
            return
        if not it:
            return
        if it.get("topics") and page["title"]:
            self.read_topics[page["title"]] = it["topics"]
            while len(self.read_topics) > 200:
                self.read_topics.pop(next(iter(self.read_topics)))
        if it.get("summary"):
            await self.broadcast({"type": "mind_read", "t": hhmm(it["t"]), "summary": it["summary"],
                                  "topics": it.get("topics", []), "host": it.get("host", ""),
                                  "tag": "notes written by an AI"})

    def mood(self, t):
        return {"boredom": self.life.boredom, "pressure": self.engine.pressure(t), "tired": self.engine.tired}

    def mind_interest(self):
        """1-3 searches linking what he read recently (mind.next_interest), refreshed every minute; the first one is
        the browser's interest. None without notes yet."""
        if not self.mind:
            return None
        now = time.time()
        if now - self.interest[0] > 60:
            t = self.clock.now()
            got = self.mind.next_interest(self.mind.taste_view(self.tastes), {"mood": self.mood(t)})
            self.interest = (now, got)
        got = self.interest[1]
        return got[0]["query"] if got else None

    def mind_view(self):
        """GET /api/mind: the plan, the latest notes and replies, the shared AI budget."""
        m = self.mind
        if not m:
            return {"on": False, "caption": mind_mod.CAPTION}
        notes = m.public_notes()
        for k in notes:
            for x in notes[k]:
                x["t"] = hhmm(x["t"])
        return {"on": True, "caption": mind_mod.CAPTION, "status": m.status(), "plan": m.plan_public(),
                "interests": self.interest[1] or [], "notes": notes, "replies": self.replies[-10:],
                "budget": m.budget.summary(), "reply_tag": "his reply (AI-written)",
                "note": "An AI writes notes on what he reads, proposes day plans and writes his chat replies; his brain "
                        "model votes among the plans. It does not understand what it reads."}

    async def run_mind(self):
        """Off the brain loop: the day plan (each Tokyo morning, revised at noon and in the evening, voted by a clone
        of the brain), the plan as a hint to life.py, and chat replies while he is at the computer."""
        self.mind_seen = self.clock.now()
        while True:
            await asyncio.sleep(2)
            await self.mind_step()

    async def mind_step(self):
        loop = asyncio.get_running_loop()
        m = self.mind
        t = self.clock.now()
        awake = self.engine.stage == "AWAKE"
        seen = getattr(self, "mind_seen", 0.0)
        hint = self.life.plan_hint
        for ts, act in list(self.life.started):            # plan steps he carried out (only a start that was the hint)
            if ts > seen:
                m.life_started(act, hint)
                seen = ts
        self.mind_seen = seen
        if awake and m.due_slot(t):
            state = {"mood": self.mood(t), "gain": self.engine.gain, "chat": True, "chess": True,
                     "bread": self.life.bread, "chat_waiting": len(self.chat_inbox)}
            clone, view = self.brain.clone(), m.taste_view(self.tastes)    # snapshots on the event loop
            try:
                await loop.run_in_executor(None, lambda: m.plan_day(state, clone, view, self.plan_rng))
                await self.broadcast({"type": "plan", **(m.plan_public() or {})})
            except Exception as e:
                print("mind: plan failed:", repr(e)[:160], flush=True)
        pressure = self.engine.pressure(t)
        scores = self.life.scores(t, self.last_rel, 0.0, pressure) if awake else None     # P1: feasible steps only
        nxt = m.next_step({"hunger": self.life.hunger, "pressure": pressure}, scores)
        self.life.plan_hint = nxt["life"] if nxt else None
        # the inbox (C1/C2): he sits down to answer only when a reply is possible; every message gets an outcome
        life = self.life
        at_desk = not life.path and (life.activity == "chat"
                                     or (life.activity in ("research", "watch_video") and life.place == "desk"))
        open_why = m.reply_open()
        if self.chat_inbox and open_why and "replies today" in open_why:      # the day's cap: the inbox is cleared
            day = day_of(t)
            if self.cap_noted != day:
                self.cap_noted = day
                rec = {"t": hhmm(t), "text": CAP_LINE, "to": "everyone", "replying_to": "",
                       "tag": "a note from the room, not his words", "source": "note"}
                self.replies = (self.replies + [rec])[-30:]
                await self.broadcast({"type": "chat_reply", **rec})
            for x in list(self.chat_inbox):
                await self.chat_missed(x, "he has answered 40 messages today; back tomorrow")
        for x in list(self.chat_inbox):
            if t - x["t"] > CHAT_WAIT_S and not (awake and at_desk):
                await self.chat_missed(x, "he missed that one: it waited too long")
        life.chat_waiting = len(self.chat_inbox) if awake and open_why is None else 0
        if self.chat_inbox and awake and at_desk:
            item = self.next_message(t)                             # peek: popped only on a posted reply
            ctx = {"awake": True, "at_desk": True, "mood": self.mood(t), "doing": self.doing_now(t),
                   "brain": self.encoding(), "viewer": item["key"]}
            try:
                r = await loop.run_in_executor(None, m.reply, item["text"], item["nick"] or None, ctx)
            except Exception as e:
                print("mind: reply failed:", repr(e)[:160], flush=True)
                r = {"reply": None, "why": "no AI reply", "source": None}
            if r["reply"]:
                if item in self.chat_inbox:
                    self.chat_inbox.remove(item)
                self.chat_served[item["key"]] = t
                while len(self.chat_served) > 200:
                    self.chat_served.pop(next(iter(self.chat_served)))
                rec = {"t": hhmm(self.clock.now()), "text": r["reply"], "to": item["nick"] or "a viewer",
                       "replying_to": item["text"], "tag": "his reply (AI-written)", "source": r["source"]}
                self.replies = (self.replies + [rec])[-30:]
                await self.broadcast({"type": "chat_reply", **rec})
            elif r["why"] == "no AI reply":                         # transient: one more try, then a visible miss
                item["tries"] += 1
                if item["tries"] >= 2:
                    await self.chat_missed(item, "his reply did not come (the AI did not answer)")
            elif r["why"].startswith("message blocked"):
                await self.chat_missed(item, "the chat filter kept it")
            # else: it waits (the 2-min gap, the rule gap, the budget): chat_waiting says whether he will come back

    # --- the eye: what SUB-01 "sees" ----------------------------------------------
    async def run_eye(self):
        loop = asyncio.get_running_loop()
        while True:
            t = self.clock.now()
            if self.diary and (date := self.diary.pending_close(self.engine)):      # morning: write last night's entry
                try:
                    tok = os.environ.get("REPLICATE_API_TOKEN")
                    llm = self.eye.llm or (ReplicateLLM(tok) if tok else None)
                    if isinstance(llm, ReplicateLLM):                 # paid: capped and logged as "diary"
                        why = self.ledger.why_not("diary")
                        if why:
                            print(f"diary: {why}; template text", flush=True)
                        llm = None if why else costs.MeteredLLM(llm, self.ledger, "diary")
                    read = [{"title": m["text"], "url": m.get("url", ""), "host": m.get("host", ""),
                             "kind": m.get("kind", "wiki")} for m in self.memory.items
                            if m.get("source") == "reading" and day_of(m["t"]) == date]
                    notes = dict(self.mind.day_notes(date)) if getattr(self, "mind", None) else {}
                    notes["music"] = self.music.day(date)                       # what his brain model picked (#68)
                    await loop.run_in_executor(None, self.diary.close, self.engine.last_night, llm, read, notes)
                    print(f"diary: night of {date} written", flush=True)
                except Exception as e:
                    print("diary error:", repr(e), flush=True)
            attended = bool(self.clients)
            dream = bool(self.diary) and not attended and self.diary.due(self.engine, t)
            if not attended and not dream:                            # nobody watching and no dream due: spend nothing
                await asyncio.sleep(5)
                continue
            stage = self.engine.stage
            if stage == "AWAKE" and (self.recent_replays or self.recent_read_replays):
                self.recent_replays, self.recent_read_replays = [], []   # dreams end when it wakes up
            if os.environ.get("REPLICATE_API_TOKEN") and (why := self.ledger.why_not("eye")):
                await self.rest_eye(why)                              # over a daily cap: keep the last frame
                await asyncio.sleep(60)
                continue
            try:
                rec = await loop.run_in_executor(None, self.eye.step, t, stage, self.last_groups,
                                                 market_mood(self.recent_trades), list(self.recent_replays), hhmm(t),
                                                 self.life.snapshot()["doing"], list(self.recent_read_replays))
                self.last_frame, self.eye_resting = rec, None
                await self.broadcast({"type": "eye", **rec})
                if self.diary and stage == "REM" and self.engine.night is not None:
                    self.diary.add(self.engine.night["date"], rec, t, attended)
            except costs.Capped as e:                                 # a cap reached between two calls
                await self.rest_eye(str(e))
                await asyncio.sleep(60)
                continue
            except Exception as e:                                    # never let the eye stop the brain
                print("eye error:", repr(e), flush=True)
                await asyncio.sleep(10)
            if dream:
                await asyncio.sleep(5)                                # unattended: the diary paces itself
                continue
            await asyncio.sleep(self.eye_every * {"AWAKE": 1.0, "REM": 0.75}.get(stage, 3.0))

    async def rest_eye(self, why):
        """Over a daily cap the eye keeps its last frame and the pages say it is resting its eyes (never an error)."""
        if self.eye_resting == why:
            return
        print(f"eye: {why}; resting its eyes", flush=True)
        self.eye_resting = why
        if self.last_frame:
            await self.broadcast({"type": "eye", **self.last_frame, "resting": RESTING})

    def eye_frame(self):
        return {"type": "eye", **self.last_frame, **({"resting": RESTING} if self.eye_resting else {})}

    # --- health (#15) ----------------------------------------------------------
    def healthy(self):
        """/healthz: the brain loop finished a tick in the last HEALTHY_S seconds."""
        return self.last_tick is not None and time.monotonic() - self.last_tick < HEALTHY_S

    def health(self):
        """GET /api/health (admin): tick time, loop lag, memory, sockets, Chromium, last diary / memory test, spend."""
        pct = lambda xs, p: round(1000 * xs[min(len(xs) - 1, int(p * len(xs)))], 2) if xs else None
        ticks = sorted(self.tick_s)
        late = sorted(max(0.0, x) for x in self.ws_stats["late"][-TICK_RING:])
        b = self.browser
        chromium = {"on": False}
        if b is not None:
            chromium = {"on": True, "separate_service": self.local_browser is None,
                        "restarting": bool(getattr(b, "restarting", False)), "failures": getattr(b, "failures", 0)}
            if self.local_browser is not None:
                chromium.update(alive=self.local_browser.alive(), restarts=self.local_browser.restarts,
                                restart_log=list(getattr(self.local_browser, "restart_log", []))[-10:],
                                mem_limit_mb=getattr(self.local_browser, "mem_mb", None),
                                heavy=self.local_browser.heavy.public() if hasattr(self.local_browser, "heavy") else None)
        nights = self.diary.index(1) if self.diary else []
        tests = tail_jsonl(self.data_dir / "spiking" / "memory_tests.jsonl", 1)
        return {"ok": self.healthy(),
                "last_tick_s_ago": round(time.monotonic() - self.last_tick, 3) if self.last_tick else None,
                "tick_ms": {"p50": pct(ticks, 0.5), "p95": pct(ticks, 0.95), "max": round(1000 * ticks[-1], 2) if ticks
                            else None, "n": len(ticks), "budget": 1000 * TICK},
                "loop_lag_ms": {"p50": pct(late, 0.5), "p95": pct(late, 0.95), "n": len(late)},
                "rss_mb": rss_mb(), "websockets": len(self.sockets), "chromium": chromium,
                "eye": {"on": bool(self.eye), "resting": self.eye_resting},
                "last_diary": nights[0]["date"] if nights else None,
                "last_memory_test": tests[-1].get("test_day") if tests else None,
                "spend_today": {k: round(v, 4) for k, v in self.ledger.by_day(1).popitem()[1].items()}}

    # --- viewers: the vote on what he does next, the reactions (preview/interactive, audience.py) ----------------
    async def audience_tick(self, msg, tsim, rel, hot):
        """Each brain tick: the viewer count and the vote's counts go in the tick, the reactions since the last tick too;
        a round that ends hands its winner to his activity model (when he is awake and it is possible), a new round
        opens, while he is awake, with what his model allows now and at its end minus what he is doing already; the
        page hears `vote_applied` when the voted activity actually begins (not when the nudge is set); a spike of
        reactions makes him glance at the camera."""
        v = self.votes
        now = v.clock()
        awake = self.engine.stage == "AWAKE"
        if v.due(now):
            res = v.close(tsim)
            if res:
                await self.broadcast({"type": "vote_result", **res})
            opts = []
            if awake:                                            # asleep: no round (it would only wait for morning)
                pressure = self.engine.pressure(tsim)
                end = tsim + v.round_s * self.time_scale
                opts = audience.pick_options(self.life.scores(tsim, rel, hot, pressure),
                                             self.life.scores(end, rel, hot, pressure), v.rng,
                                             exclude={self.life.activity})
            if v.open(opts, now):
                await self.broadcast({"type": "vote", **v.public(now)})
        p = v.pending
        held = bool(p) and self.life.activity == "play_chess"   # L4: a vote never cuts a game; finish_chess applies it
        if p and not held:
            if awake and self.life.activity == p["act"]:          # he got there by himself meanwhile: nothing to nudge
                v.pending = None
            else:
                can = awake and self.life.scores(tsim, rel, hot, self.engine.pressure(tsim)).get(p["act"], 0.0) > 0
                got = v.take_pending(tsim, can)
                if got and self.life.apply_vote(got["act"], tsim):
                    self.vote_due = got                              # announced when it starts (below)
        due = getattr(self, "vote_due", None)
        if due:
            if self.life.activity == due["act"]:                 # life.start() took the nudge: the vote is carried out
                self.vote_due = None
                await self.broadcast({"type": "vote_applied", "act": due["act"], "label": due["label"],
                                      "round": due["round"], "t": hhmm(tsim), "started": True})
            elif self.life.nudge(tsim) != due["act"]:            # the nudge ran out (an hour) without a start: dropped
                self.vote_due = None
        msg["aud"] = {"n": len(self.sockets), "v": v.compact(now)}
        if held:
            msg["aud"]["held"] = "after the game"
        rx = self.reactions.drain()
        if rx:
            msg["rx"] = rx
        if audience.glance_ok(self.engine.stage, msg.get("life")):   # (else it waits)
            emoji = self.reactions.glance_due()
            if emoji:
                await self.broadcast({"type": "glance", "emoji": emoji})   # (the spike's dominant reaction: how he answers)

    def audience_hello(self, ws):
        if getattr(self, "votes", None) is None:               # a Live with only its websocket parts (as music, replies)
            return None
        ids = self.viewer_ids.get(ws, ())
        return {"reactions": list(audience.REACTIONS), "viewers": len(self.sockets),
                "vote": self.votes.public(mine=self.votes.mine(ids)), "react_every": audience.REACT_EVERY_S,
                "react_burst": audience.REACT_BURST}

    async def handle_vote(self, ws, k):
        ids = self.viewer_ids.get(ws, ())
        ok, reason = self.votes.cast(ids, k, addr=self.viewer_addr.get(ws))
        await ws.send_json({"type": "vote_ack", "ok": ok, "reason": reason, "mine": self.votes.mine(ids)})

    async def handle_react(self, ws, k):
        ids = self.viewer_ids.get(ws, ())
        ok, reason = self.reactions.react(ids[0] if ids else id(ws), k, self.viewer_addr.get(ws))   # IP + UA, the address
        if not ok:
            await ws.send_json({"type": "react_ack", "ok": False, "reason": reason})

    # --- http ----------------------------------------------------------------
    async def ws_handler(self, request):
        # permessage-deflate costs CPU and ~0.2 MB of zlib state per socket: worth it for the room's lite feed (its
        # repeated JSON shrinks ~15x), not for q=1 (base64 activity barely compresses; ~7 KB/s raw at 10 ticks/s)
        compress = not Feed.from_query(request.query).q
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4096, compress=compress)
        await ws.prepare(request)
        # rate-limit + per-address cap key; kept only in memory for this connection and the 10 s limiter window
        key = self.client_ip(request)
        if len(self.sockets) >= self.max_ws or self.ws_per_ip.get(key, 0) >= self.max_ws_ip:
            self.ws_stats["refused"] += 1
            why = "all" if len(self.sockets) >= self.max_ws else "ip"   # (the page says which: too many tabs/addresses, or the room)
            try:
                await ws.send_json({"type": "full", "why": why, "retry": 30})
                await ws.close(code=1013, message=b"full")       # 1013: try again later
            except Exception:
                pass
            return ws
        self.sockets.add(ws)
        self.ws_per_ip[key] = self.ws_per_ip.get(key, 0) + 1
        self.viewer_addr[ws] = self.viewer_fp.address(key)
        self.viewer_ids[ws] = self.viewer_fp.ids(audience.issued_cookie(request.cookies.get(audience.VIEWER_COOKIE)),
                                                 key, request.headers.get("User-Agent", ""))   # (a made-up cookie: none)
        try:
            if request.transport is not None:                    # sends never wait: see backlogged()
                request.transport.set_write_buffer_limits(high=WS_HIGH_WATER)
                self.transports[ws] = request.transport
                sock = request.transport.get_extra_info("socket")
                if sock is not None:                             # a small kernel buffer: a backlog shows up in
                    try:                                         # the transport (and is skipped), not in the kernel
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, WS_SNDBUF)
                    except OSError:
                        pass
            await ws.send_json({"type": "hello", "chat": [self.public(m) for m in self.memory.chat()[-30:]],
                                "replies": getattr(self, "replies", [])[-10:],
                                "rules": [[cond, list(groups)] for cond, groups in RULES], "world": WORLD,
                                "music": self.music.public(self.music.now) if getattr(self, "music", None) else None,
                                "audience": self.audience_hello(ws), "ca": self.ca})
            await ws.send_json(self.nights())
            if self.last_frame:
                await ws.send_json(self.eye_frame())
            self.feeds[ws] = self.feed_for(request.query)
            self.clients.add(ws)
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    d = json.loads(msg.data)
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("type") == "chat" and isinstance(d.get("text"), str):
                    await self.handle_chat(ws, key, d["text"], d.get("nick") if isinstance(d.get("nick"), str) else "")
                elif isinstance(d, dict) and d.get("type") == "teach" and isinstance(d.get("text"), str):
                    nick = d.get("nick") if isinstance(d.get("nick"), str) else ""
                    await self.handle_teach(ws, key, d["text"], nick)
                elif isinstance(d, dict) and d.get("type") == "vote":
                    await self.handle_vote(ws, d.get("k"))
                elif isinstance(d, dict) and d.get("type") == "react":
                    await self.handle_react(ws, d.get("k"))
        finally:                                       # also on errors / cancellation: never leak a client or its buffer
            self.drop_client(ws)
            self.sockets.discard(ws)
            self.viewer_ids.pop(ws, None)
            self.viewer_addr.pop(ws, None)
            n = self.ws_per_ip.get(key, 1) - 1
            if n > 0:
                self.ws_per_ip[key] = n
            else:
                self.ws_per_ip.pop(key, None)
        return ws


def tail_jsonl(path, n, block=64 * 1024):
    """The last `n` rows of a JSONL file, read from its end in 64 KB blocks; lines that do not parse are skipped (as in
    state_io.read_jsonl, which reads and splits the whole file: the eye's frames.jsonl and the chess log grow on the
    volume for months, and /api/frames read all of it on the event loop at every request)."""
    if n <= 0:
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            end, buf = f.tell(), b""
            while end > 0 and buf.count(b"\n") <= n:      # n + 1 newlines: the n-th line from the end is whole
                start = max(0, end - block)
                f.seek(start)
                buf = f.read(end - start) + buf
                end = start
    except OSError:
        return []
    out = []
    for ln in buf.splitlines()[-n:]:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def write_json_files(items):
    """[(path, json text)] -> each written as state_io.save_json does (tmp + fsync + os.replace, one writer per path at
    a time, shared with the sync savers of the same files). Runs in a worker thread: Live.save_state."""
    for path, data in items:
        path = Path(path)
        with state_io._lock(path.absolute()):
            state_io._write_replace(path, data)


def rss_mb():
    """Resident memory of this process in MB (Linux /proc; peak RSS elsewhere)."""
    try:
        for ln in open("/proc/self/status"):
            if ln.startswith("VmRSS:"):
                return round(int(ln.split()[1]) / 1024, 1)
    except OSError:
        pass
    import resource
    import sys
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1024 ** 2 if sys.platform == "darwin" else 1024), 1)


def admin_ok(request):
    """True when the request carries SUB01_ADMIN_TOKEN (X-Admin-Token or Authorization: Bearer). No token set: False."""
    import hmac
    token = os.environ.get("SUB01_ADMIN_TOKEN", "")
    if not token:
        return False
    got = request.headers.get("X-Admin-Token") or request.headers.get("Authorization", "").removeprefix("Bearer ")
    return hmac.compare_digest(got.strip().encode(), token.encode())


async def supervised(name, fn, backoff=5.0):
    """Run a background task forever: an unexpected error is logged and the task restarts, so a part such as the
    screens' browser can fail without stopping the brain loop (asyncio.gather would otherwise end the server)."""
    while True:
        try:
            await fn()
            return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"{name} task failed, restarting in {backoff:.0f}s:", repr(e)[:160], flush=True)
            await asyncio.sleep(backoff)


def parse_start(hm):
    """'HH:MM' -> sim epoch of that local (Tokyo) time today."""
    h, m = map(int, hm.split(":"))
    return datetime.now(TZ).replace(hour=h, minute=m, second=0, microsecond=0).timestamp()


def add_ops_routes(app, live, data_dir):
    """#15: the total cap on the eyes and the mind, GET /healthz (public), /api/costs and /api/health (admin)."""
    for share in (mind_mod.eyes_budget(data_dir), mind_mod.mind_budget(data_dir)):
        share.total = live.ledger.total_why_not   # SUB01_CAP_TOTAL_USD also stops the eyes and the mind

    async def healthz(request):                   # public, tiny, no data: Railway healthcheck + uptime monitor
        ok = live.healthy()
        return web.Response(text="ok" if ok else "stalled", status=200 if ok else 503,
                            headers={"Cache-Control": "no-store"})
    app.router.add_get("/healthz", healthz)

    def admin(fn):
        """/api/costs, /api/health: with SITE_PASSWORD the gate's cookie (or the token) let it through; without it the
        SUB01_ADMIN_TOKEN header is required (no token configured: always 401)."""
        async def handler(request):
            if not (admin_ok(request) or request.app.get(GATED)):
                raise web.HTTPUnauthorized(text="admin token required")
            return web.json_response(fn(request), headers={"Cache-Control": "no-store"})
        return handler
    app.router.add_get("/api/costs", admin(lambda r: live.ledger.report()))

    async def api_wake(request):                     # the owner gets him out of bed now (curl -X POST -H "X-Admin-Token: ...")
        if not (admin_ok(request) or request.app.get(GATED)):
            raise web.HTTPUnauthorized(text="admin token required")
        t = live.clock.now()
        if not live.engine.asleep:
            return web.json_response({"ok": True, "text": "already awake"})
        ev = live.engine.get_up(t, "owner")
        try:
            await live.broadcast({"type": "event", **ev})
        except Exception:
            pass
        return web.json_response({"ok": True, **ev})
    app.router.add_post("/api/wake", api_wake)
    app.router.add_get("/api/health", admin(lambda r: live.health()))

    async def diag_shot(request):
        """#89: the masked screenshot of a logged-in feed that showed the server no video (admin only)."""
        if not (admin_ok(request) or request.app.get(GATED)):
            raise web.HTTPUnauthorized(text="admin token required")
        site = request.match_info["site"]
        get = getattr(live.browser, "diag_shot", None) if live.browser else None
        try:
            shot = await get(site) if get and site in ("tiktok", "youtube") else None
        except BrowserDown:
            shot = None
        if not shot:
            raise web.HTTPNotFound()
        return web.Response(body=shot, content_type="image/jpeg", headers={"Cache-Control": "no-store"})
    app.router.add_get("/api/diag/{site}.jpg", diag_shot)


LOGIN_PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>SUB-01</title><body style="margin:0;height:100vh;display:grid;place-items:center;background:#040406;
color:#ececf2;font-family:ui-monospace,Menlo,monospace"><form method=post action=/login style="display:grid;gap:12px">
<div style="background:#ff6a00;color:#0a0a0a;font-size:28px;letter-spacing:.12em;padding:2px 12px">SUB-01</div>
<input name=password type=password placeholder="password" autofocus style="background:#0c0c12;color:#ececf2;
border:1px solid #2a2a36;padding:10px;font:inherit"><button style="background:#ececf2;border:0;padding:10px;
font:inherit">enter</button>{msg}</form></body>"""


@web.middleware
async def viewer_cookie(request, handler):
    """The vote's one-per-viewer cookie (audience.py): a random id, HttpOnly, set on the pages (never on /ws, /api);
    set again when the browser's one is not an id this server issued (a restart forgot it, or it was made up)."""
    resp = await handler(request)
    if request.method == "GET" and not audience.issued_cookie(request.cookies.get(audience.VIEWER_COOKIE)) and not resp.prepared \
            and request.path in ("/", "/brain", "/room.html", "/index.html"):
        resp.set_cookie(audience.VIEWER_COOKIE, audience.new_viewer_id(), max_age=365 * 86400, httponly=True,
                        samesite="Lax", secure=request.secure or request.headers.get("X-Forwarded-Proto") == "https")
    return resp


# links visitors may still have from before the launch, sent to the page they meant
OLD_PATHS = {"/login": "/", "/room": "/", "/room/": "/", "/home": "/", "/index": "/", "/sees": "/world.html",
             "/brain.html": "/brain", "/diary.html": "/diary", "/about": "/about.html",
             "/city": CITY_URL, "/life": "/life.html", "/map": "/life.html"}   # the city site; the old map at /map

NOT_FOUND_PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>SUB-01</title><link rel="icon" href="/favicon.svg" type="image/svg+xml"><body style="margin:0;height:100vh;
display:grid;place-items:center;background:#040406;color:#ececf2;font-family:ui-monospace,Menlo,monospace">
<div style="display:grid;gap:14px;justify-items:center;text-align:center;padding:16px">
<div style="background:#ff6a00;color:#0a0a0a;font-size:28px;letter-spacing:.12em;padding:2px 12px">SUB-01</div>
<div>this page doesn't exist</div><a href="/" style="color:#ff6a00">back to his room</a></div></body>"""


@web.middleware
async def friendly_errors(request, handler):
    """A page a person opens that isn't there (a 403 or 404 on a GET for HTML) gets a small page with a link to the room,
    not the server's bare error; the APIs, the socket and the media keep their plain status codes."""
    page = (request.method == "GET" and "text/html" in request.headers.get("Accept", "")
            and not request.path.startswith(("/api/", "/ws", "/eye/", "/diary-img/")))
    try:
        resp = await handler(request)
    except web.HTTPException as e:
        if page and e.status in (403, 404):
            return web.Response(text=NOT_FOUND_PAGE, content_type="text/html", status=404)
        raise
    if page and not resp.prepared and isinstance(resp, web.FileResponse):   # (the static route answers a missing file
        path = getattr(resp, "_path", None)                                  # with a FileResponse that 404s on send)
        if path is not None and not Path(path).is_file():
            return web.Response(text=NOT_FOUND_PAGE, content_type="text/html", status=404)
    return resp


def password_gate(password):
    """Private preview: one shared password (SITE_PASSWORD), remembered in an HttpOnly cookie."""
    import hashlib
    import hmac
    token = hashlib.sha256(("sub01:" + password).encode()).hexdigest()

    @web.middleware
    async def gate(request, handler):
        if request.path == "/login":
            if request.method == "POST":
                form = await request.post()
                if hmac.compare_digest(str(form.get("password", "")), password):
                    resp = web.HTTPFound("/")
                    resp.set_cookie("sub01", token, max_age=30 * 86400, httponly=True, samesite="Lax",
                                    secure=request.headers.get("X-Forwarded-Proto") == "https")
                    raise resp
                return web.Response(text=LOGIN_PAGE.format(msg="<small>wrong password</small>"),
                                    content_type="text/html", status=401)
            return web.Response(text=LOGIN_PAGE.format(msg=""), content_type="text/html")
        if spiking_server and request.path in spiking_server.POD_PATHS:
            return await handler(request)                  # the pod authenticates with its own secret in the handler
        if request.path == "/healthz" or (request.path in ADMIN_PATHS and admin_ok(request)):
            return await handler(request)                  # uptime monitors / Railway healthcheck; admin token
        if hmac.compare_digest(request.cookies.get("sub01", ""), token):
            return await handler(request)
        if request.path == "/ws" or request.path.startswith("/api/"):
            raise web.HTTPUnauthorized()
        raise web.HTTPFound("/login")
    return gate


async def main(args):
    data_dir = Path(args.data_dir) if args.data_dir else HERE / "data" / ("demo" if args.time_scale != 1 else "")
    t_build = time.monotonic()
    live = Live(args.mint, args.demo, args.time_scale, data_dir,
                parse_start(args.start) if args.start else None, args.trust_proxy)
    built_s = time.monotonic() - t_build          # the brain model (+ the fitted slow layer's eig) and the saved state
    # launched (owner, 2026-10-08): the site is public; the password gate only comes back with SITE_GATE=1
    gate_on = os.environ.get("SITE_PASSWORD") and os.environ.get("SITE_GATE") == "1"
    middlewares = [password_gate(os.environ["SITE_PASSWORD"])] if gate_on else []
    if args.vote_round:
        live.votes.round_s = args.vote_round
    app = web.Application(client_max_size=64 * 1024 ** 2, middlewares=middlewares + [viewer_cookie, friendly_errors])
    app[GATED] = bool(middlewares)                # behind the password gate: its cookie also opens the admin APIs
    app.router.add_get("/ws", live.ws_handler)
    manager = None
    if spiking_server:
        hub = spiking_server.attach(app, live, data_dir)
        manager = spiking_manager.from_env(data_dir, get_items=lambda: spiking_manager.top_items(live.memory, live.clock.now()))
        if manager.enabled():
            hub.manager, manager.send_stop = manager, hub.forward_stop
            live.gpu_test = True                  # /api/taught shows recall results only when the GPU test runs
        else:
            manager = None

    cpu_net = None                                # his spiking neurons in the day (#55); SUB01_SPIKING_LIVE=0: no CPU net
    if os.environ.get("SUB01_SPIKING_LIVE", "1") != "0":
        cpu_net = spiking_live.LiveClient(data_dir, int(os.environ.get("SUB01_SPIKING_LIVE_NEURONS") or
                                                        spiking_live.N_NEURONS))
        # its frames feed the Neurons panel and the 3D neurons like the GPU session's, through the hub's per-viewer budget
        cpu_net.on_frame = live.spiking.relay if live.spiking else live.broadcast
    live.decider = brain_vote.Backend(cpu=cpu_net, gpu=spiking_manager, log=spiking_live.DecisionLog(data_dir))
    spiking_live.attach(app, live.decider)
    launchpad_eval.add_routes(app, live, data_dir)   # the launchpad asks his brain about ideas (signed, off without a secret)

    async def snap(request):                      # save a canvas capture posted by the page (local only)
        name = Path(request.query.get("name", "snap")).name
        ext = request.query.get("ext", "png") if request.query.get("ext") in ("png", "webm", "mp4") else "png"
        (HERE / "out" / f"{name}.{ext}").write_bytes(await request.read())
        return web.Response(text="ok")
    if args.host in ("127.0.0.1", "localhost"):
        app.router.add_post("/snap", snap)        # local-only helper: never exposed on a public host
    if args.replay_real_session and list((HERE / "out" / "rest").glob("*.npz")):
        live.baseline = RealBaseline(live.brain.names, HERE / "out" / "rest")
        live.brain.use_slow_layer(False)          # the recording replaces the model's own slow activity
    live.browse_wanted = bool(args.browse)
    if not args.browse:
        live.screens.set_off("the browser is turned off (BROWSE=0)")
    if args.browse:
        load_env(HERE / ".env")                   # REPLICATE_API_TOKEN / ANTHROPIC_API_KEY for the eyes (never logged)
        if os.environ.get("BROWSE_SERVICE_URL"):  # Chromium as its own Railway service
            live.browser = BrowserClient(os.environ["BROWSE_SERVICE_URL"], os.environ.get("BROWSE_SERVICE_TOKEN", ""))
        elif Browser.available():                 # Chromium in a child process with its own memory watchdog
            live.local_browser = LocalBrowser()
            live.browser = live.local_browser.client
        else:
            print("--browse: playwright is not installed, screens stay on Wikipedia reading", flush=True)
            live.screens.set_off("playwright is not installed: no browser")
        live.eyes = Eyes(data_dir=data_dir, budget=mind_mod.eyes_budget(data_dir))   # one ledger with the mind
    if os.environ.get("MIND", "1") != "0":
        load_env(HERE / ".env")                   # ANTHROPIC_API_KEY / OPENROUTER_API_KEY (never logged)
        live.mind = mind_mod.Mind(data_dir, budget=mind_mod.mind_budget(data_dir), clock=live.clock.now)

    add_ops_routes(app, live, data_dir)
    if os.environ.get("CLIPS", "1") != "0":       # #59: daily clips for the social accounts, made in nice'd children
        live.clips = clips.ClipMaker(data_dir)
        live.clips.ledger = live.ledger
        clips.add_routes(app, live.clips, lambda r: admin_ok(r) or bool(r.app.get(GATED)))

    async def screen_shot(request):               # latest screenshot of the desk or phone screen
        dev = request.match_info["device"]
        st = (getattr(live.browser, "screens", None) or {}).get(dev) if live.browser else None
        try:                                      # S2 / B8: no current status (closed, timed out), a refused title
            shot = (await live.browser.shot(dev) if live.browser and dev in ("desk", "phone")   # or a finance page:
                    and st and screen_showable(st) else None)                                   # nothing to show
        except BrowserDown:
            shot = None
        if not shot:
            raise web.HTTPNotFound()
        return web.Response(body=shot, content_type="image/jpeg", headers={"Cache-Control": "no-store"})
    app.router.add_get("/api/screen/{device}.jpg", screen_shot)

    async def browsing(request):                  # pages shown on his screens, newest last
        return web.json_response(live.browsing_view())
    app.router.add_get("/api/browsing", browsing)
    app.router.add_get("/api/screens", lambda r: web.json_response(live.screens_view()))   # #89: always visible

    async def tastes(request):                    # what kinds of pages have paid off in the brain's response
        return web.json_response(live.tastes.top())
    app.router.add_get("/api/tastes", tastes)

    async def taught(request):                    # words viewers taught him: replay counts, next-day recall (GPU on)
        return web.json_response(live.taught())
    app.router.add_get("/api/taught", taught)

    async def decisions(request):                 # the brain's last choices on the screens, with the options it saw
        return web.json_response({"decisions": live.decision_log[-20:],
                                  "eyes": live.eyes.budget.summary() if live.eyes else None,
                                  "note": "An AI reads the page and lists options; his brain model picks. "
                                          "It does not understand what it reads."})
    app.router.add_get("/api/decisions", decisions)

    async def chess_api(request):                 # the chess board at his desk, recent games, what the card says
        return web.json_response(live.chess_view())
    app.router.add_get("/api/chess", chess_api)

    async def vote_api(request):                  # viewers' vote on what he does next: the round, the last result
        return web.json_response(live.votes.public())
    app.router.add_get("/api/vote", vote_api)

    async def music_api(request):                 # now playing (Spotify embed URL), today's tracks and why each was picked
        return web.json_response(live.music.view(live.clock.now()))
    app.router.add_get("/api/music", music_api)

    async def mind_api(request):                  # the day plan, notes, replies and the shared AI budget
        return web.json_response(live.mind_view())
    app.router.add_get("/api/mind", mind_api)
    if args.eye:
        load_env(HERE / ".env")                   # REPLICATE_API_TOKEN -> images in the cloud, not on this Mac
        frames_dir = Path(args.frames_dir) if args.frames_dir else HERE / "out" / "eye" / "frames"
        live.eye = Eye(frames_dir, data_dir / "world.json", width=640, height=360, steps=6)
        live.eye.ledger = live.ledger             # SUB01_CAP_EYE_USD + total, checked before every Replicate call
        live.eye_every = args.eye_every
        app.router.add_static("/eye", frames_dir)
        live.diary = Diary(data_dir, frames_dir)
        app.router.add_static("/diary-img", live.diary.img)

    async def diary_index(request):                # nights written so far, newest first
        return web.json_response({"nights": live.diary.index() if live.diary else []})

    async def diary_night(request):
        try:
            d = live.diary.load(request.match_info["date"]) if live.diary else None
        except ValueError:
            d = None
        if d is None:
            raise web.HTTPNotFound()
        return web.json_response(d)
    app.router.add_get("/api/diary", diary_index)
    app.router.add_get("/api/diary/{date}", diary_night)

    async def reading(request):                   # what it read at the computer, newest last
        return web.json_response({"log": [public_why(a) for a in live.reader.log[-20:]]})
    app.router.add_get("/api/reading", reading)

    async def frames(request):                    # recent eye frames for the world page
        log = live.eye.log if live.eye else HERE / "missing"
        try:
            n = max(1, min(500, int(request.query.get("n", "40"))))
        except ValueError:
            n = 40
        # frames.jsonl grows for as long as the volume lives: read its tail only, and off the event loop
        rows = await asyncio.get_running_loop().run_in_executor(None, tail_jsonl, log, n)   # a torn line is skipped
        world = live.eye.world.top(live.clock.now(), 20) if live.eye else []
        return web.json_response({"frames": rows, "world": world, "resting": RESTING if live.eye_resting else None})
    app.router.add_get("/api/frames", frames)

    gmaps_ok = {}

    async def gmaps_works(key, referer):
        """Only hand the Maps key to browsers once Google really serves Street View with it (billing on)."""
        if key not in gmaps_ok or time.time() - gmaps_ok[key][1] > 3600:
            url = ("https://maps.googleapis.com/maps/api/streetview/metadata?location=35.70545,139.57455&radius=50&key="
                   + key)
            try:
                async with aiohttp.ClientSession() as http, http.get(url, headers={"Referer": referer}) as r:
                    ok = (await r.json()).get("status") == "OK"
            except Exception:
                ok = False
            gmaps_ok[key] = (ok, time.time())
        return gmaps_ok[key][0]

    async def config(request):                    # browser config (Maps JS keys are referrer-restricted by design)
        key = os.environ.get("GOOGLE_MAPS_KEY", "")
        referer = f"{request.headers.get('X-Forwarded-Proto', request.scheme)}://{request.host}/"
        return web.json_response({"gmaps": key if key and await gmaps_works(key, referer) else "", "ca": live.ca})
    app.router.add_get("/api/config", config)

    city_state = {"up": False, "checked": 0.0}

    async def city(request):
        """The city site's pulse for the room's popout card: one GET of its front page at most every 60 s (shared by
        every viewer), up = 200. The city forbids being framed by other sites (frame-ancestors 'self'), so the card is
        a preview and a live dot, and the click opens the city in its own window."""
        if time.time() - city_state["checked"] > 60:
            city_state["checked"] = time.time()
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as http, \
                        http.get(CITY_URL, headers={"User-Agent": "SUB-01 room (city pulse)"}) as r:
                    city_state["up"] = r.status == 200
            except Exception:
                city_state["up"] = False
        return web.json_response({"url": CITY_URL, "up": city_state["up"], "checked": int(city_state["checked"])},
                                 headers={"Cache-Control": "no-store"})
    app.router.add_get("/api/city", city)
    app.router.add_get("/", lambda r: web.FileResponse(HERE / "web" / "room.html", headers=NOCACHE))   # his room is the front page       # the life is the front page
    app.router.add_get("/brain", lambda r: web.FileResponse(HERE / "web" / "index.html", headers=NOCACHE))
    app.router.add_get("/diary", lambda r: web.FileResponse(HERE / "web" / "diary.html", headers=NOCACHE))
    for old, new in OLD_PATHS.items():             # links from before the launch (the login page, short names)
        app.router.add_get(old, lambda r, new=new: web.HTTPFound(new))
    app.router.add_static("/", HERE / "web")
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, args.host, args.port).start()
    print(f"SUB-01 live on http://localhost:{args.port}  ({'demo' if args.demo else (args.mint or 'no coin yet: trade feed off')}, "
          f"time x{args.time_scale:g}, state in {data_dir})", flush=True)
    # the deploy gap: until this line the edge gets "connection refused" (a 502); a slow build shows up here
    print(f"startup: listening {time.monotonic() - START:.1f} s after import (brain + state built in {built_s:.1f} s); "
          f"/healthz answers 200 from the first brain tick", flush=True)
    live.life.can_watch = bool(live.browser)     # no browser: no videos at the desk
    # every long-running part is supervised: an unexpected error restarts that part, instead of ending asyncio.gather
    # and with it the process (a Railway restart = a 502 window for every page until the new process listens)
    tasks = [supervised("brain", live.run_brain, backoff=1.0), supervised("research", live.run_research),
             supervised("trades", live.demo_trades if args.demo else live.rpc_trades),
             supervised("chess", live.run_chess), supervised("music", live.run_music)]
    if live.eye:
        tasks.append(supervised("eye", live.run_eye))
    if live.browser:
        tasks.append(supervised("browse", live.run_browse))
    if live.mind:
        tasks.append(supervised("mind", live.run_mind))
    if manager:
        tasks.append(manager.run())
    if cpu_net:
        tasks.append(supervised("spiking live", cpu_net.run))
    if getattr(live, "clips", None):
        tasks.append(supervised("clips", lambda: live.clips.run(live, args.port), backoff=60))
    me, stopping = asyncio.current_task(), []

    def on_sigterm():                             # a redeploy / `docker stop`: SIGTERM, then SIGKILL after a grace period.
        if not stopping:                          # Without this the process died at once and the last minute of state
            stopping.append(True)                 # (memory, sleep, life) was lost; now the finally below saves it first.
            print("SIGTERM: saving state and stopping", flush=True)
            me.cancel()
    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, on_sigterm)
    except (NotImplementedError, RuntimeError, ValueError):    # not on this platform / not the main thread
        pass
    try:
        await asyncio.gather(*tasks)
    finally:
        live.store.save(live.engine, live.memory)
        if manager:
            manager.shutdown()
        if cpu_net:
            await cpu_net.stop()
        live.save_screens()                               # #89: today's screens survive the deploy
        if live.browser:
            try:
                await asyncio.wait_for(live.sync_browsing(), 5)  # the newest log, if the browser still answers
            except (BrowserDown, asyncio.TimeoutError):
                pass
            save_json(live.browsing_path, live.browsing_state, ensure_ascii=False)
            if live.local_browser:
                await live.local_browser.aclose()
            else:
                await live.browser.aclose()


def build_parser():
    p = argparse.ArgumentParser()
    p.add_argument("--mint", default=os.environ.get("MINT", "").strip())   # our token, set at launch; empty: no trade feed
    p.add_argument("--demo", action="store_true")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)))
    p.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    p.add_argument("--frames-dir", help="where eye frames are written (default out/eye/frames)")
    p.add_argument("--time-scale", type=float, default=1.0, help="sim seconds per real second (60: 1 h per minute)")
    p.add_argument("--start", help="local (Tokyo) time HH:MM to start the (accelerated) clock at, e.g. 23:55")
    p.add_argument("--data-dir", help="state + nights directory (default data/, or data/demo when accelerated)")
    p.add_argument("--eye-every", type=float, default=90.0, help="seconds between eye frames while awake")
    p.add_argument("--replay-real-session", action="store_true", default=os.environ.get("REPLAY_REAL_SESSION") == "1",
                   help="replay his recorded resting-state fMRI as the background instead of the fitted slow layer")
    p.add_argument("--no-real-baseline", action="store_true", help=argparse.SUPPRESS)   # old flag (now the default)
    p.add_argument("--eye", action="store_true", help="generate what SUB-01 'sees' (local image + language models)")
    p.add_argument("--browse", action="store_true", default=os.environ.get("BROWSE") == "1",
                   help="real headless browser on the open web for his computer and phone screens (needs playwright)")
    p.add_argument("--vote-round", type=float, default=None,
                   help="seconds per viewers' vote round (default SUB01_VOTE_ROUND_S or 3600)")
    p.add_argument("--trust-proxy", action="store_true", help="rate-limit by X-Forwarded-For (behind a reverse proxy)")
    return p


if __name__ == "__main__":
    try:
        asyncio.run(main(build_parser().parse_args()))
    except asyncio.CancelledError:                # SIGTERM (a redeploy): the state was saved in main()'s finally
        pass
