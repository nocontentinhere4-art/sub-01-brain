"""The Eye: what SUB-01 "sees" — a persistent world built from chat, rendered through the brain's state.

- World: things people mention become objects in SUB-01's world. Each mention strengthens an object; objects
  fade with time (half-life WORLD_HALF_LIFE_H of simulated time) and are forgotten below a floor.
- Every frame, a small language model turns (sleep stage, network activity, what he is doing, world, recent
  messages, REM replays) into a first-person scene description + one short "thought". An image model
  renders the scene. Awake = clear and realistic, REM = surreal dream remix, NREM = near-dark.
- Scene, thought and world objects pass the same filters as the chat and his replies (scene_ok / thought_ok /
  object_ok): no money or trading images, no claims of a mind or a body. A refused scene gets a neutral view of the
  room; a refused thought is left blank.
- Everything is logged with its inputs ("why"), so each frame can be traced back to messages and state.
- The image is reused (no FLUX call) when the scene did not change from the last frame; when the image call fails
  the previous frame is returned as it was ("resting its eyes"), never a new caption over an old picture.

Images and thoughts are AI-generated from the model's state. They are not what the real person saw or thought.
"""
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from state_io import append_jsonl, load_json, read_jsonl, save_json

WORLD_HALF_LIFE_H = 6.0            # simulated hours for an object's strength to halve
FORGET_BELOW = 0.15
MAX_OBJECTS = 40
KEEP_FRAMES = 600
LLM_ID = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
HOME = "a small minimal apartment: a bed, a table, a desk with a monitor, one window over a quiet street"

SYSTEM = """You write the inner view of SUB-01, a simulated brain built from public MRI scans.
You receive its current state as JSON. Reply with JSON only:
{"new_objects": [{"said": "...", "en": "..."}], "scene": "...", "thought": "..."}
- new_objects: up to 3 concrete, drawable things (nouns, 1-3 words, English) mentioned in recent_messages that are
  not already in world. Skip abstract words, people, brands, tickers, coins, money.
- new_objects: "said" = the exact words used in the message (any language), "en" = English name. Never invent.
- scene: one first-person view (max 45 words, English) of exactly what it sees while "doing" that activity
  (the bakery counter, the park bench, the phone screen in bed, the page on the monitor...). Include the strongest
  world objects when they fit; in dreams, the place melts into the replayed messages and replayed_articles
  (titles of encyclopedia articles it read that day: use them only as images or places, never as written text).
  Follow the style: awake = coherent, realistic, lighting from mood; rem = surreal dream mixing the replayed
  messages, impossible geometry; nrem = almost black, slow blurred shapes. Never draw people's faces, text,
  logos, violence, nudity or real persons.
- thought: one short inner line (max 16 words), always in English (even when the messages are in another language),
  reacting to what it sees. It is a brain without a body: no heart, hands or breath. Never ask for money, never tell anyone to buy or sell, never claim to be human,
  conscious, or the real person the scans came from."""

STYLE = {
    "AWAKE": "first-person view, photoreal, cinematic, natural perspective, 35mm",
    "REM": "first-person dream, surreal, dreamlike, soft glow, impossible architecture, film grain",
    "NREM": "almost completely dark, slow blurred abstract shapes, deep blue and black, very low light",
}
BAD = re.compile(r"https?://|www\.|\$[a-z]{2,10}\b|[1-9A-HJ-NP-Za-km-z]{32,44}|0x[0-9a-f]{40}", re.I)
# what the eye may not draw or think (S7): money / trading images, a mind or a body. Local for now; the money part
# should come from lexicon.py (S3: HYPE / BUY_ADVICE) once it lands, like chat.HYPE and diary.BLOCK.
VISUAL_BLOCK = re.compile(
    r"\b(charts?|candles?|candlesticks?|prices?|coins?|crypto\w*|tokens?|trad(e|es|ing|er|ers)|tickers?|bitcoin|"
    r"memecoins?|invest\w*|profits?|buy (now|the dip)|conscious\w*|sentien(t|ce)|alive|humans?|real person|"
    r"heart(beat)?s?|breath\w*|hands?|fingers?|my body)\b", re.I)
