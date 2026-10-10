"""SUB-01's simulated life: a character in a small world whose choices come from needs + the brain model.

Server-authoritative: one agent, one world, everyone sees the same life. Needs (hunger, boredom, energy from
the sleep engine) rise over simulated time; every time an activity ends, a utility score picks the next one.
The brain model tilts the scores (reward -> goes out, fear -> stays in, salience -> picks up the phone) and chat
messages add short-lived desires ("vai a comprare il pane"). Walking happens in real time along a waypoint
graph, so what viewers see is continuous. It is a simulation driven by a brain model, not a person.

The day has a shape (L1-L3): the pick is a softmax over the scores with a penalty for what he did in the last hours,
meals fall in three slots and come from the bakery before the courier, the desk is damped on weekday daytime and off
between midnight and six, the park closes at 20:00 and a trip's timer starts on arrival.
"""
import heapq
import json
import math
import random
import re
from pathlib import Path

from sleep import local
from twin.body import Body

CARBS_PER_BREAD_G = 30.0    # one piece of bread: a ~60 g roll at ~50 % carbohydrate (USDA FoodData Central)
CARBS_PER_MEAL_G = 70.0     # a delivered meal (a bowl of ramen: ~70 g carbohydrate)
# eating thresholds on the body's hunger scale (design choices): below SATED it does not eat, above EAT_AT it is meal time
SATED, EAT_AT = 0.35, 0.55
# needs first (#57): above SATED the food actions get NEED_W x u^3, u = (hunger - SATED) / (EAT_AT - SATED), so at meal
# time they outrank chat, research, video, chess and the plan bonus; a smooth ramp, not a hard override
NEED_W = 1.6
FOOD_WAITING = 1.2          # a meal waiting at home and hunger above SATED: eating it wins within minutes
INTERRUPT_MARGIN = 0.3      # a food action that beats the current activity by this much ends it early
FOOD_ACTS = ("eat", "buy_bread", "buy_konbini", "order_food", "get_delivery")
INTERRUPTIBLE = ("phone", "window", "research", "chat", "watch_video", "play_chess", "listen_music")
# ---- the day's shape (L1-L3) ----------------------------------------------------------------------------------
CHOICE_T = 0.1              # softmax temperature over the scores: a 0.15 gap is ~80/20, a 0.3 gap ~95/5
REPEAT_WINDOW, REPEAT_W = 3 * 3600, 0.5   # each start of the same activity in the last 3 sim hours halves its score
DAY_RESET_H = 4             # the day for meal / session counts runs 04:00-04:00 (a late night belongs to its day)
RESEARCH_PER_DAY = 3        # reading sessions a day; past that the desk weighs a quarter
WORKDAY_RESEARCH, WORKDAY_CHESS = 0.7, 0.6   # weekday 09-18: the desk is damped (a chess wish from the chat is not)
WORKDAY_OUT = 0.1           # ... and the park, the window and the errand get a bonus on a weekday daytime
WEEKEND_PARK = 0.15         # the park weighs more on a weekend, and opens an hour earlier (07:00)
MEAL_SLOTS = ((7, 10), (12, 14), (18, 21))   # breakfast, lunch, dinner (Tokyo hours): a meal starts in a slot...
MEALS_PER_DAY = 4           # ... or as a real need (hunger >= EAT_AT); 3 meals and a snack a day, then eating weighs a fifth
MEAL_CAP_W = 0.2
ORDER_EVERY = 3 * 3600      # one delivery order per 3 sim hours at most, and only at meal need (hunger >= EAT_AT)
BAKERY_ERRAND = 0.3         # no bread at home while the bakery is open: the daily walk to stock up (BREAD_PER_TRIP)
BREAD_PER_TRIP, ROLLS_PER_MEAL = 4, 2   # four rolls a trip, two a meal: a trip is two meals (the plan said three rolls)
PARK_CLOSES = 20            # the bench is left by 20:00; a trip starts only when he can get there before that
NIGHT_END = 6               # 00:00-06:00: no computer and no window unless chat is waiting (an input wake is phone or music)
# a wish heard in the chat for one of these (a desire of at least WISH_MIN) that beats what he is doing at home, or on
# the park bench, by INTERRUPT_MARGIN ends it early: "let's play chess" leads to a game within minutes, not hours
WISH_INTERRUPTS, WISH_MIN = ("play_chess",), 0.5
# background music (#68): a flag, not an activity; live_server may put a track on during these, or on a walk outside
MUSIC_BG = ("research", "play_chess", "park")

# ---- the world (metres; x east, z south). Sent to the client, which builds the 3D scene from it. ----------
PLACES = {
    "bed": (1.6, 1.3), "window": (4.0, 0.9), "table": (6.3, 4.2), "desk": (6.5, 1.6),
    "door_in": (4.0, 5.4), "door_out": (4.0, 6.9), "street_home": (4.0, 10.0),
    "street_bakery": (21.0, 10.0), "bakery_door": (21.0, 13.0), "bakery_in": (21.0, 15.2),
    "counter": (21.0, 16.4), "street_park": (-13.0, 10.0), "park_gate": (-13.0, 13.4), "bench": (-13.0, 17.4),
}
EDGES = [("bed", "window"), ("bed", "table"), ("bed", "desk"), ("bed", "door_in"), ("window", "table"),
         ("window", "desk"), ("window", "door_in"), ("table", "desk"), ("table", "door_in"), ("desk", "door_in"),
         ("door_in", "door_out"), ("door_out", "street_home"), ("street_home", "street_bakery"),
         ("street_home", "street_park"), ("street_bakery", "bakery_door"), ("bakery_door", "bakery_in"),
         ("bakery_in", "counter"), ("street_park", "park_gate"), ("park_gate", "bench")]
