"""Dream diary: SUB-01's nights, written down even when nobody is watching.

During REM the eye renders a dream frame every DREAM_EVERY_S of simulated time (at most MAX_UNATTENDED per
night without viewers, so the cost stays at a few cents a night). Frames seen live by viewers during REM are
added too. When the night closes (natural wake-up), the diary gets a short title + text written by the language
model from the dream scenes, the replayed chat messages and the titles of articles it read that day and replayed,
plus a ready-to-post share text. Nothing is posted anywhere automatically. Replays of chat messages and of
readings are listed apart ("read that day · replayed that night").

data/diary/<night date>.json   one file per night
data/diary/img/<date>/*.jpg    the night's frames (kept apart from the eye's rolling frame buffer)

Dreams are AI-generated from the model's state and from REM replays of chat messages and readings. They are not the
real person's dreams, and nothing here claims the model dreams in the way a person does or understands what it read.
"""
import json
import re
import shutil
import time
from pathlib import Path

from state_io import load_json, save_json

DREAM_EVERY_S = 6 * 60          # simulated seconds between unattended dream frames
MIN_REAL_GAP_S = 20             # never faster than this in real seconds (accelerated clocks)
MAX_UNATTENDED = 18             # unattended frames per night (~$0.003 each on FLUX schnell)
KEEP_IMG_NIGHTS = 120           # nights whose images are kept on the volume
SHARE_MAX = 280
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

READ_VERB = {"video": "watched", "short": "watched", "forum": "read", "news": "read", "wiki": "read",
             "finance": "looked at", "page": "read"}           # #79: a reading's verb by the kind of page it was

SYSTEM = """You write the morning entry of a dream diary for SUB-01, a simulated brain model built from public MRI scans.
You receive JSON: the dream scenes the model's image generator produced during REM, the chat messages it replayed,
the titles of encyclopedia articles it read during the day and replayed, and when it slept; read_notes and
conversations are what an AI noted for it that day (page summaries, chat lines and the replies an AI wrote);
music is the genres of the tracks its brain model picked that day and the one playing when it fell asleep.
Reply with JSON only: {"title": "...", "text": "..."}
- title: max 8 words, English, evocative, no quotes, no hashtags.
- text: 2-3 sentences, max 60 words, English, third person ("SUB-01 dreamt..."), concrete images from the scenes,
  weave in the replayed messages; replayed_articles, read_notes and conversations may appear only as images, places
  or a line of talk, never as facts it learned or things it felt; music only as a sound or a mood, never as liking.
  Calm, precise, a little strange.
- Never say or imply that SUB-01 is conscious, alive, sentient, human or a person, or the person the scans came
  from. No money, prices, tokens, buying or selling. No people's names."""

# What may not stand in a diary line: claims of a mind, money / trading words, adult words, links, handles. Money stems
# have \b on both sides, so "dumpling", "pumpkin", "buying bread" pass and "buy now", "the coin", "a chart" go; "he" and
# "she" pass (2026-10-09: every entry with a pronoun fell back to the template). Local for now: when lexicon.py (S3)
# lands, the money part should come from its HYPE / BUY_ADVICE lists.
BLOCK = re.compile(
    r"conscious|sentien|\balive\b|self.?aware|\bsoul\b|\bhuman\b|\breal person\b|"
    r"\bbuy\b|\bsell\b|\bprices?\b|\btokens?\b|\bcoins?\b|\bmoney\b|\bpump(s|ed|ing)?\b|\bdump(s|ed|ing)?\b|"
    r"\bcrypto\w*|\bbitcoin\b|\bmemecoins?\b|\btrad(e|es|ing|er|ers)\b|\bmarkets?\b|\bcharts?\b|\bprofits?\b|"
    r"\binvest\w*|\bwallets?\b|\bstocks\b|\bstock (market|exchange|tips?)\b|\bticker\b|\bsex\b|\bnudes?\b|\bporn\w*|\bnaked\b|"
    r"\$|https?://|www\.|@\w", re.I)
