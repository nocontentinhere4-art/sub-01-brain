"""Scenes, times, sizes and close-ups of the visual QA suite (issue #98, G8).

A scene is the `life` part of a websocket tick (life.py's snapshot) plus how the page should be driven into it: a
scene to start from (`before`), the simulated seconds to run after the switch (`settle_s`) and what the page's
`pose()` must then report (`at`, `clip`), which is the "did he get there" check. Hours are the Tokyo clock the page
previews with `?debug&hour=H`; the fake server also writes the matching `sleep.clock`.
"""

VITALS = {"hr_bpm": 66, "resp_per_min": 14, "glucose_mg_dl": 92}
READING = {"title": "Inokashira Park", "url": "https://en.wikipedia.org/wiki/Inokashira_Park", "host": "en.wikipedia.org",
           "kind": "wiki", "why": "visual QA fixture",
           "extract": "Inokashira Park straddles Musashino and Mitaka in western Tokyo. The park's pond feeds the Kanda River; "
                      "rowing boats, a small zoo and the Ghibli Museum sit at its edges, and in spring the cherry trees around "
                      "the water draw crowds from Kichijōji station a few minutes' walk away."}


def life(activity, place, doing, **extra):
    d = {"x": 0, "z": 0, "heading": 0, "walking": False, "activity": activity, "doing": doing, "pose": "standing",
         "place": place, "hunger": 0.3, "vitals": VITALS, "boredom": 0.2, "bread": 0, "phone": None, "geo": None,
         "say": "", "music": None, "food": 0, "food_items": [], "eating": None, "order": None, "courier": None, "log": []}
    d.update(extra)
    return d


# name -> (life, sleep stage, before-scene or None, settle seconds, expected pose() at, expected clip substring[, prep JS])
# prep: JavaScript run in the page after the snap and before the settle (debug hooks only; reset by the next snap)
# Walking, the desk and the phone in bed play room/boy_moves.glb's clips (#76: walk, type, lie_phone); eating keeps the
# first seated clip (Chair_Sit_Idle) under its own layer, sleep the first sleep clip (`?moves=old`: all the first clips)
SCENES = {
    # (#98 G3: web/room/boy_motion.js's CHOICE table says which clip each activity plays, after boy_moves.glb: #80's
    # typing clip at the desk (desk: ual), the first seated clip under the eating layer (eating: ual), and the ARDY clips
    # m_idle standing, m_walk walking, m_window at the sill; the phone in bed keeps #80's lie_phone)
    "desk":     (life("research", "desk", "reading at the computer", reading=READING), "AWAKE", None, 1.0, "desk", "type"),
    # (the page eats on top of the seated clip: arm IK, chopsticks, the dish; the eat clip itself is not played)
    # (the seated clip under the eating layer: the sit idle, or #80's typing clip for a tick after a desk scene; the
    # eating itself is the dish and the arm IK, checked by eye in the shots)
    "eating":   (life("eat", "table", "eating ramen from the delivery", eating="ramen", food=1, hunger=0.7), "AWAKE", None, 3.6, "desk", None),
    # asleep the duvet comes up over him in ~2.2 s (room.html DUV.w): settle 4 s so the shot shows him covered
    "sleeping": (life("sleep", "bed", "sleeping"), "NREM", None, 4.0, "bedlie", "Sleep"),
    # the side pose he turns into now and then (every 3-8 min): forced through the page's ROLL hook (debug)
    "sleeping_side": (life("sleep", "bed", "sleeping"), "NREM", None, 7.0, "bedlie", "Sleep", "if (window.ROLL) ROLL.force = ROLL.ang;"),
    # the phone in bed: from lying asleep the page keeps him lying and brings the phone up (phone_lie: the lie_phone clip)
    "phone":    (life("phone", "bed", "in bed scrolling the phone", phone="shorts", boredom=0.6), "AWAKE", "sleeping", 2.5, "bedlie", "lie_phone"),
    # standing just inside the door (an activity the page does not know, at the door place: it stands him there)
    "door":     (life("home", "door_in", "just in at the door"), "AWAKE", None, 1.0, "door", "m_idle"),
    # walking: from the door to the desk; the harness stops mid-walk (see harness.walk_until). As the server sends it
    # since #104: `walking` true with `path` and `path_to` (before that the page treated him as already at the desk)
    "walking":  (life("research", "desk", "walking to the desk", reading=READING, walking=True, path=["desk"], path_to="desk"), "AWAKE", "door", None, None, "m_walk"),
    "window":   (life("window", "window", "looking out of the window"), "AWAKE", None, 1.5, "sill", "m_window"),
    # lying awake on the bed with music on (#68), for the phone-camera test only (not in the shot sets)
    "music":    (life("listen_music", "bed", "listening to music", music={"id": "qa", "title": "QA track", "artist": "QA", "playing": True}),
                 "AWAKE", None, 3.0, "bedlie", None),
    # at the computer with a page on the screen, as the live server sends it once his walk there has ended (the caption:
    # "at the computer" only once the page has him seated; tests/visual/test_arrival.py)
    "computer": (life("research", "desk", "reading at the computer", reading=READING,
                      screen={"device": "desk", "id": "qa1", "kind": "page", "title": "Inokashira Park - Wikipedia"}), "AWAKE", None, 1.0, "desk", None),
}
# the hour each scene is shot at in the core set, and the full matrix
# preview/room-mh: when room/boy.glb is the MakeHuman rig (web/room/boy_mh.js drives it with its own clips) pose()
# reports these instead: the desk modes (desk_type_ik / desk_mouse_ik / desk_watch), the stand and the lie stills, the
# recorded walk loop; eating plays room_eat, asleep he lies as room_bedtime ends (mh_sleep)
MH_CLIP = {"desk": "desk_", "eating": "room_eat", "sleeping": "mh_sleep", "sleeping_side": "mh_sleep", "phone": "mh_lie",
           "door": "mh_stand", "walking": "room_walk", "window": "mh_stand", "music": None}


