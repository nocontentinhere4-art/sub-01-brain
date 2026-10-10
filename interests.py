"""What a young man in Kichijōji browses (#56, scope extension): an interest profile, a daily rhythm, and variety.

The owner: "He focuses too much on one topic. He should be like a real person: watch YouTube and TikTok videos, search
for things he saw, memecoins and stocks for example. No guy like him would spend all day on Wikipedia."

- PROFILE: seed weights per topic (edit them here, in one place) with a few searches each and the words that mark a
  page as being about it. His tastes (#38, tastes.py) move a topic's weight between 0.5x and 1.6x over days; they
  never collapse it to one topic.
- RHYTHM by Tokyo hour: football, tech, music and Tokyo in the morning, short videos at lunch, games and cars in the
  afternoon, games, football and anime in the evening, Shorts on the phone late at night (there is no news or
  weather topic). The rhythm only tilts the weights and the feed; his boredom and the brain vote still choose.
- Variety: no quota is imposed from outside (owner, "NO RESTRICTIONS"). A topic that already filled a large share of
  today's pages weighs less (`saturation`), Wikipedia too, and after 3-4 pages in a row on one topic the leave
  option pulls harder (`streak_pull`, added to the vote's leave pull), so he does not get stuck on one topic.
- Novelty (#89, owner): a topic seen in the last RECENT_S (2 h) weighs RECENT_W (x0.15); a query is not typed
  again for QUERY_GAP_S (a day; a page or video is never reopened within 7 days, novelty.py); `pick(discover=True)` (most shorts, and follow-ups over their quarter) takes a
  topic not seen in the last 2 h, from the profile or from discovery: headlines he saw on front pages (`offer`,
  "trending") and a wide DISCOVERY pool of things outside his usual topics.
Pure: no network, no AI. browse.py keeps a Variety per screen session and asks `pick` what to look up next.
"""
import math
import random
import re
import time

