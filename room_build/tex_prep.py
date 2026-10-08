"""Prepare the room's textures: tinted diffuse maps, normal maps, roughness maps (glTF: G = roughness), and the poster atlas.
Output: tex_final/*.png|jpg  (the GLB build later converts everything to WebP)"""
import os, math, random
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps, ImageChops, ImageEnhance
R = os.path.dirname(os.path.abspath(__file__)); T = f"{R}/tex"; O = f"{R}/tex_final"; os.makedirs(O, exist_ok=True)

def hexrgb(h): h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

def tint(src, size, color, keep=0.55, gain=1.0, cavity=0.0):
    """recolour a texture: its luminance pattern (normalised to mean 1, contrast `keep`) times `color`;
    `cavity` mixes in the texture's AO map so the weave reads in the colour too"""
    im = Image.open(src).convert("L").resize((size, size), Image.LANCZOS)
    if cavity:
        ao = Image.open(os.path.join(os.path.dirname(src), "AO.jpg")).convert("L").resize((size, size), Image.LANCZOS)
        im = ImageChops.multiply(im, ao.point(lambda v: int(255 * (1 - cavity) + v * cavity)))
    px = im.load(); mean = sum(im.getdata()) / (size * size)
    c = hexrgb(color); out = Image.new("RGB", (size, size)); op = out.load()
    for y in range(size):
        for x in range(size):
            k = (1 + keep * (px[x, y] / mean - 1)) * gain
            op[x, y] = tuple(max(0, min(255, int(ch * k))) for ch in c)
    return out

def grade(src, size, sat=1.0, bright=1.0, warm=(1, 1, 1), contrast=1.0):
    im = Image.open(src).convert("RGB").resize((size, size), Image.LANCZOS)
    im = ImageEnhance.Color(im).enhance(sat); im = ImageEnhance.Brightness(im).enhance(bright); im = ImageEnhance.Contrast(im).enhance(contrast)
    r, g, b = im.split()
    return Image.merge("RGB", [ch.point(lambda v, k=k: min(255, int(v * k))) for ch, k in zip((r, g, b), warm)])

def mr(src_rough, size, scale=1.0, offset=0.0, metal=0):
    """glTF metallicRoughness: G = roughness, B = metalness"""
    r = Image.open(src_rough).convert("L").resize((size, size), Image.LANCZOS).point(lambda v: max(0, min(255, int(v * scale + offset * 255))))
    return Image.merge("RGB", [Image.new("L", (size, size), 0), r, Image.new("L", (size, size), metal)])

def nor(src, size, strength=1.0):
    im = Image.open(src).convert("RGB").resize((size, size), Image.LANCZOS)
    if strength == 1.0: return im
    r, g, b = im.split()
    f = lambda v: max(0, min(255, int(128 + (v - 128) * strength)))
    return Image.merge("RGB", [r.point(f), g.point(f), Image.new("L", (size, size), 255)])

def save(im, name, q=92):
    p = f"{O}/{name}"; (im.save(p, quality=q) if p.endswith(".jpg") else im.save(p)); print("wrote", name, im.size)

