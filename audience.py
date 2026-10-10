"""Viewers in the room (preview/interactive): the vote on what he does next, the live viewer count, the reactions.

The vote. Every round (VOTE_ROUND_S, default 10 min: a vote should show within minutes, not an hour) viewers pick one
of 3 activities. The options come from what his activity model (life.py) allows at that hour, both now and when the
round ends (never "go to the park" at 3 am), and never what he is already doing (a no-op option). When the round ends,
the most-voted option becomes a strong nudge in his activity model (Life.viewer_nudge: a bonus on that activity's
score, like the day plan's tilt but stronger); needs still come first. Asleep: no round opens, and a result waits until
he wakes (at most PENDING_MAX_S). The page is told when the voted activity actually begins (live_server: vote_applied).
  * one vote per viewer per round: the HttpOnly cookie (a random id the server issued and still remembers: a made-up
    cookie counts for nothing) when the browser has one, else a salted hash of IP + user agent; both are hashed with
    a salt that lives only in memory (a new one each round), so nothing about a viewer is ever stored raw or written
    to disk, and a round's hashes are dropped when it closes. Behind one address at most VOTES_PER_ADDRESS voters count
    (the backstop against a script minting cookies), so two people on one network with the same browser both vote;
  * a tie goes to the tied option listed first; options are listed in the order his own model ranks them now (its
    activity scores), so a tie falls to what the model already leaned toward; no votes at all: no nudge.

The reactions. A fixed set of emoji (REACTIONS), no free text. Each viewer has a token bucket (1 every REACT_EVERY_S,
burst REACT_BURST: a burst is a spike's worth, so one viewer alone can make him glance). Accepted reactions are summed
server-side and go out in the existing tick ("rx": counts per emoji since the last tick). When they spike (SPIKE_N
within SPIKE_S seconds) he glances toward the camera once, at most once every GLANCE_EVERY_S. Behind the per-viewer and
per-address buckets (both keyed on what the client sends: cookie, address, user agent) sit flood buckets over all
clients together (REACT_ALL_*, VOTE_ALL_*) that depend on nothing a client can forge.

Nothing here spends on an API or a language model; it is counting."""
import hashlib
import hmac
import os
import secrets
import time
from collections import deque

VOTE_ROUND_S = float(os.environ.get("SUB01_VOTE_ROUND_S", 600))
VOTE_OPTIONS = 3
VOTES_PER_ADDRESS = 25        # at most this many voters per address per round (a shared network - a dorm, an office -
                              # is fine; one machine minting a cookie and a user agent per vote is not)
VOTE_ALL_EVERY_S, VOTE_ALL_BURST = 0.05, 60    # flood backstop over every client together (20 votes/s, 60 saved)
VOTE_BONUS = 1.2              # added to the winning activity's score (the day plan's tilt is 0.35, a meal need 1.6)
NUDGE_HOLD_S = 3600           # simulated seconds the nudge stays on once he is awake (then it is spent)
PENDING_MAX_S = 12 * 3600     # simulated seconds a result may wait for him to wake (a night; not two days)
ISSUED_MAX = 50_000           # cookie ids the server remembers having issued (memory only; the oldest are forgotten)
# activity -> what the option says (neutral: what he would do, never what he wants). Food, sleep and the door are needs
# and never put to a vote; nothing financial is ever an option (S1: there is no chart activity any more).
VOTABLE = {
    "research": "read at the computer",
    "watch_video": "watch a video at the desk",
    "play_chess": "play a game of chess",
    "listen_music": "listen to music on the bed",
    "park": "walk to the park",
    "window": "look out of the window",
    "phone": "scroll the phone in bed",
}

REACTIONS = ("👋", "❤️", "😂", "😮", "👏", "✨")
REACT_EVERY_S = 3.0           # one token every 3 s ...
REACT_BURST = 10              # ... up to 10 saved up (= SPIKE_N: a viewer alone, tapping, can make him glance)
REACT_IP_EVERY_S, REACT_IP_BURST = 1.0, 20   # and per address (all its browsers together): a fresh cookie or user agent
                                             # per connection cannot multiply the rate
REACT_ALL_EVERY_S, REACT_ALL_BURST = 0.02, 200   # flood backstop over every client together (50/s, 200 saved)
RECENT_MAX = 200              # accepted reactions remembered for the spike (bounded whatever the tick rate)
SPIKE_N, SPIKE_S = 10, 10.0   # 10 reactions within 10 s: he glances toward the camera
GLANCE_EVERY_S = 120.0        # at most once every 2 minutes
VIEWER_COOKIE = "sub01v"