# topic: seed weight, searches he might type, words that mark a page as being about the topic.
# #89 teen re-seed (owner: "he's a young guy like us: YouTube, TikTok, cars, really interesting things"), from
# docs/research/teen_online.md (Pew 2024, Ofcom 2025, Common Sense, PARTY USA 2024): gaming, music, creators /
# YouTubers, football, cars, anime, tech and phones, sneakers / streetwear, memes, movies and series. Cooking is not a
# browsing topic: food only while he is hungry or ordering (pick(hungry=True)). No money or crypto topics.
PROFILE = {
    "games": (1.3, ["Elden Ring", "Minecraft builds", "Fortnite new season", "GTA 6 trailer", "Zelda", "Pokemon",
                    "Valorant", "speedrun world record"],
              r"games?|gaming|gamers?|nintendo|playstation|ps5|xbox|steam|esports?|speedrun|pokemon|elden ring|"
              r"minecraft|fortnite|zelda|gta|valorant"),
    "music": (1.1, ["new rap album", "Frank Ocean", "city pop playlist", "THE FIRST TAKE", "k-pop comeback",
                    "lo-fi hip hop", "Tokyo live house tonight"],
              r"music|songs?|albums?|playlist|band|concert|live house|lo-?fi|city pop|singer|rappers?|rap|k-?pop|"
              r"j-?pop|first take"),
    "creators": (1.1, ["MrBeast new video", "Dude Perfect trick shots", "Mark Rober", "YouTubers Japan",
                       "streamer highlights"],
                 r"youtubers?|creators?|streamers?|mrbeast|dude perfect|mark rober|twitch|vlog"),
    "football": (1.0, ["Premier League highlights", "Champions League goals", "Kaoru Mitoma", "Takefusa Kubo",
                       "J League goals", "Japan national football team"],
                 r"football|soccer|premier league|champions league|j ?league|mitoma|kubo|world cup|goals?"),
    "cars": (1.1, ["Toyota GR Supra", "Nissan GT-R", "Honda Civic Type R", "JDM cars", "drifting", "Formula 1",
                   "Porsche 911 GT3"],
             r"cars?|supra|gt-?r|skyline|jdm|drift\w*|civic|type r|porsche|ferrari|lamborghini|toyota|nissan|honda|"
             r"mazda|formula ?1|f1|racing|supercar"),
    "anime": (1.1, ["One Piece", "Jujutsu Kaisen", "Chainsaw Man", "Frieren", "Solo Leveling", "Demon Slayer",
                    "Studio Ghibli"],
              r"anime|manga|ghibli|one piece|crunchyroll|otaku|cosplay|frieren|chainsaw man|jujutsu|solo leveling|"
              r"demon slayer"),
    "tech": (1.0, ["iPhone 17", "best budget headphones", "mechanical keyboards", "AirPods", "Samsung Galaxy",
                   "gaming PC build"],
             r"iphone|android|gadgets?|headphones|keyboards?|laptops?|airpods|samsung|pixel|smartphones?|tech|pc build"),
    "sneakers": (0.9, ["Nike Air Jordan release", "streetwear Harajuku", "new sneaker releases", "vintage clothes Koenji",
                       "Supreme drop"],
                 r"sneakers?|streetwear|harajuku|jordan|nike|adidas|supreme|outfit|fashion|koenji"),
    "memes": (0.9, ["internet memes this week", "funny cat videos", "viral videos", "skits"],
              r"memes?|viral|funny|skits?|internet culture"),
    "movies": (0.8, ["new movie trailers", "Netflix series", "Dune", "anime movie", "A24"],
               r"movies?|films?|trailers?|netflix|series|cinema|a24|dune"),
    "tokyo": (0.4, ["events in Tokyo this weekend", "Shibuya", "Shimokitazawa", "Kichijoji"],
              r"tokyo|kichijoji|shibuya|shinjuku|harajuku|akihabara|inokashira|festival|matsuri"),
    "science": (0.3, ["space news", "how the brain works", "deep sea creatures"],
                r"science|brain|space|nasa|physics|biology|research|planet|dinosaur"),
    "food": (0.0, ["best ramen in Kichijoji", "konbini snacks", "Tokyo street food", "melon pan"],
             r"ramen|sushi|recipe|bakery|bread|food|restaurant|izakaya|onigiri|snack|konbini|curry|noodles?"),
    "wikipedia": (0.1, ["random article"], r"wikipedia"),
}
HUNGRY_FOOD = 1.2                  # food's weight while he is hungry or ordering (else 0: no recipe loops)
WIKI_HOST = re.compile(r"(^|\.)wikipedia\.org$", re.I)
_TOPIC_RX = {k: re.compile(r"\b(" + v[2] + r")\b", re.I) for k, v in PROFILE.items()}

