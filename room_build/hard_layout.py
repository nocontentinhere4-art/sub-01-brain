"""Shared layout of the hard surfaces' texture atlases (#98 G5): the keycap legends, the book spines and the decals.
Pure Python: imported by tex_hard.py (which draws the atlases with Pillow) and by props_hard.py (inside Blender, which
puts the same cells on the meshes). Change a cell here and both sides follow."""

# ---------------------------------------------------------------- edge wear through the vertex colours
# glTF vertex colours never exceed 1, so a lighter worn edge needs the base lifted first: tex_hard writes `oak_diff_hard.jpg`
# = oak_diff x GAIN["oak"] (and the door's), and props_hard sets the vertex colour to 1/gain everywhere but the worn edges
GAIN = {"oak": 1.16, "door": 1.22}

# ---------------------------------------------------------------- keyboard (tenkeyless, generic legends, no maker's logo)
# rows of (legend, width in key units, kind); kind: "" plain, "mod" modifier (lighter), "acc" accent (orange); None = a gap
U = 0.01905                                         # one key unit (19.05 mm)
KEY_ROWS = [
    [("Esc", 1, "acc"), (None, 1, ""), ("F1", 1, "mod"), ("F2", 1, "mod"), ("F3", 1, "mod"), ("F4", 1, "mod"), (None, 0.5, ""),
     ("F5", 1, "mod"), ("F6", 1, "mod"), ("F7", 1, "mod"), ("F8", 1, "mod"), (None, 0.5, ""),
     ("F9", 1, "mod"), ("F10", 1, "mod"), ("F11", 1, "mod"), ("F12", 1, "mod"), (None, 0.5, ""), ("Prt", 1, "mod"), ("Scr", 1, "mod"), ("Pau", 1, "mod")],
    [("`", 1, ""), ("1", 1, ""), ("2", 1, ""), ("3", 1, ""), ("4", 1, ""), ("5", 1, ""), ("6", 1, ""), ("7", 1, ""), ("8", 1, ""), ("9", 1, ""),
     ("0", 1, ""), ("-", 1, ""), ("=", 1, ""), ("Back", 2, "mod"), (None, 0.5, ""), ("Ins", 1, "mod"), ("Home", 1, "mod"), ("PgUp", 1, "mod")],
    [("Tab", 1.5, "mod"), ("Q", 1, ""), ("W", 1, ""), ("E", 1, ""), ("R", 1, ""), ("T", 1, ""), ("Y", 1, ""), ("U", 1, ""), ("I", 1, ""), ("O", 1, ""),
     ("P", 1, ""), ("[", 1, ""), ("]", 1, ""), ("\\", 1.5, ""), (None, 0.5, ""), ("Del", 1, "mod"), ("End", 1, "mod"), ("PgDn", 1, "mod")],
    [("Caps", 1.75, "mod"), ("A", 1, ""), ("S", 1, ""), ("D", 1, ""), ("F", 1, ""), ("G", 1, ""), ("H", 1, ""), ("J", 1, ""), ("K", 1, ""),
     ("L", 1, ""), (";", 1, ""), ("'", 1, ""), ("Enter", 2.25, "acc")],
    [("Shift", 2.25, "mod"), ("Z", 1, ""), ("X", 1, ""), ("C", 1, ""), ("V", 1, ""), ("B", 1, ""), ("N", 1, ""), ("M", 1, ""), (",", 1, ""),
     (".", 1, ""), ("/", 1, ""), ("Shift", 2.75, "mod"), (None, 1.5, ""), ("^", 1, "mod")],
    [("Ctrl", 1.25, "mod"), ("Fn", 1.25, "mod"), ("Alt", 1.25, "mod"), ("", 6.25, ""), ("Alt", 1.25, "mod"), ("Fn", 1.25, "mod"),
     ("Menu", 1.25, "mod"), ("Ctrl", 1.25, "mod"), (None, 0.5, ""), ("<", 1, "mod"), ("v", 1, "mod"), (">", 1, "mod")],
]
KEY_ATLAS = (1024, 512)                              # the legends atlas; one cell per key, 64 px a key unit, 64 px tall
KEY_CELL = 64
KEY_COLOURS = {"": "#2c2d31", "mod": "#3a3b40", "acc": "#e2621b"}
KEY_LEGEND = {"": "#d9dadf", "mod": "#c9cad0", "acc": "#fff1e6"}


