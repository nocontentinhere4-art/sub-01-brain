"""Public chat for SUB-01: message filter, rate limit, duplicate check, the message -> stimulus rules and the
word -> network lexicon also used for what it reads (research.py).

Everything here is a transparent rule table; no external API and no language model.
The filter runs first: blocked messages are never shown, stored or turned into stimuli.
"""
import re
import time
import unicodedata
from collections import deque

from lexicon import HYPE, money_talk
from state_io import load_json, save_json

MAX_LEN = 280
RATE_S = 10.0

# --- filter --------------------------------------------------------------------------
URL = re.compile(r"(https?://|www\.|\b[\w-]+\.(com|net|org|io|xyz|fun|app|gg|co|me|ly|sol|to|ru|info|biz|link|"
                 r"site|online|club|finance|exchange|money|pro|tech|dev|ai)\b|t\.me/|discord\.gg)", re.I)
SOL_ADDR = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
ETH_ADDR = re.compile(r"\b0x[a-fA-F0-9]{8,}")
TICKER = re.compile(r"\$[A-Za-z][A-Za-z0-9]{1,11}\b")
# song and video titles: a coin ticker still counts ("$PEPE to the moon"), a "$" in an artist's styling does not
# ("$uicideboy$", "A$AP Rocky", "Ke$ha")
MEDIA_TICKER = re.compile(r"(?<![A-Za-z0-9$])\$[A-Za-z][A-Za-z0-9]{1,11}\b(?!\$)")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
PHONE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
MONEY = re.compile(r"\b(send|give|pay|tip|donate|lend|transfer|spare)\b.{0,20}\b(sol|eth|btc|usdc|usdt|crypto|money|"
                   r"cash|funds|coins?|tokens?|dollars?|bucks|euros?|\d+)\b|\$\s?\d|\d\s?(sol|usd|eur|€)\b|"
                   r"\b(donations?|donate|giveaway|airdrop|venmo|paypal|cash ?app|zelle|wallet|seed phrase|private key)\b",
                   re.I)
# song and video titles (media=True): only requests for money (a verb with a currency, coin or "$" amount, or a
# donation / payment-app / wallet word); a bare number ("Give It 2 Me") or price ("$5 Pizza Hack", "5 eur") passes
MEDIA_MONEY = re.compile(r"\b(send|give|pay|tip|donate|lend|transfer|spare)\b.{0,20}(\b(sol|eth|btc|usdc|usdt|crypto|"
                         r"money|cash|funds|coins?|tokens?|dollars?|bucks|euros?)\b|\$\s?\d|\d\s?(sol|usd|eur|€)\b)|"
                         r"\b(donations?|donate|giveaway|airdrop|venmo|paypal|cash ?app|zelle|wallet|seed phrase|"
                         r"private key)\b", re.I)
# small built-in list of slurs and insults (matched on a normalised, de-leeted copy of the text). Chat messages,
# nicknames and viewer wishes are checked against all of them. Song and video titles (media=True) are real songs and
# videos and are shown as they are (owner, 2026-10-07: "don't censor anything"): only the self-harm prompts still
# refuse one (MEDIA_RE); the guard's adult words, self-harm and money rules apply to them elsewhere. Spaced-out
# letters ("k y s", "n i g g e r") are joined by normalise() before the match.
SELF_HARM = ("kys", "kill yourself", "hang yourself", "neck yourself", "end yourself", "cut yourself", "off yourself",
             "go die", "drink bleach")
HATE_SLURS = ("nigger", "nigga", "faggot", "fag", "kike", "spic", "chink", "gook", "wetback", "tranny", "retard",
              "dyke", "cunt", "whore", "slut")
INSULTS = ("bitch", "bastard", "idiot", "moron", "imbecile", "stupid", "dumbass", "loser", "asshole", "dickhead",
           "motherfucker", "fuck you", "fuck yourself", "fuck u", "fuck off", "stfu", "shut up", "piece of shit",
           "worthless", "pathetic", "ugly")