WORLD = {"places": PLACES, "edges": EDGES,
         "apartment": [0, 0, 8, 6], "bakery": [17, 14, 25, 20], "park": [-19, 13, -7, 23],
         "street": [-22, 8.5, 30, 11.5]}

WALK_SPEED = 1.3            # m / real second (indoors and in the 3D model)
# outdoor legs run at OUTDOOR_SPEEDUP x the real walking pace (design choice, L3): the real park route is 1.3 km, a
# quarter of an hour each way at 1.3 m/s, which left the room empty for most of a park trip; at 3x the map marker
# still follows the real streets and a park walk is ~5 min each way, the bakery ~2 min
OUTDOOR_SPEEDUP = 3

# ---- the real streets (Kichijoji, Tokyo): outdoor legs of the 3D graph are mapped onto real walking routes ----
TOKYO = json.loads((Path(__file__).parent / "web" / "tokyo_routes.json").read_text())
OUTDOOR = {"bakery_door": ("home-bakery", ["door_out", "street_home", "street_bakery", "bakery_door"]),
           "park_gate": ("home-park", ["door_out", "street_home", "street_park", "park_gate"])}
ROUTE_NODES = {name: nodes for name, nodes in OUTDOOR.values()}
# the nodes that name a real route (door_out -> street_home is on both: FRAC maps it onto the stretch they share)
TRIP_NODES = {"home-park": ("street_park", "park_gate", "bench"),
              "home-bakery": ("street_bakery", "bakery_door", "bakery_in", "counter")}
# simulated seconds of an outdoor route (both ways the same): the opening hours are checked at arrival time
WALK_S = {name: TOKYO["routes"][name]["meters"] / WALK_SPEED / OUTDOOR_SPEEDUP for name in TRIP_NODES}
STREET = ("street_home", "street_bakery", "bakery_door", "street_park", "park_gate")   # nodes on the way, outside


def _shared_f(name):
    """Fraction of a real route that both routes share from the door (~330 m of the same street, OSRM): the 3D leg
    door_out -> street_home maps onto it on either route, so the marker never jumps when a trip changes route at
    street_home (bakery -> park without going home). Measured the way along() does, in degrees."""
    a, b = TOKYO["routes"]["home-park"]["latlng"], TOKYO["routes"]["home-bakery"]["latlng"]
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    own = TOKYO["routes"][name]["latlng"]
    total = sum(math.dist(p, q) for p, q in zip(own, own[1:]))
    shared = sum(math.dist(p, q) for p, q in zip(own[:n], own[1:n]))
    return min(0.9, shared / total) if total else 0.5


def _fracs(name, nodes):
    """3D node -> fraction of the real route: door_out 0, street_home where the shared stretch ends, the rest by 3D
    distance, the destination 1."""
    f0 = _shared_f(name)
    legs = [math.dist(PLACES[p], PLACES[q]) for p, q in zip(nodes[1:], nodes[2:])]
    fr, cum = {nodes[0]: 0.0, nodes[1]: f0}, 0.0
    for q, d in zip(nodes[2:], legs):
        cum += d
        fr[q] = f0 + (1.0 - f0) * cum / sum(legs)
    return fr


FRAC = {name: _fracs(name, nodes) for name, nodes in OUTDOOR.values()}


def along(latlng, f):
    """Point and heading at fraction f of a polyline [[lat, lng], ...]."""
    seg = [math.dist(a, b) for a, b in zip(latlng, latlng[1:])]
    goal, acc = max(0.0, min(1.0, f)) * sum(seg), 0.0
    for (a, b), d in zip(zip(latlng, latlng[1:]), seg):
        if acc + d >= goal and d > 0:
            t = (goal - acc) / d
            lat, lng = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
            heading = math.degrees(math.atan2((b[1] - a[1]) * math.cos(math.radians(a[0])), b[0] - a[0])) % 360
            return lat, lng, heading
        acc += d
    a, b = latlng[-2], latlng[-1]
    return b[0], b[1], math.degrees(math.atan2((b[1] - a[1]) * math.cos(math.radians(a[0])), b[0] - a[0])) % 360
ACTIVITIES = {              # place, pose, (min, max) simulated minutes
    "sleep": ("bed", "lying", (0, 0)),
    "phone": ("bed", "lying_phone", (12, 40)),
    "eat": ("table", "sitting", (8, 15)),
    "buy_bread": ("counter", "standing", (2, 4)),
    "buy_konbini": ("counter", "standing", (2, 4)),       # the 24 h konbini next to the bakery: same street, same walk
    "window": ("window", "standing", (3, 8)),
    "park": ("bench", "sitting", (20, 45)),
    "research": ("desk", "sitting_desk", (15, 45)),
    "order_food": ("bed", "lying_phone", (2, 4)),
    "get_delivery": ("door_in", "standing", (1, 2)),
    "chat": ("desk", "sitting_desk", (6, 15)),
    "watch_video": ("desk", "sitting_desk", (10, 30)),    # one or more muted videos, each 2-10 min (#17)
    "play_chess": ("desk", "sitting_desk", (30, 60)),     # ends earlier when the game ends (live_server)
    "listen_music": ("bed", "lying_headphones", (8, 25)),  # tracks his brain model picks, shown as Spotify embeds (#68)
}
# what he eats (#63): a delivery is one dish, picked when he orders (a viewer's wish heard in the last sim hour, else at
# random); the konbini sells onigiri and bentos. The room shows the dish; the labels name it
DISHES = ("ramen", "sushi", "pizza", "curry", "bento")
KONBINI = ("onigiri", "konbini_bento")
DISH_RE = re.compile(r"\b(ramen|sushi|pizza|curry|bento)\b")
EAT_LABEL = {"bread": "eating bread at the table", "ramen": "eating ramen from the delivery",
             "sushi": "eating sushi from the delivery", "pizza": "eating pizza from the delivery",
             "curry": "eating curry from the delivery", "bento": "eating a bento from the delivery",
             "onigiri": "eating an onigiri from the konbini", "konbini_bento": "eating a bento from the konbini"}