NEUTRAL_SCENE = {
    "AWAKE": "the apartment, soft daylight on clean surfaces: {doing}",
    "REM": "the apartment with its walls bending slowly, soft glow, no clear edges",
    "NREM": "near darkness, slow blurred shapes, deep blue",
}
SAME_SCENE = 0.8                   # word-set overlap (Jaccard) at or above which two scenes count as the same view


def shared_blocked(text):
    """The checks every public text of his goes through: the chat filter (links, tickers, money asks, hype, adult),
    the reply rule against claims of feeling / being human (mind.CLAIM), and the eye's visual list. Lazy imports:
    mind pulls in the browser modules."""
    t = str(text or "")
    if not t.strip():
        return None
    if VISUAL_BLOCK.search(t) or BAD.search(t):
        return "money, mind or body words"
    from chat import blocked
    if blocked(t):
        return "chat filter"
    from mind import CLAIM
    if CLAIM.search(t):
        return "claims to feel or to be human"
    return None


def scene_ok(scene):
    return shared_blocked(scene) is None


def thought_ok(thought):
    return shared_blocked(thought) is None


def object_ok(name):
    """A world object's name ("said" or "en" as the model gave it): BAD on the raw text (tickers, addresses, links -
    checked before any character is stripped), then the shared filter."""
    raw = str(name or "")
    return bool(raw.strip()) and not BAD.search(raw) and "$" not in raw and shared_blocked(raw) is None


def neutral_scene(stage, doing=""):
    """The scene used when the model's was refused: the room and what he is doing, nothing from the model."""
    return NEUTRAL_SCENE.get(stage, NEUTRAL_SCENE["AWAKE"]).format(doing=doing or HOME)


def same_scene(a, b):
    wa, wb = set(re.findall(r"[a-z]{3,}", str(a).lower())), set(re.findall(r"[a-z]{3,}", str(b).lower()))
    if not wa or not wb:
        return a == b
    return len(wa & wb) / len(wa | wb) >= SAME_SCENE


class World:
    def __init__(self, d=None):
        d = d or {}
        self.objects = d.get("objects", {})             # name -> {w, first, last, text}

    def strength(self, o, t):
        return o["w"] * 0.5 ** (max(0.0, t - o["last"]) / 3600 / WORLD_HALF_LIFE_H)

    def add(self, names, t, source_text):
        for n in names[:3]:
            if not object_ok(n):                       # on the raw name: "$PEPE" and an address never got this far
                continue                               # before (the characters BAD looks for were stripped first)
            n = re.sub(r"[^a-zA-ZÀ-ſ \-]", "", str(n)).strip().lower()[:30]
            if not n:
                continue
            o = self.objects.get(n)
            if o:
                o["w"] = self.strength(o, t) + 1.0
                o["last"] = t
            else:
                self.objects[n] = {"w": 1.0, "first": t, "last": t, "text": source_text[:120]}
        self.forget(t)

    def forget(self, t):
        live = {k: v for k, v in self.objects.items() if self.strength(v, t) >= FORGET_BELOW}
        keep = sorted(live, key=lambda k: -self.strength(live[k], t))[:MAX_OBJECTS]
        self.objects = {k: live[k] for k in keep}

    def top(self, t, k=6):
        items = sorted(self.objects.items(), key=lambda kv: -self.strength(kv[1], t))[:k]
        return [{"name": n, "strength": round(self.strength(o, t), 2)} for n, o in items]

    def to_dict(self):
        return {"objects": self.objects}