def keycap_cells():
    """every key with its legend cell: [(row, x0 (key units from the left), legend, width units, kind, (u0, v0, u1, v1))],
    plus the plain side cells in SIDE_CELLS. UVs are glTF-style (v = 0 at the top of the image)"""
    W, H = KEY_ATLAS; out = []; cx = cy = 0
    for r, row in enumerate(KEY_ROWS):
        x = 0.0
        for legend, wu, kind in row:
            if legend is None:
                x += wu; continue
            w = int(round(KEY_CELL * wu))
            if cx + w > W: cx = 0; cy += KEY_CELL
            out.append((r, x, legend, wu, kind, (cx / W, cy / H, (cx + w) / W, (cy + KEY_CELL) / H)))
            cx += w; x += wu
    # three plain cells (the caps' sides, one per colour) at the end of the last row
    sides = {}
    for kind in ("", "mod", "acc"):
        if cx + KEY_CELL > W: cx = 0; cy += KEY_CELL
        sides[kind] = (cx / W, cy / H, (cx + KEY_CELL) / W, (cy + KEY_CELL) / H); cx += KEY_CELL
    assert cy + KEY_CELL <= H, "the keycap atlas is full"
    return out, sides


# ---------------------------------------------------------------- books: 16 spine designs, their covers, a page block, 4 manga
SPINE_ATLAS = (1024, 1024)
N_SPINES = 16
# [base colour, band colour, text colour, title, kind]; generic titles, no real books
SPINES = [
    ("#2d3e57", "#d8c9a7", "#f1e9da", "DESIGN", "en"), ("#a33b2e", "#f1e9da", "#f1e9da", "東京の夜", "jp"), ("#d8c9a7", "#2d3e57", "#2d3e57", "物語", "jp"),
    ("#3f5b45", "#e9e4d8", "#e9e4d8", "STRUCTURES", "en"), ("#c58b3a", "#1f1f24", "#1f1f24", "料理の本", "jp"), ("#1f1f24", "#e2621b", "#e9e4d8", "ATLAS", "en"),
    ("#6c5a7a", "#f1e9da", "#f1e9da", "音楽理論", "jp"), ("#e9e4d8", "#a33b2e", "#2d2d33", "CITY WALKS", "en"), ("#8a4b2f", "#f1e9da", "#f1e9da", "旅の記録", "jp"),
    ("#46708c", "#e9e4d8", "#e9e4d8", "PHYSICS", "en"), ("#b9a27a", "#2d3e57", "#2d3e57", "数学", "jp"), ("#59302c", "#d8c9a7", "#d8c9a7", "NOTES", "en"),
    ("#f1e9da", "#3f5b45", "#3f5b45", "植物図鑑", "jp"), ("#2a2a2e", "#c9c2b4", "#c9c2b4", "SLEEP", "en"), ("#cc5a3b", "#f1e9da", "#f1e9da", "漫画", "jp"),
    ("#4a5670", "#e2621b", "#f1e9da", "KICHIJOJI", "en"),
]
MANGA = [("#e9e4d8", "#d8433a", "#d8433a"), ("#2d4a6b", "#f2c12e", "#f2c12e"), ("#f2c12e", "#1f1f24", "#1f1f24"), ("#1f1f24", "#e9e4d8", "#e9e4d8")]


def spine_uv(i):
    """the spine strip of design i (64 x 512 px, the book's height along v)"""
    return (i * 64 / 1024, 0.0, (i + 1) * 64 / 1024, 0.5)


def cover_uv(i):
    """the cover of design i (64 x 256 px: a plain colour with a faint title band)"""
    return (i * 64 / 1024, 0.5, (i + 1) * 64 / 1024, 0.75)


PAGES_UV = (0.0, 0.75, 0.25, 1.0)                    # the page block (256 x 256): cream paper with fine lines


def manga_uv(i):
    return ((256 + i * 64) / 1024, 0.75, (256 + (i + 1) * 64) / 1024, 1.0)


# ---------------------------------------------------------------- decals (alpha blended quads): name -> pixel box in a 1024 atlas
DECAL_ATLAS = (1024, 1024)
DECALS = {
    "scuff_a": (0, 0, 256, 256), "scuff_b": (256, 0, 512, 256), "scratches": (512, 0, 768, 256), "dust": (768, 0, 1024, 256),
    "ring": (0, 256, 128, 384), "wall_scuff": (128, 256, 384, 384), "tape": (384, 256, 512, 320), "label": (384, 320, 512, 384),
    "sticker_cat": (512, 256, 640, 384), "sticker_fuji": (640, 256, 768, 384), "sticker_tokyo": (768, 256, 896, 384), "sticker_star": (896, 256, 1024, 384),
    "sticker_record": (0, 384, 128, 512), "sticker_smile": (128, 384, 256, 512), "sticker_wave": (256, 384, 384, 512), "sticker_onigiri": (384, 384, 512, 512),
    "floor_wear": (512, 384, 1024, 896), "drip": (0, 512, 128, 768), "dust_edge": (128, 512, 512, 640),
}


def decal_uv(name):
    x0, y0, x1, y1 = DECALS[name]; W, H = DECAL_ATLAS
    return (x0 / W, y0 / H, x1 / W, y1 / H)