SLURS = HATE_SLURS + SELF_HARM + INSULTS
_slur_re = lambda words: re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")(s|es|ed|ing|y|ic)?\b")  # noqa: E731
SLUR_RE = _slur_re(SLURS)
MEDIA_RE = _slur_re(SELF_HARM)
# ... and explicit calls to violence against a group, or a slur used as one ("kill all the ...", "death to ...",
# "... must die"; also in Italian and Spanish): never shown, whatever the title (review G24, F1-F4). A title is cut
# into segments (" - ", " | ", brackets, sentence punctuation); a call counts only when its verb opens the segment
# (after an optional "let's" / "we must" ...) and the group word ends it, so "How to Kill Japanese Beetles",
# "Shoot Women's Portraits" or "Lazio slaughter Roma 3-0" are not calls. Nation chants ("death to <country>") are
# left to the owner. Rule-based: a floor, not a classifier.
_EN_GROUPS = ("jew", "jewish people", "muslim", "muslim people", "christian", "arab", "black", "white", "asian",
              "mexican", "immigrant", "migrant", "refugee", "gay", "gay people", "lesbian", "trans people",
              "transgender", "hindu", "sikh", "gypsy", "gypsies", "roma", "african", "chinese", "japanese", "korean",
              "indian", "palestinian", "israeli", "ukrainian", "russian", "atheist", "boer", "afrikaner", "woman",
              "women", "black people", "white people", "asian people")
_IT_GROUPS = ("ebrei", "ebreo", "musulmani", "islamici", "cristiani", "arabi", "neri", "negri", "immigrati", "migranti",
              "profughi", "stranieri", "zingari", "rom", "froci", "gay", "donne", "africani", "cinesi", "terroni")
_ES_GROUPS = ("judios", "judio", "musulmanes", "cristianos", "arabes", "negros", "inmigrantes", "migrantes",
              "refugiados", "gitanos", "maricones", "gays", "mujeres", "moros", "sudacas", "indios", "chinos")


def _alt(words, plural=True):
    return (r"(?:" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + r")"
            + (r"(?:s|es)?" if plural else ""))


_G, _GIT, _GES = _alt(_EN_GROUPS + HATE_SLURS), _alt(_IT_GROUPS, False), _alt(_ES_GROUPS, False)
# the postfix form ("<group> must die") without the bare colour words: "White Will Die?" is a chess line
_GPOST = _alt(tuple(g for g in _EN_GROUPS if g not in ("black", "white")) + ("blacks", "whites") + HATE_SLURS)
_NOW = r"(?:\s+(?:now|today|already|right now|asap|tonight))?"
_CALL = r"(?:(?:lets|let us|we must|we should|we need to|time to|go|just|i want to|i will|we will)\s+)?"
_VERB = (r"(?:kill|killing|burn|burning|gas|gassing|hang|hanging|lynch|lynching|shoot|shooting|exterminate|"
         r"exterminating|slaughter|murder|genocide|nuke|bomb|bombing|stab|massacre|behead|wipe out|eliminate|purge)")