# Tokyo hour -> (name, tilt per topic, feed on the phone, how much video sources are favoured)
RHYTHM = [
    (6, 11, "morning", {"football": 1.3, "tech": 1.2, "music": 1.2, "tokyo": 1.3}, None, 0.3),
    (11, 14, "lunch", {"memes": 1.6, "creators": 1.4, "music": 1.3, "anime": 1.2}, "shorts", 0.7),
    (14, 18, "afternoon", {"games": 1.3, "cars": 1.3, "tech": 1.2, "sneakers": 1.2, "anime": 1.1}, None, 0.5),
    (18, 23, "evening", {"games": 1.6, "football": 1.4, "anime": 1.3, "creators": 1.3, "movies": 1.3}, None, 0.8),
    (23, 30, "late night", {"memes": 1.6, "music": 1.4, "anime": 1.3, "games": 1.2}, "shorts", 0.9),
]                                  # (00:00-06:00 counts as late night: rhythm() adds 24 to hours before 6)
STREAK_FROM = 3                    # pages in a row on one topic before the leave option pulls harder
SATURATION = 4.0                   # how fast a topic's weight falls with its share of today's pages
FREE_SHARE = 0.15                  # shares below this cost nothing
WIKI_FREE = 0.10
RECENT_S = 2 * 3600                # a topic seen this recently weighs RECENT_W (#89)
RECENT_W = 0.15
QUERY_GAP_S = 86400                # a query is not typed again within a day (pages: 7 days, novelty.py)
FOLLOW_SHORTS = 0.3                # shorts on his own interest / what he saw; the rest discovery (>= 60 % new topics)
PHONE_DISCOVERY = 0.15             # B4: on the phone the discovery pool only this often; the rest his topics' neighbours
TRENDING_KEEP = 40
# discovery: subjects outside his usual topics (one query each, each its own topic "discover:<words>"), for a
# 20-year-old (B4: street food, cars, animals, music scenes, game tricks, science shorts; the bonsai / beekeeping /
# knife-sharpening kind of entry is gone), each with the Tokyo months it fits (None: all year; seasonal entries such
# as cherry blossoms, snow festivals and fireworks only in season)
DISCOVERY_SEASONS = [
    ("axolotl facts", None), ("deep sea anglerfish", None), ("octopus intelligence", None), ("giant squid", None),
    ("jellyfish aquarium", None), ("tardigrades", None), ("capybara onsen", (10, 11, 12, 1, 2, 3)),
    ("shiba inu zoomies", None), ("red panda", None), ("penguin parade", None), ("sea otters holding hands", None),
    ("owl cafe Tokyo", None), ("deer in Nara", None), ("snow monkeys", (12, 1, 2, 3)), ("cats vs cucumbers", None),
    ("animal fails compilation", None), ("robot dog", None),
    ("volcano eruption footage", None), ("Antarctica research station life", None), ("storm chasing", (5, 6, 7, 8, 9)),
    ("bioluminescent waves", None), ("ice cave", (12, 1, 2, 3)), ("desert night sky", None), ("typhoon footage", (8, 9, 10)),
    ("Iceland northern lights", (9, 10, 11, 12, 1, 2, 3)), ("aurora timelapse", (9, 10, 11, 12, 1, 2, 3)),
    ("meteor shower", (8, 12)), ("solar eclipse", None), ("black hole image", None), ("Mars rover", None),
    ("ISS live", None), ("rocket launch", None), ("how big is the universe", None), ("slow motion science", None),
    ("why the sky is blue", None), ("how elevators work", None), ("how ramen noodles are made", None),
    ("lucid dreaming tips", None), ("magnetic slime", None), ("domino toppling", None), ("marble run", None),
    ("satisfying cleaning", None), ("miniature cooking", None),
    ("street food Tokyo night market", None), ("konbini night snacks", None), ("ramen vending machine", None),
    ("kakigori shaved ice", (6, 7, 8)), ("yakiimo truck", (10, 11, 12, 1, 2)), ("Tokyo street racing history", None),
    ("JDM car meet Daikoku", None), ("drift car build", None), ("Formula 1 pit stop record", None),
    ("e-scooter Tokyo", None), ("train driver cab view", None), ("night bus Japan", None),
    ("ferry Seto Inland Sea", (4, 5, 6, 7, 8, 9, 10)),
    ("skateboard tricks", None), ("skateboard Shibuya", None), ("parkour Tokyo", None), ("breakdance battle", None),
    ("basketball trick shots", None), ("football freestyle skills", None), ("boxing training footage", None),
    ("sumo training morning", None), ("drone racing", None), ("speed cubing", None), ("kendama tricks", None),
    ("yo-yo world champion", None), ("chess blunders", None), ("rhythm game pro", None), ("Beat Saber expert", None),
    ("Tokyo arcade crane games", None), ("Akihabara retro arcade tour", None), ("Elden Ring speedrun tricks", None),
    ("GTA stunt montage", None), ("Minecraft redstone tricks", None),
    ("beatbox", None), ("a cappella cover", None), ("street piano", None), ("busking Shibuya", None),
    ("jazz drummer solo", None), ("orchestra behind the scenes", None), ("Tokyo hip hop scene", None),
    ("city pop revival", None), ("lo-fi beats study", None), ("taiko drumming", (7, 8)), ("street magic tricks", None),
    ("pixel art", None), ("stop motion animation", None), ("claymation", None), ("3D printing fails", None),
    ("abandoned places Japan", None), ("tiny house tour", None), ("capsule hotel tour", None),
    ("Tokyo apartment tour", None), ("tsunami stone markers", None), ("onsen etiquette", (10, 11, 12, 1, 2, 3)),
    ("cherry blossom forecast", (2, 3, 4)), ("hanami Inokashira", (3, 4)), ("Hokkaido snow festival", (1, 2)),
    ("snowboarding Hakuba", (12, 1, 2, 3)), ("Kyoto autumn leaves", (10, 11, 12)), ("Fuji climbing", (7, 8, 9)),
    ("Okinawa beaches", (5, 6, 7, 8, 9)), ("summer fireworks hanabi", (7, 8)), ("summer festival matsuri", (7, 8)),
    ("Halloween Shibuya", (10,)), ("Tokyo Game Show", (9,)), ("Comiket", (8, 12)), ("Christmas illuminations Tokyo", (11, 12)),
    ("hatsumode New Year shrine", (12, 1)), ("Tokyo Auto Salon", (1,)), ("Golden Week travel Japan", (4, 5)),
]
DISCOVERY = [q for q, _ in DISCOVERY_SEASONS]