_ISSUED = {}                  # cookie id -> None, in issue order (a bounded set: the ids this process handed out)


def new_viewer_id():
    """The cookie's value: random, says nothing about the viewer. Remembered (memory only) so a vote can tell a cookie
    this server issued from one a script made up."""
    v = secrets.token_urlsafe(16)
    _ISSUED[v] = None
    while len(_ISSUED) > ISSUED_MAX:
        del _ISSUED[next(iter(_ISSUED))]
    return v


def issued_cookie(cookie):
    """`cookie` if this server issued it (and still remembers it), else None: an unknown cookie (made up, or from
    before a restart: the page middleware then sets a fresh one) counts as no cookie."""
    return cookie if isinstance(cookie, str) and cookie in _ISSUED else None


class Fingerprints:
    """Salted hashes of a viewer's cookie, or of IP + user agent without one. The salt lives in memory only; rotate()
    makes a new one (each vote round), so last round's hashes can never be matched again."""

    def __init__(self):
        self.rotate()

    def rotate(self):
        self.salt = secrets.token_bytes(16)

    def _h(self, kind, value):
        return hmac.new(self.salt, f"{kind}|{value}".encode("utf-8", "replace"), hashlib.sha256).hexdigest()[:24]

    def ids(self, cookie, ip, ua):
        """The hash one viewer is known by: the cookie's when there is one (the caller passes only a cookie the server
        issued: issued_cookie), else IP + UA's. One tuple either way (what the vote and the reactions key on)."""
        if cookie:
            return (self._h("cookie", cookie[:64]),)
        return (self._h("ip-ua", f"{ip or ''}|{(ua or '')[:300]}"),)

    def address(self, ip):
        """The address alone, hashed (the reactions' per-address bucket; never used for the vote)."""
        return self._h("ip", ip or "")

    def rehash(self, ids):
        """Hashes of hashes: a connection's ids (made once with the process's salt) under this round's salt."""
        return tuple(self._h("id", i) for i in ids)


class VoteRound:
    """One round: options, counts, the hashes that voted. Pure (the caller passes the clock and the options)."""

    def __init__(self, rid, start, end, options, labels=None):
        self.id, self.start, self.end = rid, start, end
        self.options = list(options)                       # activities, in his model's order (the tie rule)
        self.labels = [(labels or VOTABLE).get(a, a) for a in self.options]
        self.counts = [0] * len(self.options)
        self.voted = {}                                    # viewer hash -> option index (memory only)
        self.per_addr = {}                                 # address hash -> voters from it this round (memory only)
        self.closed = False

    def cast(self, ids, k, now, addr=None, flood=None):
        """(ok, reason). ids: the viewer's hashes (the cookie's, or IP + UA's); any one of them seen already = voted.
        addr: the address's hash; at most VOTES_PER_ADDRESS voters from one address per round. flood: a callable
        asked last, only for a vote that would count (the backstop over all clients: False refuses it)."""
        if self.closed or now >= self.end:
            return False, "this round has ended"
        if not isinstance(k, int) or isinstance(k, bool) or not 0 <= k < len(self.options):
            return False, "not an option"
        if any(i in self.voted for i in ids):
            return False, "one vote per viewer per round"
        if addr is not None and self.per_addr.get(addr, 0) >= VOTES_PER_ADDRESS:
            return False, "too many votes from this network this round"
        if flood is not None and not flood():
            return False, "too many votes at once; try again in a moment"
        if addr is not None:
            self.per_addr[addr] = self.per_addr.get(addr, 0) + 1
        for i in ids:
            self.voted[i] = k
        self.counts[k] += 1
        return True, ""

    def choice_of(self, ids):
        for i in ids:
            if i in self.voted:
                return self.voted[i]
        return None

    def winner(self):
        """The most-voted option's index; a tie goes to the tied option listed first; no votes: None."""
        if not self.options or max(self.counts, default=0) == 0:
            return None
        top = max(self.counts)
        return self.counts.index(top)

    def close(self):
        self.closed = True
        k = self.winner()
        self.voted.clear()                                 # nothing kept about who voted
        self.per_addr.clear()
        return k

    def public(self, now, mine=None):
        return {"id": self.id, "options": [{"act": a, "label": l, "n": n}
                                           for a, l, n in zip(self.options, self.labels, self.counts)],
                "total": sum(self.counts), "ends_in": max(0, round(self.end - now)), "length": round(self.end - self.start),
                **({"mine": mine} if mine is not None else {})}