_DET = r"(?:(?:all|all of|every|every single|each)\s+)?(?:(?:the|those|these|them|em)\s+)?"
_DIE = r"(?:die|burn|hang|be (?:killed|gassed|shot|burned|burnt|hanged|exterminated|wiped out))"
INCITE_RE = re.compile("|".join((
    r"^" + _CALL + _VERB + r"\s+" + _DET + _G + _NOW + r"$",                               # kill (all) (the) jews
    r"\bdeath\s+to\s+" + _DET + _G + _NOW + r"$",                                          # death to (all) (the) gays
    r"^(?:all\s+)?(?:the\s+)?" + _GPOST + r"\s+(?:must|should|need to|will|deserve to)\s+(?:all\s+)?" + _DIE + r"$",
    r"^(?:all\s+)?(?:the\s+)?" + _GPOST + r"\s+deserves?\s+(?:death|to die)$",           # <group> deserve death
    r"^(?:uccidi|uccidete|ammazza|ammazzate|brucia|bruciate|impiccate|sterminate|spara|sparate)\s+"
    r"(?:(?:a|ai|agli|alle)\s+)?(?:tutt[ie]\s+)?(?:(?:i|gli|le|quei|quegli)\s+)?" + _GIT + r"$",
    r"\bmorte\s+(?:a|ai|agli|alle)\s+(?:tutt[ie]\s+)?(?:(?:i|gli|le)\s+)?" + _GIT + r"$",
    r"^(?:matar|maten|mata|matad|quemen|quemar|quemad|exterminar|exterminen)\s+(?:a\s+)?(?:tod[oa]s\s+)?"
    r"(?:(?:los|las)\s+)?" + _GES + r"$",
    r"\bmuerte\s+a\s+(?:tod[oa]s\s+)?(?:(?:los|las)\s+)?" + _GES + r"$")))
_SEGMENT = re.compile(r"\s[-|–—]\s|[()\[\]{}\"]+|\s{2,}")          # the parts of a title
_SENTENCE = re.compile(r"[!?.:;]+")                                  # ... and the sentences inside a part


def _segments(text):
    """A title's segments, normalised: accents folded, CamelCase and "-", "_", "/", "#" split into words ("#KillAllX",
    "kill-all-x"), apostrophes dropped ("let's" -> "lets"), a lone "2" read as "to". Each sentence of a part is a
    segment, and so is the part with its stops read as spaces ("kill. all. the. jews"); a comma never cuts ("Kill the
    Indian, Save the Man" is one phrase)."""
    t = fold(text or "")
    t = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", t)
    for part in _SEGMENT.split(t):
        for seg in _SENTENCE.split(part) + [_SENTENCE.sub(" ", part)]:
            seg = re.sub(r"[-_/#,]+", " ", seg.replace("'", "").replace("’", ""))
            seg = normalise(re.sub(r"(?<=\s)2(?=\s)", "to", " " + seg + " "))
            if seg:
                yield seg


def incitement(text):
    """A call to violence against a group (INCITE_RE) in any segment of the title."""
    return any(INCITE_RE.search(s) for s in _segments(text))


LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})


def fold(text):
    """Accents folded, not deleted (review F4: "judíos" -> "judios", not "judos")."""
    t = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text))
    return "".join(c for c in t if not unicodedata.combining(c))


def normalise(text):
    """Lower case, accents folded, leet undone ("sh!t"; a "!" closing a word is just dropped: "kys!"), punctuation and
    digits dropped, a letter repeated 3+ times twice; a run of 3+ single letters is one word ("k y s" -> "kys",
    "n i g g e r" -> "nigger")."""
    t = fold(re.sub(r"!+(?=\s|$)", "", text)).lower().translate(LEET)
    t = re.sub(r"[^a-z\s]", "", t)
    t = re.sub(r"(.)\1{2,}", r"\1\1", re.sub(r"\s+", " ", t)).strip()
    return re.sub(r"\b(?:[a-z] ){2,}[a-z]\b", lambda m: m.group().replace(" ", ""), t)


def dedupe_key(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text).lower())


# the chat is on everyone's screen: trading/"get rich" pushes (lexicon.HYPE, re-exported here), buy advice and coin
# pushes (lexicon.BUY_ADVICE, BUY_PRESSURE: "should I buy sol", "buy this coin now") and adult requests are dropped
# (never stored or shown), like the pages he may read (browse.MONEY_HYPE) - seen live 2026-10-09: "take a look on pump
# fun, and learn how to trade like a pro", "when you wake up, look on fomo", "watch porno". A bare coin name
# ("bitcoin", "memecoin") is refused in a message, a nickname or a taught word (message_blocked) but not here: blocked()
# is also the search filter's core (eyes.query_ok) and "memecoin news" stays a readable search (owner). Song and video
# titles (media=True) refuse HYPE and BUY_ADVICE only ("Get Rich or Die Tryin'", not "Price Tag"). HYPE itself is
# lexicon.HYPE, imported above: the one list every filter shares.
ADULT = re.compile(r"\b(porn\w*|xxx|nsfw|nudes?|naked|sex|sexual|hentai|onlyfans|strip(per|tease)?|blowjob|dick pics?|"
                   r"cum|horny|boobs?|tits|pussy|cock)\b", re.I)