SENTENCE = re.compile(r"(?<=[.!?\u2026])\s+")
_NO_ASK_LOGGED = False


def clean_line(s, limit):
    """One diary line, safe to show: the sentences that hit BLOCK are dropped (the rest stays: one bad image no longer
    costs the whole entry), then cut at the last full sentence that fits `limit`."""
    s = re.sub(r"\s+", " ", str(s or "")).strip().strip('"').strip()
    s = " ".join(x for x in SENTENCE.split(s) if x and not BLOCK.search(x)).strip()
    if not s:
        return ""
    if len(s) > limit:                                 # cut at the last full sentence that fits
        cut = s[:limit]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        s = cut[:end + 1] if end > limit // 3 else cut.rsplit(" ", 1)[0] + "\u2026"
    return s


def music_facts(rows):
    """Tracks its brain model picked that day (music.Music.day rows) -> a few facts for the entry, or None. Genres and
    titles only: artists are people's names and stay out of the diary."""
    rows = [r for r in rows if isinstance(r, dict) and r.get("title")]
    if not rows:
        return None
    counts = {}
    for r in rows:
        g = r.get("genre_label") or "music"
        counts[g] = counts.get(g, 0) + 1
    last = rows[-1]
    return {"tracks": len(rows), "genres": sorted(counts, key=lambda g: -counts[g])[:3],
            "last": str(last["title"])[:80], "asleep_genre": (last.get("genre_label") or "music")
            if last.get("ended") == "fell asleep" else None}


def music_line(m):
    if not m:
        return ""
    n = m["tracks"]
    line = f" Its brain model picked {n} track{'s' * (n != 1)} that day, mostly {m['genres'][0]}"
    return line + (f"; it fell asleep after {m['asleep_genre']}." if m["asleep_genre"] else ".")