PLAN_BONUS = 0.35           # the day plan (mind.py) tilts the choice toward its next step; needs still come first
VOTE_BONUS = 1.2            # viewers' vote (audience.py): a strong tilt toward the winning activity; needs still come first
NUDGE_HOLD = 3600           # simulated seconds the vote's nudge lasts once applied (then it is spent)
COOK_MIN = (8, 15)          # simulated minutes before the courier leaves the shop
COURIER_SPEED = 4.0         # m / simulated second (bike)
LABEL = {"sleep": "sleeping", "phone": "in bed scrolling the phone", "eat": "eating bread at the table",
         "buy_bread": "buying bread", "buy_konbini": "buying a meal at the konbini",
         "window": "looking out of the window",
         "park": "sitting on the park bench", "research": "reading at the computer",
         "order_food": "ordering food on the phone", "get_delivery": "getting the delivery at the door",
         "chat": "answering chat at the computer", "watch_video": "watching a video at the computer (muted)",
         "play_chess": "playing chess at the desk", "listen_music": "lying on the bed listening to music"}
DESIRES = [  # chat words -> short-lived desire
    (r"\b(pane|bread|fame|hungry|mangia|eat|colazione|breakfast)\b", "buy_bread"),
    (r"\b(tiktok|telefono|phone|scroll|social|video)\b", "phone"),
    (r"\b(parco|park|fuori|outside|passeggia|walk|aria)\b", "park"),
    (r"\b(finestra|window|guarda fuori|look outside)\b", "window"),
    (r"\b(sushi|ramen|pizza|delivery|consegna|ordina|order|cibo|food|uber)\b", "order_food"),
    (r"\b(chess|scacchi)\b", "play_chess"),
    (r"\b(music|musica|song|songs|canzone|canzoni|spotify|playlist|metti|ascolta|listen|headphones|cuffie)\b"
     r"|^\s*(play|put on)\b(?!.*\b(chess|scacchi|game)\b)", "listen_music"),
    (r"\b(youtube|video|videos|filmato)\b", "watch_video"),
    (r"\b(learn|impara|studia|study|research|ricerca|cerca|wikipedia|why|perch[eé]|how|come mai)\b|\?", "research"),
]


def graph():
    g = {k: [] for k in PLACES}
    for a, b in EDGES:
        d = math.dist(PLACES[a], PLACES[b])
        g[a].append((b, d))
        g[b].append((a, d))
    return g


GRAPH = graph()


def route(a, b):
    """Shortest waypoint path a -> b (Dijkstra)."""
    q, seen, prev = [(0.0, a)], {a: 0.0}, {}
    while q:
        d, n = heapq.heappop(q)
        if n == b:
            break
        for m, w in GRAPH[n]:
            if d + w < seen.get(m, 1e9):
                seen[m], prev[m] = d + w, n
                heapq.heappush(q, (d + w, m))
    path = [b]
    while path[-1] != a:
        path.append(prev[path[-1]])
    return path[::-1]


def day_key(t):
    """The Tokyo day a sim time belongs to, with the day turning at DAY_RESET_H (a 01:00 meal is the evening's)."""
    return local(t - DAY_RESET_H * 3600).date()


def day_start(t):
    """Sim time the current day began (DAY_RESET_H o'clock, Tokyo): one datetime call, then plain comparisons."""
    lt = local(t - DAY_RESET_H * 3600)
    return lt.replace(hour=DAY_RESET_H, minute=0, second=0, microsecond=0).timestamp()


def at_hour(t, hour):
    """Sim time of `hour` o'clock on the Tokyo day of t."""
    return local(t).replace(hour=hour, minute=0, second=0, microsecond=0).timestamp()


def trip_of(place, path):
    """The real route a walk is on ('home-park' / 'home-bakery'), from the nodes it starts at and passes; None indoors."""
    nodes = [place, *path]
    for name, marks in TRIP_NODES.items():
        if any(n in marks for n in nodes):
            return name
    return None