def blocked(text, media=False):
    """Reason string if the message must be dropped, else None. media=True: a song or video title, shown as it is:
    no slur check, only self-harm prompts (MEDIA_RE) and calls to violence against a group (incitement); tickers only as coins
    (MEDIA_TICKER: not "$uicideboy$"), no phone rule (it reads year ranges, "2000 - 2010"), money only as a request (MEDIA_MONEY),
    and of the money lexicon only trading promotion and buy advice (lexicon.money_talk without BUY_PRESSURE)."""
    if URL.search(text):
        return "links are not allowed"
    if SOL_ADDR.search(text) or ETH_ADDR.search(text):
        return "addresses are not allowed"
    if (MEDIA_TICKER if media else TICKER).search(text):
        return "tickers are not allowed"
    if EMAIL.search(text) or not media and PHONE.search(text):
        return "no personal data"
    if (MEDIA_MONEY if media else MONEY).search(text):
        return "no requests for money"
    if (MEDIA_RE if media else SLUR_RE).search(normalise(text)) or media and incitement(text):
        return "insults are not allowed"
    if money_talk(text, chat=not media) or money_talk(normalise(text), chat=not media):     # (also de-leeted)
        return "no trading or get-rich talk"
    if not media and ADULT.search(normalise(text)):
        return "keep it clean"
    return None


def message_blocked(text):
    """blocked() for what viewers put on everyone's screen (a message, a nickname, a taught word): a bare coin name
    (lexicon.COIN_NAMES) is refused too."""
    return blocked(text) or ("no trading or get-rich talk" if money_talk(text, names=True) else None)


# --- message -> stimulus rule table ----------------------------------------------------
POSITIVE = {"love", "loved", "lovely", "happy", "glad", "good", "great", "nice", "beautiful", "wonderful", "amazing",
            "thanks", "thank", "joy", "calm", "peace", "hope", "sweet", "smile", "friend", "kind", "cute", "yay",
            "awesome", "cool", "best", "fun", "hug", "warm", "gm", "gn", "sleep well", "sweet dreams", "welcome"}
HOSTILE = {"hate", "kill", "die", "dead", "death", "attack", "threat", "danger", "dangerous", "hurt", "pain",
           "war", "gun", "blood", "angry", "rage", "destroy", "scared", "fear", "afraid", "scream", "fire",
           "crash", "dump", "rug", "rugged", "panic", "nightmare", "monster", "hunt", "fight"}
QUESTION_START = ("who", "what", "why", "how", "when", "where", "which", "do", "does", "did", "are", "is", "can",
                  "could", "will", "would", "should")
SELF = re.compile(r"\b(sub[\s-]?01|you|your|yours|you're|youre|yourself|u)\b", re.I)

RULES = [  # (condition, {group: drive at gain 1}) - shown on the page as "networks hit"
    ("every message", {"language": 6.0, "somatomotor": 3.0}),
    ("positive words", {"reward": 8.0}),
    ("hostile / threat words", {"fear": 8.0, "salience": 6.0}),
    ("question", {"attention": 6.0, "control": 5.0}),
    ("mentions SUB-01 / you", {"default": 6.0}),
]


def words(text):
    return set(re.findall(r"[a-z']+", text.lower()))