def tokyo_month(t=None):
    from datetime import datetime
    try:
        from sleep import TZ
    except Exception:                                       # pragma: no cover
        from zoneinfo import ZoneInfo
        TZ = ZoneInfo("Asia/Tokyo")
    return datetime.fromtimestamp(time.time() if t is None else t, TZ).month


def discovery_pool(month=None):
    """The discovery queries that fit this Tokyo month (B4: no cherry blossoms in October)."""
    m = int(month) if month else tokyo_month()
    return [q for q, months in DISCOVERY_SEASONS if not months or m in months]


def rhythm(hour):
    """-> {name, tilt, feed, video} for a Tokyo hour (0..24)."""
    h = float(hour) % 24
    h2 = h + 24 if h < 6 else h
    for a, b, name, tilt, feed, video in RHYTHM:
        if a <= h2 < b:
            return {"name": name, "tilt": dict(tilt), "feed": feed, "video": video}
    return {"name": "early", "tilt": {}, "feed": None, "video": 0.0}


def tokyo_hour(t=None):
    from datetime import datetime
    try:
        from sleep import TZ
    except Exception:                                       # pragma: no cover
        from zoneinfo import ZoneInfo
        TZ = ZoneInfo("Asia/Tokyo")
    d = datetime.fromtimestamp(time.time() if t is None else t, TZ)
    return d.hour + d.minute / 60


def topic_of(text, host=""):
    """The profile topic a page / query is about (most matching words), or None."""
    if WIKI_HOST.search((host or "").rstrip(".")):
        best = topic_of(text)
        return best or "wikipedia"
    t = text or ""
    scores = {k: len(rx.findall(t)) for k, rx in _TOPIC_RX.items() if k != "wikipedia"}
    k = max(scores, key=lambda x: scores[x]) if scores else None
    return k if k and scores[k] > 0 else None


def taste_multiplier(topic, pref):
    """Tastes move a topic's weight between 0.5x and 1.6x: the mean learned preference of its words."""
    words = set(re.findall(r"[a-z]{4,}", " ".join(PROFILE[topic][1]).lower()))
    vals = [pref[f"kw:{w}"] for w in words if f"kw:{w}" in (pref or {})]
    v = sum(vals) / len(vals) if vals else 0.0
    return round(max(0.5, min(1.6, 1.0 + 0.6 * math.tanh(2.0 * v))), 3)