class Diary:
    def __init__(self, root, frames_dir):
        self.dir = Path(root) / "diary"
        self.img = self.dir / "img"
        self.img.mkdir(parents=True, exist_ok=True)
        self.frames_dir = Path(frames_dir)
        self.last_real = 0.0

    # --- storage -------------------------------------------------------------
    def path(self, date):
        if not DATE.match(str(date)):
            raise ValueError("bad date")
        return self.dir / f"{date}.json"

    def load(self, date):
        p = self.path(date)
        return load_json(p)                            # a torn night is kept aside and starts again

    def save(self, d):
        p = self.path(d["date"])
        save_json(p, d, indent=1, ensure_ascii=False)

    def entry(self, date):
        return self.load(date) or {"date": date, "frames": [], "unattended": 0, "last_sim": 0.0, "closed": False}

    # --- during the night ----------------------------------------------------
    def due(self, engine, t_sim, now_real=None):
        """True when an unattended dream frame should be rendered now."""
        now_real = time.time() if now_real is None else now_real
        if engine.stage != "REM" or engine.night is None or not DATE.match(str(engine.night.get("date"))):
            return False                               # (a nap's record, "<day>-nap-<HHMM>", is not a diary night)
        d = self.entry(engine.night["date"])
        return (d["unattended"] < MAX_UNATTENDED and t_sim - d["last_sim"] >= DREAM_EVERY_S
                and now_real - self.last_real >= MIN_REAL_GAP_S)

    def add(self, date, rec, t_sim, attended):
        """Keep a REM frame in the night's entry (its image is copied out of the eye's rolling buffer)."""
        if rec.get("reused") or rec.get("stage") != "REM" or not DATE.match(str(date)):
            return None
        d = self.entry(date)
        src = self.frames_dir / Path(rec["img"]).name
        if not src.exists():
            return None
        (self.img / date).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, self.img / date / src.name)
        d["frames"].append({"t": rec["t"], "img": f"/diary-img/{date}/{src.name}", "thought": rec.get("thought", ""),
                            "scene": rec.get("scene", ""), "replayed": (rec.get("why") or {}).get("replayed", []),
                            "articles": (rec.get("why") or {}).get("replayed_articles", []),
                            "attended": bool(attended)})
        d["last_sim"] = t_sim
        if not attended:
            d["unattended"] += 1
            self.last_real = time.time()
        self.save(d)
        print(f"diary: dream frame {len(d['frames'])} of {date}" + ("" if attended else " (unattended)"), flush=True)
        return d

    # --- in the morning --------------------------------------------------------
    def pending_close(self, engine):
        """Date of a finished night whose diary entry is still open, else None."""
        n = engine.last_night
        if not n or (engine.night is not None and engine.night.get("date") == n["date"]):
            return None
        if not n.get("sleep_onset") or n.get("kind", "night") != "night" or not DATE.match(str(n["date"])):
            return None                                # stayed awake all night, or a nap: nothing to write
        d = self.load(n["date"])
        return None if d and d["closed"] else n["date"]

    def close(self, night, llm=None, read_today=(), notes=None):
        """Write title, text and share text for a finished night. `llm.ask(system, user)` is optional.
        `read_today` = [{title, url}] of the articles read during the day before this night; `notes` =
        mind.Mind.day_notes(date): {read: [summaries], topics: [...], talked: [{who, said, reply}]} (optional)."""
        notes = notes or {}
        music = music_facts(notes.get("music") or [])
        d = self.entry(night["date"])
        allr = night.get("replays", [])
        replays = [r["text"] for r in allr if r.get("source", "chat") == "chat"]
        taught = [r["text"] for r in allr if r.get("source") == "taught"]       # words viewers taught: counted apart
        counts, rcounts = {}, {}
        for x in replays:
            counts[x] = counts.get(x, 0) + 1
        for r in allr:
            if r.get("source") == "reading":
                rcounts[r["text"]] = rcounts.get(r["text"], 0) + 1
        # quoted in the entry and the share text: only lines that pass the diary's own filter (viewers wrote them)
        top = [x for x in sorted(counts, key=lambda x: -counts[x]) if clean_line(x, 90)][:5]
        today = {}
        for a in read_today:                            # #79: pages he stayed on (kind: video, short, forum, news, ...)
            today.setdefault(a["title"], {"title": a["title"], "url": a.get("url", ""), "replayed": 0, "today": True,
                                          "kind": a.get("kind", "wiki"), "host": a.get("host", ""),
                                          "verb": READ_VERB.get(a.get("kind", "wiki"), "read")})
        for title, n in rcounts.items():
            today.setdefault(title, {"title": title, "url": "", "replayed": 0, "today": False})["replayed"] = n
        read = sorted(today.values(), key=lambda a: (-a["replayed"], not a["today"]))[:30]
        top_read = [a["title"] for a in read if a["replayed"] and clean_line(a["title"], 80)][:3]
        facts = {"sleep_onset": (night.get("sleep_onset") or "")[-5:], "woke_up": (night.get("woke_up") or "")[-5:],
                 "wakeups": len(night.get("wakeups", [])), "replays": len(replays), "top_replayed": top,
                 "taught_replays": len(taught), "reading_replays": sum(rcounts.values()), "read": read,
                 "dream_frames": len(d["frames"]), "read_topics": list(notes.get("topics", []))[:5],
                 "conversations": len(notes.get("talked", [])), **({"music": music} if music else {})}
        title = text = ""
        if llm is not None and not hasattr(llm, "ask"):   # a local model object (mlx) has no ask(): template text
            global _NO_ASK_LOGGED
            if not _NO_ASK_LOGGED:
                print("diary: this language model has no ask(); template text", flush=True)
                _NO_ASK_LOGGED = True
            llm = None
        if llm is not None and d["frames"]:
            user = json.dumps({"scenes": [f["scene"] for f in d["frames"] if f["scene"]][-12:],
                               "replayed_messages": top, "replayed_articles": top_read,
                               "read_notes": list(notes.get("read", []))[:5],
                               "conversations": [f"{c.get('who', 'a viewer')}: {c.get('said', '')[:120]} / "
                                                 f"reply: {c.get('reply', '')[:160]}" for c in notes.get("talked", [])[:3]],
                               "slept": f"{facts['sleep_onset']}-{facts['woke_up']}",
                               **({"music": {"genres": music["genres"], "fell_asleep_to": music["asleep_genre"]}}
                                  if music else {})})
            for _ in range(2):                         # one retry: small models sometimes break the JSON
                try:
                    raw = llm.ask(SYSTEM, user)
                    m = re.search(r"\{.*?\}", raw, re.S)
                    out = json.loads(m.group(0)) if m else {}
                    title, text = clean_line(out.get("title"), 80), clean_line(out.get("text"), 420)
                except Exception as e:                 # the diary must never break on a provider error
                    print("diary: summary failed:", repr(e)[:160], flush=True)
                if title and text:
                    break
                print("diary: summary rejected or empty", flush=True)
        if not text:
            text = (f"SUB-01 slept {facts['sleep_onset']}-{facts['woke_up']} and replayed {len(replays)} "
                    f"message{'s' * (len(replays) != 1)} during REM" +
                    (f", most often “{clean_line(top[0], 80)}”." if top else ".") +
                    (f" It also replayed {len(taught)} of the words viewers taught it." if taught else "") +
                    (f" It also replayed {facts['reading_replays']} of the things it read or watched, such as "
                     f"“{clean_line(top_read[0], 80)}” ({today.get(top_read[0], {}).get('verb', 'read')} that day)."
                     if top_read else "") +
                    (f" That day it read about {', '.join(facts['read_topics'][:3])}." if facts["read_topics"] else "") +
                    music_line(music))
        d.update(title=title or f"Night of {night['date']}", text=text, facts=facts, closed=True,
                 share=self.share(night["date"], title, facts), closed_at=time.time())
        self.save(d)
        self.prune()
        return d

    @staticmethod
    def share(date, title, facts):
        lines = [f"SUB-01 · night of {date}" + (f" — {title}" if title else ""),
                 f"Slept {facts['sleep_onset']}–{facts['woke_up']} Tokyo time"
                 + (f", woke {facts['wakeups']}x" if facts["wakeups"] else "") + "."]
        if facts["replays"]:
            lines.append(f"In REM it replayed {facts['replays']} of your messages.")
            quoted = [clean_line(x, 90) for x in facts["top_replayed"]]
            if any(quoted):                            # (viewers' words: the diary's filter, like the entry)
                lines.append(f"Most often: “{next(q for q in quoted if q)}”")
        read = [clean_line(a["title"], 70) for a in facts.get("read", []) if a["replayed"]]
        if any(read):
            lines.append(f"It also replayed what it read: “{next(r for r in read if r)}”.")
        lines.append("A model of brain activity, not a mind.")
        out = "\n".join(lines)
        while len(out) > SHARE_MAX and len(lines) > 2:
            lines.pop(-2)
            out = "\n".join(lines)
        return out[:SHARE_MAX]

    def prune(self):
        dirs = sorted(p for p in self.img.iterdir() if p.is_dir())
        for p in dirs[:-KEEP_IMG_NIGHTS]:
            shutil.rmtree(p, ignore_errors=True)

    # --- api -------------------------------------------------------------------
    def index(self, n=30):
        out = []
        for p in sorted(self.dir.glob("*.json"), reverse=True)[:n]:
            d = load_json(p)
            if d is None or "date" not in d or "frames" not in d:
                continue
            out.append({"date": d["date"], "title": d.get("title", ""), "closed": d.get("closed", False),
                        "frames": len(d["frames"]), "cover": d["frames"][len(d["frames"]) // 2]["img"] if d["frames"] else None})
        return out