# --- word -> network lexicon (EN/IT) ---------------------------------------------------
# Used to say which networks a topic leans on (curiosity in research.py) next to the rule table above.
# A crude, hand-written association table: it does not model meaning, it only routes words to stimulus groups.
TOPICS = {
    "memory": "memory remember history historical ancient archive museum past heritage century medieval empire "
              "dynasty ruins archaeology tradition childhood nostalgia diary memoria ricordo storia antico museo "
              "passato archivio tradizione",
    "reward": "food bread bakery cake sweet chocolate coffee tea ramen sushi cuisine dish festival game games music "
              "song album dance party holiday gift garden flower cat cats dog dogs pane cibo musica festa gioco "
              "dolce caffe giardino fiore gatto",
    "visual": "art painting painter colour color light photography photograph film cinema animation anime manga "
              "sculpture architecture design image sky star stars moon sun rainbow arte pittura luce foto cielo "
              "stella luna sole colore",
    "somatomotor": "sport sports football baseball soccer swimming running walking cycling bicycle martial dance "
                   "body hand muscle exercise yoga climbing tennis calcio corsa bicicletta corpo mano",
    "language": "language word words poem poetry poet novel book books writer writing literature alphabet "
                "grammar dialect translation script letter lingua parola poesia libro romanzo scrittore",
    "attention": "puzzle chess mathematics math physics science experiment discovery map maps navigation "
                 "telescope microscope astronomy matematica fisica scienza scoperta mappa",
    "control": "logic algorithm computer programming engineering machine rule law system planning economics "
               "strategy logica algoritmo computer ingegneria macchina regola",
    "default": "dream dreams sleep self mind philosophy imagination memory story myth legend soul identity "
               "meditation sogno sonno mente filosofia mito leggenda",
    "limbic": "smell taste perfume emotion mood love friendship family home nostalgia odore gusto emozione "
              "amicizia famiglia casa",
    "salience": "alarm siren noise surprise accident emergency earthquake volcano storm thunder sirena rumore "
                "sorpresa terremoto vulcano tempesta",
    "fear": "danger predator shark storm earthquake volcano tsunami ghost monster pericolo squalo fantasma mostro",
    "relay": "signal radio telephone network broadcast sensor neuron neurons brain segnale radio cervello",
}
TOPIC = {}
for _g, _ws in TOPICS.items():
    for _w in _ws.split():
        if _g not in TOPIC.setdefault(_w, []):
            TOPIC[_w].append(_g)


def networks_for(text):
    """-> {group: weight}: words of `text` routed through the rule words (POSITIVE / HOSTILE) and TOPICS."""
    out = {}
    for w in re.findall(r"[a-zà-ÿ']+", text.lower()):
        groups = TOPIC.get(w) or TOPIC.get(w[:-1] if w.endswith("s") else "") or []
        if w in POSITIVE:
            groups = groups + ["reward"]
        if w in HOSTILE:
            groups = groups + ["fear", "salience"]
        for g in groups:
            out[g] = out.get(g, 0.0) + 1.0
    return out


def stimulus(text):
    """-> ({group: drive}, [groups hit], emotion tag). Drives are before the sleep-stage gain."""
    w = words(text)
    low = " " + " ".join(re.findall(r"[a-z']+", text.lower())) + " "
    pos = bool(w & POSITIVE) or any(f" {p} " in low for p in POSITIVE if " " in p)
    hos = bool(w & HOSTILE)
    q = "?" in text or text.strip().lower().split(" ", 1)[0] in QUESTION_START
    fired = [True, pos, hos, q, bool(SELF.search(text))]
    stim = {}
    for on, (_, groups) in zip(fired, RULES):
        if on:
            for g, a in groups.items():
                stim[g] = stim.get(g, 0.0) + a
    emotion = "threat" if hos else "positive" if pos else "neutral"
    return stim, list(stim), emotion