class Variety:
    """Today's pages per topic (Tokyo day), Wikipedia's share, and the current run of pages on one topic."""

    def __init__(self, state=None, clock=time.time):
        from search_sources import tokyo_day
        self._day_of = tokyo_day
        self.clock = clock
        s = state or {}
        self.day = s.get("day")
        self.topics = {k: int(v) for k, v in (s.get("topics") or {}).items() if isinstance(v, int)}
        self.pages = int(s.get("pages") or 0)
        self.wiki = int(s.get("wiki") or 0)
        self.last = s.get("last")
        self.streak = int(s.get("streak") or 0)
        self.seen_t = {k: float(v) for k, v in (s.get("seen_t") or {}).items() if isinstance(v, (int, float))}
        self.queries = {k: float(v) for k, v in (s.get("queries") or {}).items() if isinstance(v, (int, float))}
        self.trending = [x for x in (s.get("trending") or []) if isinstance(x, str)][-TRENDING_KEEP:]
        self.hosts = {k: int(v) for k, v in (s.get("hosts") or {}).items() if isinstance(v, int)}
        self.last_host = s.get("last_host")
        self.host_streak = int(s.get("host_streak") or 0)
        self._roll()

    def recent(self, topic, within=RECENT_S):
        """Seen in the last `within` seconds (across days)."""
        return bool(topic) and self.clock() - self.seen_t.get(topic, -1e18) < within

    def mark(self, topic=None, query=None):
        """A topic / query was used now (a pick, a page)."""
        now = self.clock()
        if topic:
            self.seen_t[topic] = now
        if query:
            self.queries[" ".join(str(query).lower().split())] = now
        for d in (self.seen_t, self.queries):
            for k in [k for k, t in d.items() if now - t > QUERY_GAP_S]:
                del d[k]

    def query_used(self, q):
        return self.clock() - self.queries.get(" ".join(str(q).lower().split()), -1e18) < QUERY_GAP_S

    def offer(self, titles):
        """Headlines seen on a front page (news, forums): candidates for discovery ("trending")."""
        for t in titles or []:
            t = " ".join(str(t).split())[:80]
            if 3 <= len(t.split()) <= 12 and t not in self.trending and not self.query_used(t):
                self.trending.append(t)
        self.trending = self.trending[-TRENDING_KEEP:]

    def _roll(self):
        day = self._day_of(self.clock())
        if day != self.day:
            self.day, self.topics, self.pages, self.wiki, self.last, self.streak = day, {}, 0, 0, None, 0
            self.hosts = {}

    def note(self, title, text="", host=""):
        """A page was shown: count its topic; returns the topic (None: no profile topic)."""
        self._roll()
        topic = topic_of(f"{title} {text[:1500]}", host)
        self.pages += 1
        h = (host or "").lower().removeprefix("www.")
        if h:
            self.hosts[h] = self.hosts.get(h, 0) + 1
            self.host_streak = self.host_streak + 1 if h == self.last_host else 1
            self.last_host = h
        if WIKI_HOST.search((host or "").rstrip(".")):
            self.wiki += 1
        if topic:
            self.topics[topic] = self.topics.get(topic, 0) + 1
            self.mark(topic)
        if topic and topic == self.last:
            self.streak += 1
        else:
            self.last, self.streak = topic, 1 if topic else 0
        return topic

    def host_count(self, host):
        """Pages on this site today."""
        self._roll()
        return self.hosts.get((host or "").lower().removeprefix("www."), 0)

    def share(self, topic):
        self._roll()
        return self.topics.get(topic, 0) / self.pages if self.pages else 0.0

    def wiki_share(self):
        self._roll()
        return self.wiki / self.pages if self.pages else 0.0

    def entropy(self):
        """Shannon entropy (bits) of today's topic mix; pages with no profile topic count as one 'other' bucket."""
        self._roll()
        counts = list(self.topics.values()) + [max(0, self.pages - sum(self.topics.values()))]
        n = sum(counts)
        return round(-sum(c / n * math.log2(c / n) for c in counts if c), 3) if n else 0.0

    def to_dict(self):
        self._roll()
        return {"day": self.day, "topics": dict(self.topics), "pages": self.pages, "wiki": self.wiki,
                "last": self.last, "streak": self.streak, "seen_t": dict(self.seen_t), "queries": dict(self.queries),
                "trending": list(self.trending), "hosts": dict(self.hosts), "last_host": self.last_host,
                "host_streak": self.host_streak}

    def public(self):
        d = self.to_dict()
        for k in ("seen_t", "queries", "trending", "hosts"):
            d.pop(k, None)
        d["top_hosts"] = dict(sorted(self.hosts.items(), key=lambda kv: -kv[1])[:5])
        d.update(recent_topics=sorted(k for k in self.seen_t if self.recent(k)), trending_n=len(self.trending),
                 top_share=round(max(self.topics.values()) / self.pages, 3) if self.pages and self.topics else 0.0,
                 wiki_share=round(self.wiki_share(), 3), entropy_bits=self.entropy())
        return d


def saturation(share, free=FREE_SHARE):
    """A topic that already filled much of today weighs less (novelty, not a quota): 1 below `free`, then falling."""
    return math.exp(-SATURATION * max(0.0, share - free))


def taste_multipliers(pref):
    """Topic -> taste multiplier (computed where the tastes live, passed to the browser with the interest)."""
    return {t: round(taste_multiplier(t, pref or {}), 3) for t in PROFILE}