def pick_options(scores_now, scores_end, rng, n=VOTE_OPTIONS, votable=VOTABLE, exclude=()):
    """Up to n votable activities his model allows both now and at the round's end (score > 0 at both), drawn at random
    and listed in the order his model ranks them now (the tie rule). `exclude`: what he is doing now (voting for it
    would change nothing). Fewer than 2 possible: no round."""
    ok = [a for a in votable if a not in exclude and scores_now.get(a, 0.0) > 0 and scores_end.get(a, 0.0) > 0]
    if len(ok) < 2:
        return []
    pick = rng.sample(ok, min(n, len(ok)))
    return sorted(pick, key=lambda a: -scores_now[a])


class Votes:
    """The rounds over time and the result waiting to be applied. The caller (live_server) gives it the clock and asks
    it, each tick, whether a result can be applied now (awake)."""

    def __init__(self, round_s=VOTE_ROUND_S, rng=None, clock=time.time):
        import random
        self.round_s, self.rng, self.clock = float(round_s), rng or random.Random(), clock
        self.fp = Fingerprints()
        self.round = None
        self.n = 0
        self.pending = None          # {"act", "label", "round", "votes", "total", "at"} waiting for him to be awake
        self.retry_at = 0.0          # no round could open (fewer than 2 options, or asleep): when to try again
        self.last = None             # the last closed round's public result (for the card)
        self.flood = TokenBucket(VOTE_ALL_EVERY_S, VOTE_ALL_BURST)   # over all clients: no header can lift it

    def due(self, now=None):
        now = self.clock() if now is None else now
        return now >= self.retry_at if self.round is None else now >= self.round.end

    def open(self, options, now=None):
        now = self.clock() if now is None else now
        self.fp.rotate()
        self.n += 1
        self.round = VoteRound(self.n, now, now + self.round_s, options) if options else None
        if self.round is None:                    # nothing to choose between now: try again in a minute
            self.retry_at = now + 60
        return self.round

    def close(self, sim_t):
        """Close the running round; returns the result (or None). The winner becomes the pending nudge."""
        r = self.round
        if r is None:
            return None
        k = r.close()
        res = {"round": r.id, "options": [{"act": a, "label": l, "n": n} for a, l, n in zip(r.options, r.labels, r.counts)],
               "total": sum(r.counts), "winner": None if k is None else r.options[k],
               "label": None if k is None else r.labels[k]}
        self.last = res
        if k is not None:
            self.pending = {"act": r.options[k], "label": r.labels[k], "round": r.id, "votes": r.counts[k],
                            "total": sum(r.counts), "at": sim_t}
        return res

    def take_pending(self, sim_t, awake):
        """The pending result, if it can be applied now (awake: he is awake and the activity is possible now). Asleep:
        it waits. Older than PENDING_MAX_S: dropped. Returns the pending dict once (and clears it), or None."""
        p = self.pending
        if p is None:
            return None
        if sim_t - p["at"] > PENDING_MAX_S:
            self.pending = None
            return None
        if not awake:
            return None
        self.pending = None
        return p

    def cast(self, ids, k, now=None, addr=None):
        """ids: the viewer's hashes (Fingerprints.ids, made once per connection); rehashed with this round's salt, as
        is addr (Fingerprints.address)."""
        now = self.clock() if now is None else now
        if self.round is None:
            return False, "no round right now"
        return self.round.cast(self.fp.rehash(ids), k, now, None if addr is None else self.fp.rehash((addr,))[0],
                               flood=lambda: self.flood.allow("all"))

    def mine(self, ids):
        return None if self.round is None else self.round.choice_of(self.fp.rehash(ids))

    def public(self, now=None, mine=None):
        now = self.clock() if now is None else now
        out = {"round": self.round.public(now, mine) if self.round else None, "last": self.last,
               "waiting": ({"label": self.pending["label"]} if self.pending else None)}
        return out

    def compact(self, now=None):
        """The tick's view: round id, counts, seconds left (labels come with the hello and vote messages)."""
        now = self.clock() if now is None else now
        r = self.round
        if r is None:
            return None
        return [r.id, r.counts, max(0, round(r.end - now))]