# --- limits --------------------------------------------------------------------------
class RateLimiter:
    """1 message per RATE_S per client key. Keys (IPs) are forgotten as soon as the window passes."""

    def __init__(self, window=RATE_S, clock=time.monotonic):
        self.window, self.clock, self.last = window, clock, {}

    def allow(self, key):
        now = self.clock()
        self.last = {k: t for k, t in self.last.items() if now - t < self.window}   # purge old IPs
        if key in self.last:
            return False
        self.last[key] = now
        return True


class Dedupe:
    """Drops a message identical (after normalising) to one of the recent accepted ones."""

    def __init__(self, n=200):
        self.recent = deque(maxlen=n)

    def seen(self, text):
        k = dedupe_key(text)
        if k in self.recent:
            return True
        self.recent.append(k)
        return False


def check(text, key, limiter, dedupe):
    """Full pipeline for one incoming message -> (ok, reason). Filter first, then limits."""
    text = (text or "").strip()
    if not text:
        return False, "empty"
    reason = message_blocked(text)
    if reason:
        return False, reason
    if len(text) > MAX_LEN:
        return False, f"max {MAX_LEN} characters"
    if not limiter.allow(key):
        return False, f"one message every {RATE_S:.0f} s"
    if dedupe.seen(text):
        return False, "duplicate"
    return True, None


# --- "teach him something" (#31) -------------------------------------------------------
TEACH_MAX_WORDS = 6
NICK_MAX = 16
TEACH_PER_DAY = 30          # taught items per Tokyo day in total, first come


def clean_nick(nick):
    """-> (nickname or "", reason or None). Display only, never a stimulus; the same rules as a chat message."""
    nick = re.sub(r"\s+", " ", (nick or "")).strip()
    if not nick:
        return "", None
    if len(nick) > NICK_MAX:
        return "", f"nickname: max {NICK_MAX} characters"
    reason = message_blocked(nick)
    return ("", "nickname: " + reason) if reason else (nick, None)


class TeachLimits:
    """One teach per viewer per day (keyed like the chat limiter: the client address, kept only in memory and only
    for the current day) and at most `per_day` taught items per day in total. The day's total is also written to
    `path` (state_io, atomic), so a restart cannot reopen the cap; viewer keys are never written to disk."""

    def __init__(self, per_day=TEACH_PER_DAY, path=None):
        self.per_day, self.path = per_day, path
        self.day, self.keys, self.count = None, set(), 0
        if path is not None:
            d = load_json(path, {})
            if isinstance(d.get("day"), str) and isinstance(d.get("count"), int):
                self.day, self.count = d["day"], d["count"]

    def _roll(self, day):
        if day != self.day:
            self.day, self.keys, self.count = day, set(), 0

    def check(self, key, day, taught_today):
        """`taught_today`: texts already taught that day. -> reason or None (does not record anything)."""
        self._roll(day)
        if key in self.keys:
            return "one teach per viewer per day"
        if max(self.count, len(taught_today)) >= self.per_day:
            return f"he has been taught {self.per_day} things today; try again tomorrow"
        return None

    def note(self, key, taught_today=()):
        self.keys.add(key)
        self.count = max(self.count, len(taught_today)) + 1
        if self.path is not None:
            save_json(self.path, {"day": self.day, "count": self.count})


def check_teach(text, nick, key, limits, day, taught_today):
    """Full pipeline for one taught word or phrase -> (ok, reason, text, nick). Filter first, then limits."""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return False, "empty", "", ""
    reason = message_blocked(text)
    if reason:
        return False, reason, "", ""
    if len(text.split()) > TEACH_MAX_WORDS:
        return False, f"max {TEACH_MAX_WORDS} words", "", ""
    if len(text) > 80:
        return False, "too long", "", ""
    nick, reason = clean_nick(nick)
    if reason:
        return False, reason, "", ""
    if dedupe_key(text) in {dedupe_key(x) for x in taught_today}:
        return False, "already taught today", "", ""
    reason = limits.check(key, day, taught_today)
    if reason:
        return False, reason, "", ""
    limits.note(key, taught_today)
    return True, None, text, nick