def mood(groups, stage, market=None):
    """Readable summary of the brain state that the language model conditions on. `market` is accepted and ignored
    (the trading terminal is gone: no market mood reaches the eye, the frame log or the page)."""
    g = groups or {}
    base = sum(g.values()) / max(1, len(g))

    def rel(k):
        return round(g.get(k, base) / max(base, 1e-6), 2)

    return {"stage": stage.lower(), "reward": rel("reward"), "fear": rel("fear"), "salience": rel("salience"),
            "attention": rel("attention"), "self": rel("default"), "language": rel("language")}


def load_env(path):
    """Read KEY=VALUE lines from a local, git-ignored .env into os.environ (never printed or logged)."""
    p = Path(path)
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def replicate_post(url, token, payload, tries=5, poll_s=240, timeout=60):
    """POST a prediction, waiting on 429s (low-credit accounts are limited to ~6 requests/min, burst 1)."""
    body = json.dumps(payload).encode()
    for i in range(tries):
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "wait=30"})
        try:
            out = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == tries - 1:
                raise
            time.sleep(float(e.headers.get("Retry-After") or 0) or 10 * (i + 1))
            continue
        # "Prefer: wait" can return before the model is done (cold start): poll the prediction until it ends
        deadline = time.time() + poll_s
        while out.get("status") in ("starting", "processing") and time.time() < deadline:
            time.sleep(1.5)
            get = urllib.request.Request(out["urls"]["get"], headers={"Authorization": f"Bearer {token}"})
            out = json.loads(urllib.request.urlopen(get, timeout=30).read())
        return out


class ReplicateImages:
    """FLUX schnell on Replicate: ~1-2 s per image, nothing runs on this Mac's GPU."""
    URL = "https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions"

    def __init__(self, token):
        self.token = token

    def generate(self, prompt, seed, width, height):
        from io import BytesIO

        from PIL import Image
        out = replicate_post(self.URL, self.token, {"input": {
            "prompt": prompt, "seed": seed, "aspect_ratio": "16:9", "num_outputs": 1,
            "output_format": "jpg", "output_quality": 88, "go_fast": True}})
        if out.get("status") != "succeeded" or not out.get("output"):
            raise RuntimeError(f"replicate: {out.get('status')} {str(out.get('error'))[:200]}")
        url = out["output"][0] if isinstance(out["output"], list) else out["output"]
        return Image.open(BytesIO(urllib.request.urlopen(url, timeout=60).read())).resize((width, height))