class Life:
    def __init__(self, state=None, rng=None, body=None):
        """body: a twin.body.Body stepped by the caller (live_server). Without one, Life makes and steps its own."""
        s = state or {}
        self.rng = rng or random.Random()
        self.place = s.get("place", "bed")
        self.x, self.z = PLACES[self.place]
        self.heading = 0.0
        self.path = []                         # remaining waypoints while walking
        self.activity = s.get("activity", "window")
        if self.activity not in ACTIVITIES:    # a save from before S1 (the chart is gone): he reads instead
            self.activity = "research"
        self.until = s.get("until", 0.0)       # sim time when the activity ends
        self.dur = s.get("dur")                # minutes-worth of the activity still to clock from arrival (L3), else None
        self.trip = s.get("trip")              # the real route of the current walk, one per trip (L3)
        self.own_body = body is None
        if body is None:
            bs = s.get("body")
            if bs is None and "hunger" in s:               # older save: only the old hunger number
                bs = {"ghrelin": min(1.0, max(0.0, s["hunger"]))}
            body = Body(bs)
        self.body = body
        self.boredom = s.get("boredom", 0.3)
        self.bread = s.get("bread", 0)
        self.desires = {k: v for k, v in s.get("desires", {}).items() if k in ACTIVITIES}   # activity -> (strength, sim time)
        self.phone_app = "chat"                # what the phone shows in bed: the chat app, or short videos (S1: no chart)
        self.log = s.get("log", [])            # recent events for the page
        self.say = ""
        self.time_scale = 1.0
        self.geo = None                        # real position in Tokyo while outside
        self.food = s.get("food", 0)           # delivered meals waiting to be eaten
        self.delivery = s.get("delivery")      # {"ordered", "leaves", "arrives", "dish"} sim times, while one is on its way
        self.food_items = s.get("food_items", [])   # what the waiting meals are (oldest first), e.g. ["ramen"] (#63)
        self.eating = s.get("eating")          # what he eats in the current "eat" (#63)
        self.order_dish = s.get("order_dish")  # the dish he is ordering on the phone
        self.wish = s.get("wish")              # [dish, sim time] a viewer asked for
        self._t = 0.0
        self.plan_hint = None                  # life activity of the day plan's next step (live_server, mind.py)
        self.chat_waiting = 0                  # chat messages he may answer at the computer (live_server)
        # (sim t, activity) of the latest starts: read by live_server, and here the repeat penalty, the day's reading
        # sessions and meals (L1, L2); saved, so a restart does not reset the day's counts
        self.started = [tuple(x) for x in s.get("started", []) if isinstance(x, (list, tuple)) and len(x) == 2][-120:]
        self.last_chess = s.get("last_chess", -1e18)   # sim time the last chess game started (one a day)
        self.last_order = s.get("last_order", -1e18)   # sim time of the last delivery order (one per ORDER_EVERY)
        self.can_watch = True                  # live_server: False when no video can show (no browser, no key, no quota)
        self.video_block_until = s.get("video_block_until", -1e18)   # no watch_video until then (nothing to show, L5)
        self.music = None                      # live_server: {"title", "artist", "mode"} while a track plays (#68)
        self.viewer_nudge = s.get("viewer_nudge")   # [activity, sim time applied]: what viewers voted for (audience.py)
        target = ACTIVITIES[self.activity][0]
        if target != self.place:                          # restored mid-activity somewhere else: walk there
            self.path = route(self.place, target)[1:]
        if self.path and not self.trip:
            self.trip = trip_of(self.place, self.path)

    @property
    def hunger(self):
        """0..1, from the body's blood glucose and gut/ghrelin-like proxy (twin/body.py), no rule of its own."""
        return self.body.hunger

    def exertion(self):
        """0..1 physical effort for the body: walking ~0.3, sitting on the park bench 0.1."""
        return 0.3 if self.path else 0.1 if self.activity == "park" else 0.0

    # --- inputs ---------------------------------------------------------------------------------
    def hear(self, text, t):
        low = text.lower()
        m = DISH_RE.search(low)
        if m:
            self.wish = [m.group(1), t]
        for pat, act in DESIRES:
            if act == "watch_video" and not self.can_watch:
                continue                                    # nothing could show (L5): no wish for it
            if re.search(pat, low):
                w = self.desires.get(act, [0, t])[0]
                self.desires[act] = [min(1.5, w + 0.6), t]

    def desire(self, act, t):
        w, t0 = self.desires.get(act, [0.0, t])
        return w * 0.5 ** ((t - t0) / 3600)            # halves every sim hour

    # --- decision ---------------------------------------------------------------------------------
    def need(self):
        """Hunger-scaled priority of the food actions: 0 up to SATED, NEED_W at EAT_AT, rising past it."""
        u = max(0.0, (self.hunger - SATED) / (EAT_AT - SATED))
        return NEED_W * u ** 3

    def starts_today(self, act, t, since=None):
        """Starts of `act` on the day of t (04:00-04:00), from the start log. since: day_start(t), when known."""
        since = day_start(t) if since is None else since
        return sum(1 for ts, a in self.started if a == act and since <= ts <= t)

    def repeats(self, act, t):
        """Starts of `act` in the last REPEAT_WINDOW (what he is doing counts at least once)."""
        n = sum(1 for ts, a in self.started if a == act and 0 <= t - ts < REPEAT_WINDOW)
        return max(n, 1 if act == self.activity else 0)

    def scores(self, t, rel, hot=0.0, pressure=0.0, going_on=False):
        """Utility of each activity now (awake), before the repeat penalty and the softmax. going_on: the score of
        carrying on with the current activity, so a game already started is not held to the one-a-day rule.
        `hot` (the coin trades) is ignored since S1: it is a body stimulus, never an activity; the slot stays so the
        positional calls (live_server) keep working."""
        lt = local(t)
        h = lt.hour + lt.minute / 60
        wk = lt.weekday() >= 5
        workday = not wk and 9 <= h < 18                   # the daypart table: errands and the park, less desk
        night = h < NIGHT_END and not self.chat_waiting    # 00:00-06:00 and nothing to answer: no computer, no window
        open_bakery = 7 <= h + WALK_S["home-bakery"] / 3600 < 20     # open when he gets there
        park_open = (7 if wk else 8) <= h and h + WALK_S["home-park"] / 3600 < PARK_CLOSES
        kitchen_open = 10 <= h < 23.5
        has_food = self.bread or self.food
        hu = self.hunger                                   # from the body: ~0.2 just fed, ~0.6 at meal time
        need = self.need()
        go_eat = self.desire("buy_bread", t)               # "go eat", "mangia": any way to food
        # meals (L2): in a slot a hunger above SATED starts one; between slots only a real need (EAT_AT) does, and a
        # meal already waiting at home is eaten; past MEALS_PER_DAY a snack weighs a fifth (a real need still eats)
        mealtime = hu >= EAT_AT or any(a <= h < b for a, b in MEAL_SLOTS)
        since = day_start(t)
        cap = MEAL_CAP_W if hu < EAT_AT and self.starts_today("eat", t, since) >= MEALS_PER_DAY else 1.0
        hungry = hu > SATED
        desk = 0.0 if night else 1.0
        s = {
            "eat": ((1.3 * hu + need + (FOOD_WAITING if self.food else 0.0) + go_eat) * cap
                    if hungry and (mealtime or self.food) else 0.0) if has_food else 0.0,
            "buy_bread": (((0.9 * hu + need) * cap if hungry and mealtime else 0.0) + go_eat
                          + BAKERY_ERRAND + (WORKDAY_OUT if workday else 0.0))
                         if (not has_food and open_bakery and not self.delivery) else 0.0,
            "buy_konbini": (((0.85 * hu + need) * cap if hungry and mealtime else 0.0) + go_eat)
                           if (not has_food and not open_bakery and not self.delivery) else 0.0,
            "order_food": (0.6 * hu + 0.15 + need + self.desire("order_food", t)) * cap
                          if (not has_food and not self.delivery and kitchen_open and hu >= EAT_AT
                              and t - self.last_order >= ORDER_EVERY) else 0.0,
            "research": ((0.42 + 0.3 * (1 - self.boredom) + 0.2 * max(0, rel.get("attention", 1) - 1))
                         * (WORKDAY_RESEARCH if workday else 1.0)
                         * (0.25 if self.starts_today("research", t, since) >= RESEARCH_PER_DAY else 1.0)
                         + self.desire("research", t)) * desk,
            "phone": 0.7 * self.boredom + (0.5 if h >= 22.5 or h < NIGHT_END else 0) + 0.25 * pressure
                     + self.desire("phone", t) + 0.2 * max(0, rel.get("salience", 1) - 1),
            "park": (0.8 * self.boredom + 0.05 + (WORKDAY_OUT if workday else 0.0) + (WEEKEND_PARK if wk else 0.0)
                     + 0.8 * max(0, rel.get("reward", 1) - 1) + self.desire("park", t))
                    if park_open and rel.get("fear", 1) < 1.3 and not self.delivery else 0.0,
            "window": (0.2 + (WORKDAY_OUT if workday else 0.0) + 0.15 * max(0, rel.get("fear", 1) - 1)
                       + self.desire("window", t)) * desk,
            "chat": 0.6 + 0.25 * min(3, self.chat_waiting) if self.chat_waiting else 0.0,
            "watch_video": (0.15 + 0.55 * self.boredom + 0.25 * max(0, rel.get("visual", 1) - 1)
                            + self.desire("watch_video", t)) * desk
                           if self.can_watch and t >= self.video_block_until else 0.0,
            "play_chess": ((0.3 + 0.2 * (1 - self.boredom) + 0.25 * max(0, rel.get("attention", 1) - 1))
                           * (WORKDAY_CHESS if workday and self.desire("play_chess", t) < WISH_MIN else 1.0)
                           + self.desire("play_chess", t))
                          if (self.chess_ok(t) or going_on and self.activity == "play_chess") and 8 <= h < 23.5 else 0.0,
            # music (#68): when bored or tired, more in the evening; needs still come first (food gets NEED_W)
            "listen_music": (0.12 + 0.4 * self.boredom + 0.35 * min(1.0, max(0.0, pressure))
                             + (0.15 if 18 <= h or h < 1 else 0.0) + 0.15 * max(0, rel.get("reward", 1) - 1)
                             + self.desire("listen_music", t)),
        }
        if s.get(self.plan_hint, 0.0) > 0:              # the plan only tilts what is possible now
            s[self.plan_hint] += PLAN_BONUS
        nudge = self.nudge(t)
        if nudge and s.get(nudge, 0.0) > 0:             # viewers' vote: the same, stronger; never the impossible
            s[nudge] += VOTE_BONUS
        return s

    def nudge(self, t):
        """The activity viewers voted for, while its nudge lasts (NUDGE_HOLD after it was applied), else None."""
        n = self.viewer_nudge
        if not n or t - n[1] > NUDGE_HOLD or n[0] not in ACTIVITIES:
            return None
        return n[0]

    def apply_vote(self, act, t):
        """Viewers' vote result (audience.py): a strong nudge toward `act`. What he is doing at home ends early when the
        nudged activity now beats it (wish_now), so it shows within a tick or two; needs still win."""
        if act not in ACTIVITIES or act == "sleep":
            return False
        self.viewer_nudge = [act, t]
        return True

    def choose(self, t, stage, rel, hot=0.0, pressure=0.0):
        """The next activity: a softmax (CHOICE_T) over the scores, each halved per start of the same activity in the
        last REPEAT_WINDOW (L1) so a day is not one thing twice in a row; food is a need and is not penalised."""
        if stage != "AWAKE":
            return "sleep"
        s = self.scores(t, rel, hot, pressure)
        for a in s:
            if a not in FOOD_ACTS:
                s[a] *= REPEAT_W ** self.repeats(a, t)
        return self.softmax(s)

    def softmax(self, s):
        """One draw over the possible activities (score > 0), p ∝ exp(score / CHOICE_T): the Gumbel-max form, one
        draw per activity (a single inverse-CDF draw made the pick a function of the first random number)."""
        keys = [k for k, v in s.items() if v > 0]
        if not keys:
            return max(s, key=s.get)
        r = self.rng.random
        return max(keys, key=lambda k: s[k] / CHOICE_T - math.log(-math.log(max(1e-12, r()))))

    def hungry_now(self, t, rel, hot=0.0, pressure=0.0):
        """Needs first: a food action now beats what he is doing at home, or on the park bench, by INTERRUPT_MARGIN, so
        he stops early. A chess game and a park visit are only cut at meal time (EAT_AT): with a mild hunger he
        finishes the game, or sits a while, then eats."""
        if not (self.activity in INTERRUPTIBLE or self.activity == "park") or self.hunger <= SATED:
            return False
        if self.activity in ("play_chess", "park") and self.hunger < EAT_AT:
            return False
        s = self.scores(t, rel, hot, pressure, going_on=True)
        best = max((a for a in FOOD_ACTS if a in s), key=s.get)
        return best if s[best] > s.get(self.activity, 0.0) + INTERRUPT_MARGIN else False   # the food action, or False

    def wish_now(self, t, rel, hot=0.0, pressure=0.0):
        """A wish heard in the chat (WISH_INTERRUPTS) beats what he is doing at home, or on the park bench, by
        INTERRUPT_MARGIN: he stops early to do it (the activity, or False; needs still come first in update)."""
        if not (self.activity in INTERRUPTIBLE or self.activity == "park"):
            return False
        wished = [a for a in WISH_INTERRUPTS if self.desire(a, t) >= WISH_MIN and a != self.activity]
        nudge = self.nudge(t)
        if nudge and nudge != self.activity:            # viewers' vote: carried out like a wish
            wished.append(nudge)
        if not wished:
            return False
        s = self.scores(t, rel, hot, pressure, going_on=True)
        best = max(wished, key=lambda a: s.get(a, 0.0))
        return best if s.get(best, 0.0) > s.get(self.activity, 0.0) + INTERRUPT_MARGIN else False

    def chess_ok(self, t):
        """At most one chess game a day (the Tokyo day, turning at DAY_RESET_H; #17 had one an hour)."""
        return t - self.last_chess >= 86400 or day_key(self.last_chess) != day_key(t)

    def end_activity(self, t):
        """The current activity is over now (the chess game ended): the next tick picks the next one."""
        self.until = min(self.until, t)
        self.dur = None

    def no_video(self, t, hold_s=1800):
        """Nothing to show for watch_video (live_server/browse, L5): the activity ends and videos are off for hold_s."""
        self.video_block_until = t + hold_s
        if self.activity == "watch_video":
            self.end_activity(t)

    def walk_s(self):
        """Simulated seconds the current path takes: the real metres of each outdoor leg at OUTDOOR_SPEEDUP x the pace,
        WALK_SPEED on the 3D graph indoors."""
        total, here, path = 0.0, self.place, list(self.path)
        for i, nxt in enumerate(path):
            name = self.leg_route(here, nxt, path[i + 1:])
            if name:
                total += abs(FRAC[name][nxt] - FRAC[name][here]) * TOKYO["routes"][name]["meters"] / WALK_SPEED / OUTDOOR_SPEEDUP
            else:
                total += math.dist((self.x, self.z) if i == 0 else PLACES[here], PLACES[nxt]) / WALK_SPEED * max(1.0, self.time_scale)
            here = nxt
        return total

    def timer(self, t, walk=0.0):
        """When the activity ends if he gets there in `walk` sim seconds: its duration from arrival, and the bench is
        left by PARK_CLOSES (L3)."""
        until = t + walk + (self.dur or 0.0)
        if self.activity == "park":
            until = min(until, max(t + walk, at_hour(t, PARK_CLOSES)))
        return until

    def start(self, act, t, why):
        if act == "play_chess":
            self.last_chess = t
        if act == "order_food":
            self.last_order = t
        self.activity = act
        place, _, (a, b) = ACTIVITIES[act]
        self.dur = 60 * self.rng.uniform(a, b)
        if place != self.place or (self.x, self.z) != PLACES[place]:
            self.path = route(self.place, place)[1:]
            # the real route of the trip (L3); turning back on the shared stretch of street keeps the one he is on
            self.trip = trip_of(self.place, self.path) or (self.trip if self.place in STREET else None)
        else:
            self.trip = None
        # the clock starts on arrival (update); until then a provisional end, never math.inf (old saves, live_server)
        self.until = self.timer(t, self.walk_s() if self.path else 0.0)
        if not self.path:
            self.dur = None
        if act == "phone":                               # the chat app, or short videos when something can show (L5)
            self.phone_app = self.rng.choice(["chat", "tiktok", "tiktok"] if self.can_watch else ["chat"])
        if act == "order_food":                          # its own random stream: the needs logic's draws stay as they were
            w = self.wish
            self.order_dish = w[0] if w and t - w[1] < 3600 else random.Random(int(t)).choice(DISHES)
        if act == "eat":
            self.eating = self.food_items[0] if self.food and self.food_items else "bento" if self.food else "bread"
        self.desires.pop(act, None)
        if act in FOOD_ACTS:
            self.desires.pop("buy_bread", None)         # "go eat" is answered by any way to food
        if self.viewer_nudge and self.viewer_nudge[0] == act:
            self.viewer_nudge = None                     # the vote is carried out: spent
        self.started = (self.started + [(t, act)])[-120:]
        self.say = why
        self.log = (self.log + [{"t": t, "what": why}])[-30:]

    # --- per tick -----------------------------------------------------------------------------------
    def courier(self, t):
        """Where the delivery is: {"status", "eta_min", "geo", "dish"} or None."""
        d = self.delivery
        if not d:
            return None
        if t < d["leaves"]:
            return {"status": "being prepared", "eta_min": round((d["arrives"] - t) / 60), "geo": None, "dish": d.get("dish")}
        route = TOKYO["routes"]["shop-home"]
        f = min(1.0, (t - d["leaves"]) / max(1.0, d["arrives"] - d["leaves"]))
        lat, lng, hd = along(route["latlng"], f)
        return {"status": "at the door" if f >= 1 else "on the way", "eta_min": max(0, round((d["arrives"] - t) / 60)),
                "geo": {"lat": round(lat, 6), "lng": round(lng, 6), "heading": round(hd)}, "dish": d.get("dish")}

    def update(self, t, dt_real, dt_sim, stage, rel, hot=0.0, pressure=0.0, levels=None, amygdala=0.0):
        self._t = t
        if self.own_body:                                  # an external body is stepped by its owner
            self.body.update(dt_sim, levels, amygdala, stage, exertion=self.exertion())
        # the courier at the door: from anywhere at home or on the bench he goes to the door (a purchase at the counter
        # is finished first; mid-walk he turns back at the next node, below)
        if self.delivery and t >= self.delivery["arrives"] and not self.path and self.activity != "get_delivery" \
                and self.place not in ("counter", "bakery_in") and stage == "AWAKE":
            self.start("get_delivery", t, "the courier rings: goes to the door")
        if self.activity in ("window", "research"):
            self.boredom = min(1.0, self.boredom + dt_sim / (2 * 3600))
        if self.activity in ("phone", "chat", "watch_video", "play_chess", "listen_music"):
            self.boredom = max(0.0, self.boredom - dt_sim / (40 * 60))
        if self.activity == "park":
            self.boredom = max(0.0, self.boredom - dt_sim / (30 * 60))
        # walking (real time, so viewers see continuous motion)
        if self.path:
            tx, tz = PLACES[self.path[0]]
            dx, dz = tx - self.x, tz - self.z
            d = math.hypot(dx, dz)
            step = WALK_SPEED * dt_real
            out = self.outdoor_leg()
            if out:                                       # outside: the real Tokyo walk, at OUTDOOR_SPEEDUP x the pace
                name, nodes, (f0, f1) = out
                self.trip = name                          # the route he is on (the shared stretch home keeps it)
                leg_m = max(1.0, abs(f1 - f0) * TOKYO["routes"][name]["meters"])
                real_s = leg_m / WALK_SPEED / OUTDOOR_SPEEDUP / max(1.0, self.time_scale)
                step = math.dist(PLACES[self.place], (tx, tz)) / real_s * dt_real
            self.heading = math.atan2(dx, dz)
            if d <= step:
                self.x, self.z = tx, tz
                self.place = self.path.pop(0)
                if not self.path and self.dur is not None:      # arrived: the activity's clock starts now (L3)
                    self.until = self.timer(t)
                    self.dur = None
                elif self.path and self.delivery and t >= self.delivery["arrives"] and stage == "AWAKE" \
                        and self.activity != "get_delivery" and self.place in STREET:
                    self.start("get_delivery", t, "the courier rings: heads back to the door")   # turns back
            else:
                self.x += dx / d * step
                self.z += dz / d * step
            self.update_geo()
            return
        # arrived: effects of finishing the activity, then pick the next one
        if self.activity == "sleep" and stage != "AWAKE":
            return                                        # asleep: nothing to decide until the brain wakes up
        must_sleep = stage != "AWAKE"
        woke = stage == "AWAKE" and self.activity == "sleep"
        # an interruption names what he gets up for: the food action (needs first), else the wish or the vote
        hungry = self.hungry_now(t, rel, hot, pressure) if stage == "AWAKE" else False
        wish = (not hungry and self.wish_now(t, rel, hot, pressure)) if stage == "AWAKE" else False
        if t >= self.until or must_sleep or woke or hungry or wish:
            if self.activity == "buy_bread" and self.place == "counter":
                self.bread += BREAD_PER_TRIP
            if self.activity == "buy_konbini" and self.place == "counter":
                self.food += 1                            # one meal (a bento), eaten like a delivered one
                self.food_items.append(random.Random(int(t)).choice(KONBINI))
            if self.activity == "eat" and self.food:
                self.food -= 1
                if self.food_items:
                    self.food_items.pop(0)
                self.body.eat(CARBS_PER_MEAL_G)
            elif self.activity == "eat" and self.bread:
                rolls = min(self.bread, ROLLS_PER_MEAL)   # a meal is two rolls (~60 g carbohydrate), a snack one
                self.bread -= rolls
                self.body.eat(rolls * CARBS_PER_BREAD_G)
            if self.activity == "order_food" and not self.delivery:
                leaves = t + 60 * self.rng.uniform(*COOK_MIN)
                ride = TOKYO["routes"]["shop-home"]["meters"] / COURIER_SPEED
                self.delivery = {"ordered": t, "leaves": leaves, "arrives": leaves + ride, "dish": self.order_dish or "bento"}
            if self.activity == "get_delivery" and self.delivery and t >= self.delivery["arrives"]:
                self.food_items.append(self.delivery.get("dish", "bento"))
                self.delivery = None
                self.food += 1
            nxt = (hungry or wish) if (hungry or wish) and not must_sleep else self.choose(t, stage, rel, hot, pressure)
            why = {
                "sleep": "falls asleep" if self.place == "bed" else "goes to bed",
                "eat": "hungry: eats some bread",
                "buy_bread": "hungry and no bread left: goes to the bakery" if self.hunger > SATED
                             else "no bread left: walks to the bakery",
                "buy_konbini": "hungry and the bakery is closed: walks to the konbini",
                "phone": "bored: picks up the phone",
                "park": "feels good: goes out to the park", "window": "looks out of the window",
                "research": "curious: sits at the computer to read", "order_food": "hungry: orders food on the phone",
                "get_delivery": "the courier rings: goes to the door",
                "chat": "chat messages are waiting: sits at the computer to answer",
                "watch_video": "bored: puts a video on at the computer (muted)",
                "play_chess": "sits down for a game of chess at the desk",
                "listen_music": "bored: lies down with his headphones on" if self.boredom >= 0.5
                                else "lies down with his headphones on",
            }[nxt]
            if nxt == self.plan_hint and nxt != "sleep":
                why += "; it is in today's plan"
            if self.viewer_nudge and nxt == self.viewer_nudge[0]:
                why += "; viewers voted for it"
            if nxt == "eat" and self.food:
                why = f"hungry: eats the {(self.food_items[0] if self.food_items else 'meal').replace('konbini_', '')} at the table"
            if woke:
                why = "wakes up"
            self.start(nxt, t, why)

    def music_bg_ok(self):
        """Background music is possible now (#68): at the desk reading or playing chess, on the park bench, or walking
        outside."""
        if self.activity == "listen_music" or self.activity == "sleep":
            return False
        if self.path:
            return self.outdoor_leg() is not None
        return self.activity in MUSIC_BG

    def leg_route(self, here, nxt, ahead=()):
        """The real route of the 3D leg here -> nxt, None indoors. A side street names its route; the stretch both
        routes share (door_out <-> street_home) takes the trip's route, else the one the path leads to, else the park's
        (the same metres of street either way, FRAC)."""
        for name, marks in TRIP_NODES.items():
            if here in marks or nxt in marks:
                nodes = ROUTE_NODES[name]
                return name if here in nodes and nxt in nodes else None
        if {here, nxt} == {"door_out", "street_home"}:
            return self.trip or trip_of(nxt, list(ahead)) or "home-park"
        return None

    def outdoor_leg(self):
        """(route name, 3D nodes, (fraction here, fraction next)) when the current step is on the street between home
        and a destination, else None."""
        here, nxt = self.place, (self.path[0] if self.path else None)
        name = self.leg_route(here, nxt, self.path[1:]) if nxt else None
        if not name:
            return None
        return name, ROUTE_NODES[name], (FRAC[name][here], FRAC[name][nxt])

    def update_geo(self):
        """Real Tokyo position: how far along the current 3D leg -> between the leg's two fractions of the real route."""
        out = self.outdoor_leg()
        if not out:
            if not self.path and self.place in ("counter", "bakery_in", "bench"):
                return                                    # inside the shop / on the bench: keep the last street point
            if not self.path or self.place in ("door_in", "bed", "table", "desk", "window"):
                self.geo = None                           # at home
            return
        name, nodes, (f0, f1) = out
        leg = math.dist(PLACES[self.place], PLACES[self.path[0]])
        moved = math.dist(PLACES[self.place], (self.x, self.z))
        f = f0 + (f1 - f0) * min(1.0, moved / leg if leg else 1.0)
        lat, lng, hd = along(TOKYO["routes"][name]["latlng"], f)
        if f1 < f0:
            hd = (hd + 180) % 360
        self.geo = {"lat": round(lat, 6), "lng": round(lng, 6), "heading": round(hd), "route": name, "f": round(f, 3)}

    def snapshot(self):
        return {"x": round(self.x, 2), "z": round(self.z, 2), "heading": round(self.heading, 2),
                "walking": bool(self.path), "path": list(self.path) or None, "path_to": self.path[-1] if self.path else None,
                "activity": self.activity, "doing": self.label(),
                "pose": "walking" if self.path else ACTIVITIES[self.activity][1], "place": self.place,
                "hunger": round(self.hunger, 2), "vitals": self.body.vitals(), "boredom": round(self.boredom, 2), "bread": self.bread,
                "phone": self.phone_app if self.activity == "phone" and not self.path else None,
                "geo": self.geo, "say": self.say, "music": self.music, "food": self.food, "food_items": list(self.food_items),
                "eating": self.eating if self.activity == "eat" else None,
                "order": self.order_dish if self.activity == "order_food" else None, "courier": self.courier(self._t), "log": [{"t": e["t"], "what": e["what"]} for e in self.log[-8:]]}

    def label(self):
        if self.activity == "eat" and self.eating in EAT_LABEL:
            return EAT_LABEL[self.eating]
        if self.activity == "order_food" and self.order_dish:
            return f"ordering {self.order_dish} on the phone"
        return LABEL[self.activity]

    def to_dict(self):
        return {"place": self.place, "activity": self.activity, "until": self.until, "hunger": self.hunger,
                "food": self.food, "delivery": self.delivery, "food_items": self.food_items, "eating": self.eating,
                "order_dish": self.order_dish, "wish": self.wish,
                "boredom": self.boredom, "bread": self.bread, "desires": self.desires, "log": self.log,
                "last_chess": self.last_chess, "last_order": self.last_order, "viewer_nudge": self.viewer_nudge,
                "started": [[ts, a] for ts, a in self.started], "dur": self.dur, "trip": self.trip,
                "video_block_until": self.video_block_until,
                **({"body": self.body.to_dict()} if self.own_body else {})}