# floor: warm brown planks
save(grade(f"{T}/wood_floor/Diffuse.jpg", 2048, sat=1.0, bright=1.0, warm=(1.04, 1.0, 0.94)), "floor_diff.jpg")
save(nor(f"{T}/wood_floor/nor_gl.jpg", 2048), "floor_nor.jpg")
save(mr(f"{T}/wood_floor/Rough.jpg", 1024, 0.9, 0.02), "floor_mr.jpg")
# walls: warm off-white plaster, only its relief and a whisper of its colour
save(tint(f"{T}/white_stucco/Diffuse.jpg", 512, "#e8e0d2", keep=0.35), "wall_diff.jpg")
save(nor(f"{T}/white_stucco/nor_gl.jpg", 1024, 0.6), "wall_nor.jpg")
# oak (desk, shelf, bed): natural oak, slightly warm
save(grade(f"{T}/oak_veneer_01/Diffuse.jpg", 1024, sat=0.95, bright=1.02, warm=(1.03, 1.0, 0.95)), "oak_diff.jpg")
save(nor(f"{T}/oak_veneer_01/nor_gl.jpg", 1024, 0.7), "oak_nor.jpg")
save(mr(f"{T}/oak_veneer_01/Rough.jpg", 512, 0.85, 0.05), "oak_mr.jpg")
# door: the same veneer, darker (walnut-ish)
save(grade(f"{T}/oak_veneer_01/Diffuse.jpg", 1024, sat=1.05, bright=0.72, warm=(1.06, 0.97, 0.88)), "door_diff.jpg")
# fabrics (the textures cover ~27 cm): sheet, duvet, curtain, rug, chair
save(tint(f"{T}/cotton_jersey/Diffuse.jpg", 512, "#ece7de", keep=0.5, cavity=0.6), "sheet_diff.jpg")
save(nor(f"{T}/cotton_jersey/nor_gl.jpg", 512, 0.8), "sheet_nor.jpg")
save(tint(f"{T}/waffle_pique_cotton/Diffuse.jpg", 512, "#4a5670", keep=0.6, cavity=0.6), "duvet_diff.jpg")
save(nor(f"{T}/waffle_pique_cotton/nor_gl.jpg", 512, 1.0), "duvet_nor.jpg")
save(tint(f"{T}/rough_linen/Diffuse.jpg", 512, "#cfc5b0", keep=0.6, cavity=0.6), "curtain_diff.jpg")   # lighter: the panels read as lit through
save(nor(f"{T}/rough_linen/nor_gl.jpg", 512, 0.9), "curtain_nor.jpg")
save(tint(f"{T}/poly_wool_herringbone/Diffuse.jpg", 512, "#8d8478", keep=0.9, cavity=0.6), "rug_diff.jpg")
save(nor(f"{T}/poly_wool_herringbone/nor_gl.jpg", 512, 1.0), "rug_nor.jpg")
save(nor(f"{T}/jersey_melange/nor_gl.jpg", 512, 1.0), "fabric_nor.jpg")
# the soft goods of #98 (props_soft.py): socks (knit), the towel (terry), the hoodie (sweatshirt fleece) with ribbed
# cuffs (corduroy ribs), the backpack's weave, the floor cushion, the tote's canvas, the jeans
save(nor(f"{T}/knitted_fleece/nor_gl.jpg", 512, 1.0), "knit_nor.jpg")
save(nor(f"{T}/ribbed_corduroy/nor_gl.jpg", 512, 1.0), "rib_nor.jpg")
save(tint(f"{T}/terry_cloth/Diffuse.jpg", 512, "#e0a35a", keep=0.55, cavity=0.5), "terry_diff.jpg")
save(nor(f"{T}/terry_cloth/nor_gl.jpg", 512, 1.0), "terry_nor.jpg")
save(tint(f"{T}/jogging_melange/Diffuse.jpg", 512, "#5c6372", keep=1.0, cavity=0.6), "hoodie_diff.jpg")
save(nor(f"{T}/jogging_melange/nor_gl.jpg", 512, 1.0), "hoodie_nor.jpg")
save(nor(f"{T}/bi_stretch/nor_gl.jpg", 512, 1.0), "bag_nor.jpg")
save(tint(f"{T}/cotton_jersey/Diffuse.jpg", 512, "#b4903f", keep=0.9, cavity=0.8), "cushion_diff.jpg")
save(tint(f"{T}/rough_linen/Diffuse.jpg", 512, "#d6cbb3", keep=0.6, cavity=0.6), "canvas_diff.jpg")
save(tint(f"{T}/denim_fabric_05/Diffuse.jpg", 512, "#3a4763", keep=1.2, cavity=0.7), "denim_diff.jpg")
save(nor(f"{T}/denim_fabric_05/nor_gl.jpg", 512, 1.0), "denim_nor.jpg")

# ---------- posters (one atlas, 1024 x 512): A 2:3 | B 2:3 | C square + D 2:1 ----------
JP = f"{R}/fonts/NotoSansJP.ttf"; SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
def font(path, size, wght=None):
    f = ImageFont.truetype(path, size)
    if wght:
        try: f.set_variation_by_axes([wght])
        except Exception: pass
    return f