OUTSIDE = ("counter", "bakery_in", "bench", "park_gate", "bakery_door")   # (life.PLACES out of the room's view)


def glance_ok(stage, life):
    """He can glance at the camera: awake, in the room (not out on a walk) and upright (sitting, standing, walking;
    not lying on the bed). life: Life.snapshot()."""
    return stage == "AWAKE" and bool(life) and not life.get("geo") and life.get("place") not in OUTSIDE \
        and not str(life.get("pose", "")).startswith("lying")


class TokenBucket:
    """Per-key token buckets: `rate` tokens a second, at most `burst` saved. Idle keys are forgotten."""

    def __init__(self, every=REACT_EVERY_S, burst=REACT_BURST, clock=time.monotonic):
        self.every, self.burst, self.clock = float(every), float(burst), clock
        self.b = {}                                         # key -> (tokens, last time)
        self.purged = clock()

    def peek(self, key):
        """Tokens `key` has now (without taking one)."""
        tok, last = self.b.get(key, (self.burst, self.clock()))
        return min(self.burst, tok + (self.clock() - last) / self.every)

    def allow(self, key):
        now = self.clock()
        if now - self.purged > 60:                          # a full bucket is the same as no entry: forget it
            self.b = {k: v for k, v in self.b.items() if v[0] + (now - v[1]) / self.every < self.burst}
            self.purged = now
        tok, last = self.b.get(key, (self.burst, now))
        tok = min(self.burst, tok + (now - last) / self.every)
        if tok < 1.0:
            self.b[key] = (tok, now)
            return False
        self.b[key] = (tok - 1.0, now)
        return True


class Reactions:
    """Accepted reactions, summed until the next tick; the spike that makes him glance."""

    def __init__(self, clock=time.monotonic, every=REACT_EVERY_S, burst=REACT_BURST):
        self.clock = clock
        self.limit = TokenBucket(every, burst, clock)
        self.limit_ip = TokenBucket(REACT_IP_EVERY_S, REACT_IP_BURST, clock)
        self.limit_all = TokenBucket(REACT_ALL_EVERY_S, REACT_ALL_BURST, clock)   # over all clients together
        self.counts = [0] * len(REACTIONS)
        self.recent = deque(maxlen=RECENT_MAX)              # (time, reaction index) of accepted reactions, the last SPIKE_S seconds
        self.last_glance = -1e18
        self.total = 0

    def _trim(self, now):
        while self.recent and now - self.recent[0][0] > SPIKE_S:
            self.recent.popleft()

    def react(self, key, k, addr=None):
        """(ok, reason). key: the viewer's hash (cookie, or IP + UA); addr: the address's hash (never the raw address).
        Every bucket must have a token: per viewer (1 every 3 s, burst 10), per address (1 a second, burst 20) and
        over all clients (50 a second, burst 200: the flood backstop no client header can lift)."""
        if not isinstance(k, int) or isinstance(k, bool) or not 0 <= k < len(REACTIONS):
            return False, "not a reaction"
        if addr is not None and self.limit_ip.peek(addr) < 1.0:
            return False, "slow down"
        if self.limit_all.peek("all") < 1.0:
            return False, "slow down"
        if not self.limit.allow(key):
            return False, "slow down"
        if addr is not None:
            self.limit_ip.allow(addr)
        self.limit_all.allow("all")
        self.counts[k] += 1
        self.total += 1
        now = self.clock()
        self._trim(now)
        self.recent.append((now, k))
        return True, ""

    def drain(self):
        """The counts since the last call (for the tick), or None if there were none."""
        if not any(self.counts):
            return None
        out, self.counts = self.counts, [0] * len(REACTIONS)
        return out

    def glance_due(self):
        """Once when reactions spike (SPIKE_N within SPIKE_S), at most every GLANCE_EVERY_S: the spike's dominant reaction
        (the emoji most sent in it; a tie goes to the latest of them), which picks how he answers; else None."""
        now = self.clock()
        self._trim(now)
        if len(self.recent) >= SPIKE_N and now - self.last_glance >= GLANCE_EVERY_S:
            n, last = [0] * len(REACTIONS), {}
            for i, (_, k) in enumerate(self.recent):
                n[k] += 1; last[k] = i
            top = max(range(len(REACTIONS)), key=lambda k: (n[k], last.get(k, -1)))
            self.last_glance = now
            self.recent.clear()
            return REACTIONS[top]
        return None