def makehuman_rig():
    """room/boy.glb is the MakeHuman rig (163 bones, fingers named metacarpal1.L ...), or the page plays room/char_v5.glb
    (preview/room-v5: v5 under room/boy_mh.js, its bones given the MakeHuman names by room/char_v5.js)."""
    import json, struct
    from pathlib import Path
    room = Path(__file__).resolve().parents[2] / "web" / "room"
    if (room / "char_v5.glb").exists() and 'load("room/char_v5.glb")' in (room.parent / "room.html").read_text():
        return True
    raw = (room / "boy.glb").read_bytes()
    n = struct.unpack_from("<I", raw, 12)[0]
    g = json.loads(raw[20:20 + n])
    return any(nd.get("name") == "metacarpal1.L" for nd in g.get("nodes", []))


NATURAL_HOUR = {"computer": 14, "desk": 14, "eating": 19, "sleeping": 23, "sleeping_side": 23, "phone": 23, "door": 8, "walking": 8, "window": 19, "music": 23}
HOURS = (8, 14, 19, 23)
SIZES = {"1280": (1280, 800, False), "390": (390, 844, True)}
SHOT_SIZES = ("1280", "390")                                  # the shot sets; the phone-camera test adds two more phones
PHONE_SIZES = {"360": (360, 780, True), "430": (430, 932, True)}
SIZES.update(PHONE_SIZES)

# close-ups: name -> (scene to take it in, hour, JS camera recipe name in page_checks.js)
CLOSEUPS = {
    "face":  ("walking", 14, "face"),       # mid-room, lit from the window, nothing in front of him
    "hands": ("desk", 14, "hands"),         # over his shoulder: hands on the keyboard and the armrests
    "grip":  ("phone", 14, "grip"),         # the phone hand (hand_phone.glb) in bed by day
    "feet":  ("door", 14, "feet"),
    "socks": ("window", 14, "socks"),       # the laundry hanger's socks and towel
    "desk":  ("desk", 19, "desk"),          # the desk at dusk, lamp on
    "bed":   ("sleeping", 14, "bed"),       # him on the bed by day (the pose and the duvet's drape)
    "duvet": ("window", 14, "duvet"),       # the empty bed: duvet, pillow, sheet
    "night": ("sleeping", 23, "bed"),       # the same bed at night: what the dark room shows
    "side":  ("sleeping_side", 14, "bed"),  # asleep on his side under the duvet (#108)
}
CORE_SCENES = [s for s in SCENES if s not in ("sleeping_side", "computer", "music")]   # the side pose: its close-up; the computer: test_arrival.py; music: test_phone_camera.py
CORE_SHOTS = [(s, NATURAL_HOUR[s], "1280") for s in CORE_SCENES] + [("desk", 14, "390"), ("sleeping", 23, "390")]
FULL_SHOTS = [(s, h, z) for s in CORE_SCENES for h in HOURS for z in SHOT_SIZES] + [("sleeping_side", 23, "1280"), ("sleeping_side", 14, "390")]


# the brain page's per-region activity (214 regions of web/brain.json): a flat resting level, enough to colour the fibres
ACT_FLAT = [0.3] * 214


def clock(hour):
    h = int(hour) % 24
    return f"{h:02d}:{int(round((hour - int(hour)) * 60)) % 60:02d}"


def scene(name):
    """(life, stage, before, settle_s, at, clip, prep) with prep "" when absent."""
    t = SCENES[name]
    return tuple(t) + ("",) * (7 - len(t))


def tick(name, hour):
    lf, stage, *_ = SCENES[name]
    return {"type": "tick", "life": lf, "sleep": {"stage": stage, "clock": clock(hour)},
            "neuro": {"DA": 1.0, "5HT": 1.0, "NE": 0.9, "ACh": 1.1}, "events": [], "trades": [], "groups": {}}