S = 2   # draw at 2x, then downsample (clean edges)
A = Image.new("RGB", (1024 * S, 512 * S), "#000"); d = ImageDraw.Draw(A)
def vgrad(box, top, bot):
    x0, y0, x1, y1 = box; t, b = hexrgb(top), hexrgb(bot)
    for y in range(y0, y1):
        k = (y - y0) / max(1, y1 - y0 - 1); d.line([(x0, y), (x1 - 1, y)], fill=tuple(int(t[i] + (b[i] - t[i]) * k) for i in range(3)))
# A: city pop night - striped sun over a skyline, 東京
w, h = 341 * S, 512 * S
vgrad((0, 0, w, h), "#1b1f4a", "#e0566b")
cx, cy, r = w // 2, int(h * 0.50), int(w * 0.33)
sun = Image.new("L", (w, h), 0); sd = ImageDraw.Draw(sun); sd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
for i in range(7):                               # the stripes cut through the lower half of the sun
    y = cy + int(r * (0.1 + i * 0.14)); sd.rectangle((0, y, w, y + int(4 * S + i * 1.6 * S)), fill=0)
sunc = Image.new("RGB", (w, h)); scd = ImageDraw.Draw(sunc)
for y in range(h): k = min(1, max(0, (y - (cy - r)) / (2 * r))); scd.line([(0, y), (w, y)], fill=(255, int(214 - 120 * k), int(90 - 40 * k)))
A.paste(sunc, (0, 0), sun)
random.seed(7); x = 0
while x < w:                                     # skyline
    bw = random.randint(18, 46) * S // 2; bh = random.randint(int(h * 0.12), int(h * 0.34)); d.rectangle((x, h - bh, x + bw, h), fill="#141631")
    for wy in range(h - bh + 8, h - 6, 10 * S // 2):
        for wx in range(x + 4, x + bw - 4, 8 * S // 2):
            if random.random() < 0.28: d.rectangle((wx, wy, wx + 2 * S, wy + 3 * S), fill="#ffcf7a")
    x += bw + random.randint(0, 3) * S
tx = int(w * 0.66)                               # a tower with a red light
d.polygon([(tx - 26, h), (tx + 26, h), (tx + 4, int(h * 0.36)), (tx - 4, int(h * 0.36))], fill="#141631"); d.ellipse((tx - 5, int(h * 0.36) - 12, tx + 5, int(h * 0.36) - 2), fill="#ff3b30")
fj = font(JP, 92 * S // 2 * 2 // 2, 900)
d.text((int(w * 0.08), int(h * 0.05)), "東", font=font(JP, 74 * S, 900), fill="#fff4e6"); d.text((int(w * 0.08), int(h * 0.05) + 80 * S), "京", font=font(JP, 74 * S, 900), fill="#fff4e6")
d.text((int(w * 0.62), int(h * 0.07)), "TOKYO", font=font(SANS, 15 * S), fill="#fff4e6"); d.text((int(w * 0.62), int(h * 0.07) + 20 * S), "NIGHT FM", font=font(SANS, 11 * S), fill="#ffd0a0")
d.text((int(w * 0.62), int(h * 0.07) + 36 * S), "87.6", font=font(SANS, 11 * S), fill="#ffd0a0")
# B: Mt Fuji, minimal
ox = 341 * S; w2 = 341 * S
d.rectangle((ox, 0, ox + w2, h), fill="#f1e9da")
d.ellipse((ox + int(w2 * 0.56), int(h * 0.16), ox + int(w2 * 0.86), int(h * 0.16) + int(w2 * 0.30)), fill="#d9472b")
base = int(h * 0.74); peak = int(h * 0.36)
d.polygon([(ox - 10, base), (ox + int(w2 * 0.38), peak), (ox + int(w2 * 0.62), peak), (ox + w2 + 10, base)], fill="#2d3b5c")
d.polygon([(ox + int(w2 * 0.30), peak + int((base - peak) * 0.22)), (ox + int(w2 * 0.38), peak), (ox + int(w2 * 0.62), peak), (ox + int(w2 * 0.70), peak + int((base - peak) * 0.22)),
           (ox + int(w2 * 0.6), peak + int((base - peak) * 0.16)), (ox + int(w2 * 0.52), peak + int((base - peak) * 0.25)), (ox + int(w2 * 0.44), peak + int((base - peak) * 0.15))], fill="#fbf7ef")
for i in range(6):                               # waves
    y = base + 14 * S + i * 15 * S; d.line([(ox + 20 * S, y), (ox + w2 - 20 * S, y)], fill="#2d3b5c", width=3 * S if i == 0 else 2 * S)
d.text((ox + 24 * S, 22 * S), "富士山", font=font(JP, 30 * S, 700), fill="#2d3b5c")
d.text((ox + 24 * S, 62 * S), "FUJI 3776 M", font=font(SANS, 10 * S), fill="#2d3b5c")
d.text((ox + 24 * S, h - 30 * S), "KICHIJOJI PRINT CLUB", font=font(SANS, 9 * S), fill="#2d3b5c")
# C: record sleeve (square): concentric arcs
ox = 683 * S; s3 = 341 * S
d.rectangle((ox, 0, ox + s3, s3), fill="#e8b23a")
for i in range(9):
    rr = int(s3 * (0.46 - i * 0.05)); col = ["#1f2a44", "#e8b23a"][i % 2]
    d.ellipse((ox + s3 // 2 - rr + int(s3 * 0.12), s3 // 2 - rr + int(s3 * 0.1), ox + s3 // 2 + rr + int(s3 * 0.12), s3 // 2 + rr + int(s3 * 0.1)), fill=col)
d.rectangle((ox, 0, ox + int(s3 * 0.36), s3), fill="#1f2a44")
d.text((ox + 18 * S, 20 * S), "CITY", font=font(SANS, 22 * S), fill="#e8b23a"); d.text((ox + 18 * S, 48 * S), "POP", font=font(SANS, 22 * S), fill="#e8b23a")
d.text((ox + 18 * S, s3 - 40 * S), "夜明け", font=font(JP, 20 * S, 700), fill="#f4ead8")
# D: a ticket / photo strip (2:1)
oy = 341 * S; d.rectangle((ox, oy, ox + s3, oy + 171 * S), fill="#f4efe6")
for i in range(3):
    px0 = ox + 12 * S + i * 108 * S; d.rectangle((px0, oy + 14 * S, px0 + 98 * S, oy + 120 * S), fill=["#7aa6c2", "#d98b6a", "#8fb58a"][i])
    d.ellipse((px0 + 30 * S, oy + 40 * S, px0 + 68 * S, oy + 78 * S), fill="#f4efe6")
d.text((ox + 14 * S, oy + 132 * S), "井の頭公園  2024.04", font=font(JP, 14 * S, 500), fill="#3a3a3a")
A = A.resize((1024, 512), Image.LANCZOS)
save(A, "posters.png")

# ---------- pinboard (512 x 512, original drawing): cork, a calendar page, notes and doodles, pins ----------
import calendar
S = 2; P = 512 * S
random.seed(21)
cork = Image.new("RGB", (P, P), "#b48a5c"); cd = ImageDraw.Draw(cork)
for _ in range(26000):                            # cork granules: dark and light specks
    x, y = random.randrange(P), random.randrange(P); r = random.choice((1, 1, 2, 2, 3))
    c = random.choice(("#8f6a43", "#9c7650", "#c79d6c", "#d1aa78", "#7d5a37")); cd.ellipse((x, y, x + r, y + r), fill=c)
cork = cork.filter(ImageFilter.GaussianBlur(0.8))
def card(w, h, col, lines=None):
    return Image.new("RGBA", (w, h), col)
def pin(img, x, y, col):
    d_ = ImageDraw.Draw(img); r = 7 * S
    d_.ellipse((x - r + 3, y - r + 4, x + r + 3, y + r + 4), fill=(0, 0, 0, 90))
    d_.ellipse((x - r, y - r, x + r, y + r), fill=col); d_.ellipse((x - r // 2 - 2, y - r // 2 - 2, x - 1, y - 1), fill="#ffffff")
def stick(note, x, y, ang):
    """paste a note (RGBA) rotated by ang degrees with a soft shadow; returns its top centre (for the pin)"""
    rot = note.rotate(ang, expand=True, resample=Image.BICUBIC)
    sh = Image.new("RGBA", rot.size, (0, 0, 0, 0)); sh.putalpha(rot.split()[3].point(lambda a: int(a * 0.35)))
    sh = sh.filter(ImageFilter.GaussianBlur(5 * S)); cork.paste((0, 0, 0), (x + 4 * S, y + 6 * S), sh.split()[3])
    cork.paste(rot, (x, y), rot); return x + rot.size[0] // 2, y + 10 * S
hand = lambda sz, w=400: font(JP, sz * S, w)
# the calendar page: October 2026 (1 Oct is a Thursday), a few days circled
cal = card(250 * S, 236 * S, "#fbfaf6"); g = ImageDraw.Draw(cal)
g.rectangle((0, 0, 250 * S, 40 * S), fill="#2d3b5c")
g.text((12 * S, 6 * S), "10月", font=hand(22, 700), fill="#ffffff"); g.text((80 * S, 12 * S), "OCTOBER 2026", font=font(SANS, 12 * S), fill="#cfd8ec")
for i, k in enumerate("日月火水木金土"):
    g.text((14 * S + i * 33 * S, 46 * S), k, font=hand(11, 500), fill="#d9472b" if i == 0 else "#2d3b5c" if i == 6 else "#555555")
weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(2026, 10)
for r_, wk in enumerate(weeks):
    for c_, dday in enumerate(wk):
        if not dday: continue
        x0_, y0_ = 12 * S + c_ * 33 * S, 66 * S + r_ * 32 * S
        g.text((x0_ + 2 * S, y0_), str(dday), font=font(SANS, 11 * S), fill="#d9472b" if c_ == 0 else "#333333")
        if dday in (9, 17, 24): g.ellipse((x0_ - 4 * S, y0_ - 5 * S, x0_ + 22 * S, y0_ + 18 * S), outline="#e2621b", width=2 * S)
        if dday == 2: g.line((x0_ - 2 * S, y0_ + 16 * S, x0_ + 20 * S, y0_ - 2 * S), fill="#7a7a7a", width=2 * S)
cx_, cy_ = stick(cal, 22 * S, 24 * S, 1.5); pin(cork, cx_, cy_, "#d9472b")
# a yellow sticky: a short shopping / chores list, ticked
n1 = card(118 * S, 118 * S, "#f6dd6b"); g = ImageDraw.Draw(n1)
for i, t in enumerate(("牛乳", "たまご", "洗濯", "電気代")):
    g.text((14 * S, 12 * S + i * 25 * S), t, font=hand(15, 500), fill="#3b3326")
    if i in (0, 2): g.line((84 * S, 22 * S + i * 25 * S, 90 * S, 28 * S + i * 25 * S, 102 * S, 12 * S + i * 25 * S), fill="#c23a2b", width=3 * S)
cx_, cy_ = stick(n1, 290 * S, 30 * S, -5); pin(cork, cx_, cy_, "#3a7bd5")
# a pink sticky: a cat doodle
n2 = card(104 * S, 104 * S, "#f2a7b8"); g = ImageDraw.Draw(n2); k_ = S
g.ellipse((26 * k_, 34 * k_, 78 * k_, 82 * k_), outline="#3b2a30", width=3 * k_)
g.polygon([(30 * k_, 44 * k_), (34 * k_, 20 * k_), (46 * k_, 36 * k_)], outline="#3b2a30", width=3 * k_); g.polygon([(74 * k_, 44 * k_), (70 * k_, 20 * k_), (58 * k_, 36 * k_)], outline="#3b2a30", width=3 * k_)
g.ellipse((40 * k_, 52 * k_, 45 * k_, 57 * k_), fill="#3b2a30"); g.ellipse((59 * k_, 52 * k_, 64 * k_, 57 * k_), fill="#3b2a30")
g.line((52 * k_, 62 * k_, 48 * k_, 67 * k_), fill="#3b2a30", width=2 * k_); g.line((52 * k_, 62 * k_, 56 * k_, 67 * k_), fill="#3b2a30", width=2 * k_)
for s_ in (-1, 1): g.line((52 * k_ + s_ * 10 * k_, 62 * k_, 52 * k_ + s_ * 30 * k_, 58 * k_), fill="#3b2a30", width=2 * k_)
cx_, cy_ = stick(n2, 400 * S, 150 * S, 7); pin(cork, cx_, cy_, "#2fa36b")
# an index card: a hand-drawn way to the park (station, park, a star)
n3 = card(170 * S, 110 * S, "#eef3f8"); g = ImageDraw.Draw(n3)
for y_ in range(22 * S, 110 * S, 14 * S): g.line((0, y_, 170 * S, y_), fill="#bcd0e6", width=1 * S)
g.line((10 * S, 80 * S, 70 * S, 60 * S, 120 * S, 70 * S, 160 * S, 30 * S), fill="#2d3b5c", width=3 * S)
g.rectangle((8 * S, 72 * S, 30 * S, 90 * S), outline="#2d3b5c", width=2 * S); g.text((10 * S, 92 * S), "駅", font=hand(11, 500), fill="#2d3b5c")
g.ellipse((118 * S, 14 * S, 160 * S, 44 * S), outline="#2fa36b", width=3 * S); g.text((122 * S, 46 * S), "公園", font=hand(11, 500), fill="#2fa36b")
g.text((10 * S, 4 * S), "パン屋 →", font=hand(12, 500), fill="#c23a2b")
cx_, cy_ = stick(n3, 250 * S, 290 * S, -3); pin(cork, cx_, cy_, "#f0b429")
# a white note: a small mountain sketch and a time
n4 = card(120 * S, 90 * S, "#ffffff"); g = ImageDraw.Draw(n4)
g.line((8 * S, 70 * S, 46 * S, 22 * S, 66 * S, 44 * S, 80 * S, 30 * S, 112 * S, 70 * S), fill="#555555", width=3 * S)
g.text((12 * S, 72 * S), "土 7:00", font=hand(11, 500), fill="#333333")
cx_, cy_ = stick(n4, 40 * S, 300 * S, 4); pin(cork, cx_, cy_, "#d9472b")
# a ticket stub (no venue or brand): seat and time
n5 = card(150 * S, 58 * S, "#e9d8bd"); g = ImageDraw.Draw(n5)
g.line((112 * S, 0, 112 * S, 58 * S), fill="#9b8a6c", width=1 * S)
g.text((10 * S, 8 * S), "映画  18:30", font=hand(13, 600), fill="#4a3b25"); g.text((10 * S, 32 * S), "G-12", font=font(SANS, 12 * S), fill="#4a3b25")
g.text((118 * S, 20 * S), "No.", font=font(SANS, 8 * S), fill="#4a3b25")
cx_, cy_ = stick(n5, 70 * S, 420 * S, -8); pin(cork, cx_, cy_, "#3a7bd5")
# a small green sticky: a doodled plant
n6 = card(84 * S, 84 * S, "#a8d8a0"); g = ImageDraw.Draw(n6)
g.rectangle((30 * S, 52 * S, 54 * S, 76 * S), outline="#2e4a2b", width=3 * S); g.line((42 * S, 52 * S, 42 * S, 22 * S), fill="#2e4a2b", width=3 * S)
g.ellipse((22 * S, 18 * S, 42 * S, 34 * S), outline="#2e4a2b", width=3 * S); g.ellipse((42 * S, 26 * S, 62 * S, 42 * S), outline="#2e4a2b", width=3 * S)
cx_, cy_ = stick(n6, 410 * S, 400 * S, -4); pin(cork, cx_, cy_, "#f0b429")
cork = cork.resize((512, 512), Image.LANCZOS)
save(cork, "pinboard.png")

# ---------- the hard surfaces (#98 G5): the plank floor, plaster, roughness micro-variation, the keycap / spine / decal atlases ----------
import tex_hard; tex_hard.build()