def weights(variety=None, pref=None, hour=12.0, mult=None, hungry=False):
    """Topic -> weight now: seed x tastes x the hour's tilt x saturation. `mult`: precomputed taste multipliers.
    Food weighs only while he is hungry (HUNGRY_FOOD)."""
    r = rhythm(hour)
    out = {}
    for topic, (seed, _, _) in PROFILE.items():
        m = (mult or {}).get(topic) if mult else taste_multiplier(topic, pref or {})
        m = max(0.5, min(1.6, float(m))) if isinstance(m, (int, float)) else 1.0
        if topic == "food":
            seed = HUNGRY_FOOD if hungry else 0.0
        w = seed * m * r["tilt"].get(topic, 1.0)
        if variety is not None:
            w *= saturation(variety.wiki_share(), WIKI_FREE) if topic == "wikipedia" else saturation(
                variety.share(topic))
            if variety.last == topic and variety.streak >= STREAK_FROM:
                w *= 0.5                                    # he just had several pages of it
            if variety.recent(topic):
                w *= RECENT_W                               # #89: seen in the last 2 hours
        out[topic] = w
    return out


def discovery_topic(q):
    return "discover:" + "-".join(re.findall(r"[a-z0-9]+", str(q).lower())[:6] or ["x"])


def pick(variety=None, pref=None, hour=12.0, rng=None, mult=None, discover=False, hungry=False, month=None,
         pool_share=0.5):
    """One search from the profile: {"query", "topic", "from": "interests", "rhythm"}. Queries typed in the last
    week are left out. discover=True: a topic not seen in the last 2 h, from the profile or (pool_share of the time)
    from discovery (trending headlines he saw, the DISCOVERY pool of this Tokyo `month`); "new": True on the result."""
    rng = rng or random.Random()
    w = weights(variety, pref, hour, mult, hungry)
    fresh = (lambda q: not variety.query_used(q)) if variety is not None else (lambda q: True)
    topics = [k for k in w if k != "wikipedia" and w[k] > 0 and any(fresh(q) for q in PROFILE[k][1])]
    if discover and variety is not None:
        topics = [k for k in topics if not variety.recent(k)]
    out = None
    if discover and (not topics or rng.random() < pool_share):
        season = discovery_pool(month)
        trend = [t for t in (variety.trending if variety is not None else []) if fresh(t)
                 and not (variety and variety.recent(topic_of(t) or discovery_topic(t)))]
        pool = [q for q in season if fresh(q) and not (variety and variety.recent(discovery_topic(q)))]
        if not pool and not trend and variety is not None:  # all typed today: the one typed longest ago
            old = [q for q in season if not variety.recent(discovery_topic(q))]
            pool = sorted(old, key=lambda q: variety.queries.get(q.lower(), 0))[:5]
        if trend and (rng.random() < 0.5 or not pool):
            q = rng.choice(trend)
            variety.trending.remove(q)
            out = {"query": q, "topic": topic_of(q) or discovery_topic(q), "source": "trending"}
        elif pool:
            q = rng.choice(pool)
            out = {"query": q, "topic": discovery_topic(q), "source": "discovery"}
    if out is None:
        topics = topics or [k for k in w if k != "wikipedia" and w[k] > 0]
        total = sum(w[k] for k in topics)
        x = rng.random() * total
        for k in topics:
            x -= w[k]
            if x <= 0:
                break
        qs = [q for q in PROFILE[k][1] if fresh(q)] or PROFILE[k][1]
        out = {"query": rng.choice(qs), "topic": k, "source": "profile"}
    if variety is not None:
        out["new"] = not variety.recent(out["topic"])
        variety.mark(out["topic"], out["query"])
    return dict(out, **{"from": "interests", "rhythm": rhythm(hour)["name"]})


def streak_pull(variety):
    """Extra pull of the leave option after STREAK_FROM pages in a row on one topic, or on one site (#89 teen: the
    seven King Arthur Baking pages in a row) (0..1)."""
    if variety is None:
        return 0.0
    n = max(variety.streak if variety.last else 0, getattr(variety, "host_streak", 0))
    if n < STREAK_FROM:
        return 0.0
    return round(min(1.0, 0.35 + 0.2 * (n - STREAK_FROM)), 3)