class ReplicateLLM:
    """Thoughts via Llama 3 8B on Replicate (~2-3 s): no local GPU, runs anywhere."""
    URL = "https://api.replicate.com/v1/models/meta/meta-llama-3-8b-instruct/predictions"

    def __init__(self, token):
        self.token = token
        self.last_usage = None                           # (tokens in, tokens out) of the last call, for the ledger

    def ask(self, system, user):
        self.last_usage = None
        res = replicate_post(self.URL, self.token, {"input": {
            "system_prompt": system, "prompt": user, "max_tokens": 260, "temperature": 0.7}})
        out = res.get("output") or ""
        out = "".join(out) if isinstance(out, list) else str(out)
        m = res.get("metrics") or {}
        self.last_usage = (int(m.get("input_token_count") or len(system + user) // 4),
                           int(m.get("output_token_count") or len(out) // 4))
        return out


class Eye:
    def __init__(self, out_dir, world_path, width=768, height=432, steps=8, quantize=4):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.world_path = Path(world_path)
        self.world = World(load_json(self.world_path))
        self.size, self.steps, self.quantize = (width, height), steps, quantize
        self.heard = []                                  # recent accepted messages (text, t)
        self.absorbed = set()                            # messages already turned into world objects
        self.llm = self.tok = self.img = None
        self.log = self.out / "frames.jsonl"
        self.ledger = None                               # costs.Ledger (live_server): caps + logs the Replicate calls
        self.last_rec = self._last_logged()              # the previous frame (scene, thought, image): reused, see step
        self.refused = {"scene": 0, "thought": 0, "objects": 0}   # how often the filters stepped in (status, tests)

    def _last_logged(self):
        rows = read_jsonl(self.log, last=1)
        rec = rows[-1] if rows and isinstance(rows[-1], dict) else None
        return rec if rec and rec.get("img") and (self.out / Path(rec["img"]).name).exists() else None

    # called from the server whenever a chat message is accepted
    def hear(self, text, t):
        self.heard.append((text, t))
        self.heard = self.heard[-12:]

    def _load(self):
        if self.llm is None and os.environ.get("REPLICATE_API_TOKEN"):
            self.llm = ReplicateLLM(os.environ["REPLICATE_API_TOKEN"])
        if self.llm is None:
            from mlx_lm import load
            self.llm, self.tok = load(LLM_ID)
        if self.img is None and os.environ.get("REPLICATE_API_TOKEN"):
            self.img = ReplicateImages(os.environ["REPLICATE_API_TOKEN"])
        if self.img is None:
            from mflux.models.common.resolution.config_resolution import ConfigResolution
            from mflux.models.z_image.variants.z_image import ZImage
            self.img = ZImage(model_config=ConfigResolution.resolve_restricted("z-image-turbo", "z-image-turbo",
                                                                               model_path=None),
                              quantize=self.quantize, model_path=None)

    def _ask(self, state):
        if isinstance(self.llm, ReplicateLLM):
            raw = self._paid_llm(SYSTEM, json.dumps(state))
        else:
            from mlx_lm import generate
            msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(state)}]
            prompt = self.tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
            raw = generate(self.llm, self.tok, prompt=prompt, max_tokens=220)
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            out = json.loads(m.group(0)) if m else {}
        except ValueError:
            out = {}
        scene = str(out.get("scene", ""))[:400]
        thought = str(out.get("thought", ""))[:140]
        if scene and not scene_ok(scene):               # refused: a neutral view of the room instead (step)
            self.refused["scene"] += 1
            scene = ""
        if thought and not thought_ok(thought):         # refused: no thought on this frame
            self.refused["thought"] += 1
            thought = ""
        raw_objects = out.get("new_objects") if isinstance(out.get("new_objects"), list) else []
        objects = [o for o in raw_objects if isinstance(o, dict)       # both names through the shared check
                   and object_ok(o.get("said")) and (not o.get("en") or object_ok(o.get("en")))]
        self.refused["objects"] += len(raw_objects) - len(objects)
        return objects, scene, thought

    def _check(self):
        """Before every paid call: over the eye's or the total daily cap raises costs.Capped (the server keeps the
        last frame)."""
        if self.ledger is not None:
            self.ledger.check("eye")

    def _paid_llm(self, system, user):
        import costs
        self._check()
        try:
            return self.llm.ask(system, user)
        finally:
            if self.ledger is not None:
                tin, tout = self.llm.last_usage or (len(system + user) // 4, 0)
                self.ledger.record("eye", "meta/meta-llama-3-8b-instruct", tin + tout, costs.llm_usd(tin, tout), "thought")

    def step(self, t, stage, groups, market=None, replays=(), sim_hhmm="", doing="", articles=()):
        """One frame. Blocking (runs in a worker thread): returns the frame record. `market` is accepted for the
        caller and ignored (see mood). The image is made only when the scene changed from the last frame (same stage,
        word overlap under SAME_SCENE): otherwise the last image is kept and only the thought is new (and billed).
        When the image call fails the previous record comes back as it was, marked resting: a caption never changes
        over an old picture, no new frame is written."""
        self._load()
        replays = list(dict.fromkeys(list(replays)[-4:]))          # the same line replayed twice is one image
        recent = [x for x, ts in self.heard if t - ts < 3 * 3600][-5:]
        state = {"time": sim_hhmm, "home": HOME, "doing": doing, **mood(groups, stage), "world": self.world.top(t),
                 "recent_messages": recent, "replayed_messages": replays}
        if articles:
            state["replayed_articles"] = list(articles)[-3:]
        new, scene, thought = self._ask(state)
        if not scene:                                    # the model's scene was empty or refused: the room, as it is
            scene = neutral_scene(stage, doing)
        fresh = [x for x, ts in self.heard if t - ts < 3 * 3600 and x not in self.absorbed]
        if fresh:                                        # a message shapes the world once; objects must come from it
            said = " ".join(fresh).lower()
            keep = [o.get("en") or o.get("said") for o in new
                    if isinstance(o, dict) and o.get("said") and str(o["said"]).lower().strip() in said]
            self.world.add(keep, t, fresh[-1])
            self.absorbed.update(fresh)
        style = STYLE.get(stage, STYLE["AWAKE"])
        # image models ignore "no X": describe the absence positively instead
        prompt = f"{scene}. {style}. uninhabited scene, empty of humans, seen through the viewer's own eyes, clean surfaces without writing"
        t0 = time.time()
        last = self.last_rec if self.last_rec and (self.out / Path(self.last_rec["img"]).name).exists() else None
        why = {"messages": recent, "replayed": replays, "replayed_articles": list(articles)[-3:],
               "world": self.world.top(t, 5), "mood": {k: state[k] for k in ("reward", "fear", "salience")}}
        if last and last.get("stage") == stage and same_scene(last.get("scene", ""), scene):
            # the view did not change: the same image, a new thought; nothing is rendered or darkened again
            rec = {"t": sim_hhmm, "stage": stage, "img": last["img"], "thought": thought, "scene": scene, "why": why,
                   "render_s": round(time.time() - t0, 1), "reused": True, "same_scene": True}
            return self._done(rec)
        name = f"{int(time.time() * 1000)}.jpg"
        if isinstance(self.img, ReplicateImages):
            self._check()                                # over a cap: no frame is written (the server keeps the last)
            try:
                pil = self.img.generate(prompt, int(t) % 100000, *self.size)
                if self.ledger is not None:
                    import costs
                    self.ledger.record("eye", "black-forest-labs/flux-schnell", 1, costs.FLUX_SCHNELL_USD, "frame")
            except Exception as e:                        # provider queue/outage: the previous frame, as it was
                if last is None:
                    raise
                print("eye: image failed, keeping the last frame:", repr(e)[:160], flush=True)
                return {**last, "reused": True, "resting": "resting its eyes", "image_failed": True}
        else:
            image = self.img.generate_image(seed=int(t) % 100000, prompt=prompt, width=self.size[0],
                                            height=self.size[1], num_inference_steps=self.steps, guidance=0.0)
            pil = getattr(image, "image", None) or image
        if stage == "NREM":                               # deep sleep: keep only a faint trace of the scene
            from PIL import ImageEnhance
            pil = ImageEnhance.Brightness(pil).enhance(0.25)
        pil.convert("RGB").save(self.out / name, quality=88)
        rec = {"t": sim_hhmm, "stage": stage, "img": f"/eye/{name}", "thought": thought, "scene": scene, "why": why,
               "render_s": round(time.time() - t0, 1), "reused": False}
        jpgs = sorted(self.out.glob("*.jpg"))
        for old in jpgs[:-KEEP_FRAMES]:                    # bounded disk use on a server volume
            old.unlink(missing_ok=True)
        return self._done(rec)

    def _done(self, rec):
        append_jsonl(self.log, rec)
        save_json(self.world_path, self.world.to_dict())
        self.last_rec = rec
        return rec


def market_mood(trades, window_s=120):
    """Gone with the trading terminal (S1/S7): the eye no longer reads a market mood. Kept only so live_server's
    import and `step(..., market_mood(...), ...)` call keep working until that caller is removed; always "calm"."""
    return "calm"
