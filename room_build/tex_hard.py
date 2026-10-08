"""The hard surfaces' textures (#98 G5): the plank floor (Poly Haven `wooden_floor_01`, graded, with wear), the plaster
walls, roughness maps with micro-variation for oak, plastic, painted metal and brushed steel, and three original atlases:
the keycap legends, the book spines and the decals (dust, scuffs, scratches, stickers without brands).
Writes into tex_final/ (run by tex_prep.py, or on its own: python tex_hard.py). Pillow + numpy only."""
import os, math, random
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import hard_layout as L

R = os.path.dirname(os.path.abspath(__file__)); T = f"{R}/tex"; O = f"{R}/tex_final"; os.makedirs(O, exist_ok=True)
JP = f"{R}/fonts/NotoSansJP.ttf"; SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"; SANS_R = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def hexrgb(h): h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def font(path, size, wght=None):
    f = ImageFont.truetype(path, size)
    if wght:
        try: f.set_variation_by_axes([wght])
        except Exception: pass
    return f


def fnoise(n, beta=1.8, seed=0, cut=1):
    """tileable fractal noise in [0, 1]: random phases with a 1/f^beta spectrum (periodic by construction)"""
    rng = np.random.default_rng(seed)
    fy = np.fft.fftfreq(n)[:, None]; fx = np.fft.rfftfreq(n)[None, :]
    f = np.sqrt(fx * fx + fy * fy); f[0, 0] = 1.0
    amp = f ** (-beta / 2); amp[f < cut / n] = 0; amp[0, 0] = 0
    spec = amp * np.exp(2j * np.pi * rng.random((n, n // 2 + 1)))
    im = np.fft.irfft2(spec, s=(n, n)); im -= im.min(); im /= max(1e-9, im.max())
    return im


def stretch_noise(n, seed, sx=40):
    """brushed-metal streaks: fine noise smeared along x"""
    rng = np.random.default_rng(seed); a = rng.random((n, n))
    k = np.ones(sx) / sx
    a = np.apply_along_axis(lambda r: np.convolve(np.concatenate([r[-sx:], r, r[:sx]]), k, mode="same")[sx:-sx], 1, a)
    a -= a.min(); a /= max(1e-9, a.max()); return a


def normal_from_height(h, strength, wrap=True):
    """a tangent-space (OpenGL) normal map from a height field in [0, 1]"""
    dx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * strength
    dy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * strength
    nz = np.ones_like(h); n = np.stack([-dx, dy, nz], -1); n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return Image.fromarray(np.clip((n * 0.5 + 0.5) * 255, 0, 255).astype(np.uint8), "RGB")


def mr_image(rough, metal=0):
    """glTF metallicRoughness: G = roughness, B = metalness"""
    g = np.clip(rough * 255, 0, 255).astype(np.uint8); z = np.zeros_like(g)
    return Image.merge("RGB", [Image.fromarray(z), Image.fromarray(g), Image.fromarray(np.full_like(g, metal))])


def save(im, name, q=92):
    p = f"{O}/{name}"; (im.save(p, quality=q) if p.endswith(".jpg") else im.save(p)); print("wrote", name, im.size)


def load_gray(path, n): return np.asarray(Image.open(path).convert("L").resize((n, n), Image.LANCZOS), dtype=np.float32) / 255


# ---------------------------------------------------------------- the floor: lacquered planks, graded, worn where he walks
def floor():
    n = 2048; src = f"{T}/wooden_floor_01"
    im = Image.open(f"{src}/Diffuse.jpg").convert("RGB").resize((n, n), Image.LANCZOS)
    im = ImageEnhance.Color(im).enhance(0.9); im = ImageEnhance.Contrast(im).enhance(1.04)
    a = np.asarray(im, dtype=np.float32) / 255
    ao = load_gray(f"{src}/AO.jpg", n) ** 0.6                              # the gaps between the planks read darker
    worn = fnoise(n, 2.2, seed=3); worn = np.clip((worn - 0.55) / 0.3, 0, 1) ** 1.5    # worn patches: lighter, paler
    lum = a.mean(-1, keepdims=True)
    a = a * (1 - 0.35 * worn[..., None]) + (lum * 1.12 + 0.03) * 0.35 * worn[..., None]
    a *= ao[..., None]
    # a few fine scratches
    sc = Image.new("L", (n, n), 0); d = ImageDraw.Draw(sc); rng = random.Random(9)
    for _ in range(70):
        x, y = rng.randrange(n), rng.randrange(n); ang = rng.uniform(-0.4, 0.4) + rng.choice((0, math.pi / 2)); ln = rng.uniform(40, 260)
        d.line((x, y, x + ln * math.cos(ang), y + ln * math.sin(ang)), fill=rng.randint(60, 140), width=1)
    sc = np.asarray(sc.filter(ImageFilter.GaussianBlur(0.6)), dtype=np.float32) / 255
    a = a * (1 - 0.5 * sc[..., None]) + 0.5 * sc[..., None] * np.array([0.78, 0.70, 0.58])
    a = a * np.array([1.02, 1.0, 0.95])
    save(Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8)), "floor_diff.jpg", 90)
    save(Image.open(f"{src}/nor_gl.jpg").convert("RGB").resize((n, n), Image.LANCZOS), "floor_nor.jpg")
    m = 1024; r = load_gray(f"{src}/Rough.jpg", m) * 0.85 + 0.03
    w2 = np.asarray(Image.fromarray((worn * 255).astype(np.uint8)).resize((m, m), Image.LANCZOS), dtype=np.float32) / 255
    r = r + 0.18 * w2 + 0.04 * (fnoise(m, 1.2, seed=4) - 0.5)                   # worn lacquer is matte, the rest keeps a sheen
    save(mr_image(r), "floor_mr.jpg")


# ---------------------------------------------------------------- walls: plaster with faint blotches and a roughness map
def walls():
    n = 1024; base = np.array(hexrgb("#e8e0d2"), dtype=np.float32) / 255
    st = load_gray(f"{T}/white_stucco/Diffuse.jpg", n); st = 1 + 0.30 * (st / st.mean() - 1)
    blot = fnoise(n, 2.4, seed=11); blot = 1 + 0.045 * (blot - 0.5) * 2
    roller = fnoise(n, 1.4, seed=12); roller = 1 + 0.02 * (roller - 0.5) * 2
    a = base[None, None, :] * (st * blot * roller)[..., None]
    save(Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8)), "wall_diff.jpg")
    m = 512; r = 0.86 + 0.10 * (fnoise(m, 1.6, seed=13) - 0.5) * 2 - 0.06 * np.clip((fnoise(m, 2.6, seed=14) - 0.6) / 0.3, 0, 1)
    save(mr_image(r), "wall_mr.jpg")


# ---------------------------------------------------------------- roughness and relief for oak, plastic, painted and brushed metal
def surfaces():
    m = 512
    r = load_gray(f"{T}/oak_veneer_01/Rough.jpg", m) * 0.8 + 0.06
    r += 0.10 * (fnoise(m, 1.8, seed=21) - 0.5) * 2                            # finish that varies across the board
    gloss = np.clip((fnoise(m, 2.4, seed=22) - 0.62) / 0.25, 0, 1); r -= 0.14 * gloss   # polished patches where hands rest
    sc = Image.new("L", (m, m), 0); d = ImageDraw.Draw(sc); rng = random.Random(23)
    for _ in range(60):
        x, y = rng.randrange(m), rng.randrange(m); ang = rng.uniform(-0.5, 0.5) + rng.choice((0, 0, math.pi / 2)); ln = rng.uniform(12, 80)
        d.line((x, y, x + ln * math.cos(ang), y + ln * math.sin(ang)), fill=rng.randint(90, 200), width=1)
    r += 0.35 * np.asarray(sc.filter(ImageFilter.GaussianBlur(0.5)), dtype=np.float32) / 255     # scratches are matte
    save(mr_image(r), "oak_mr.jpg")
    # plastic: fine grain + smudges
    n = 256; h = fnoise(n, 1.2, seed=31, cut=8)
    save(normal_from_height(h, 1.4), "plastic_nor.jpg")
    n = 512; r = 0.46 + 0.07 * (fnoise(n, 1.0, seed=32) - 0.5) * 2
    smudge = np.clip((fnoise(n, 2.6, seed=33) - 0.58) / 0.28, 0, 1); r -= 0.16 * smudge    # fingerprints: glossier
    save(mr_image(r), "plastic_mr.jpg")
    # painted steel / white goods: orange peel + smudges
    h = fnoise(256, 1.8, seed=41, cut=4)
    save(normal_from_height(h, 0.9), "white_nor.jpg")
    r = 0.34 + 0.06 * (fnoise(n, 1.2, seed=42) - 0.5) * 2
    smudge = np.clip((fnoise(n, 2.8, seed=43) - 0.6) / 0.25, 0, 1); r += 0.14 * smudge       # hand marks on a glossy finish: matte
    save(mr_image(r), "white_mr.jpg")
    # brushed metal: streaks along x
    s = stretch_noise(n, 51, 48)
    save(normal_from_height(s * 0.5 + 0.25 * fnoise(n, 0.7, seed=52, cut=30), 0.7), "metal_nor.jpg")
    r = 0.30 + 0.12 * (s - 0.5) * 2 + 0.05 * (fnoise(n, 1.5, seed=53) - 0.5) * 2
    save(mr_image(r, 255), "metal_mr.jpg")


# ---------------------------------------------------------------- the keycap legends atlas
def keycaps():
    W, H = L.KEY_ATLAS; S = 2
    A = Image.new("RGB", (W * S, H * S), "#2c2d31"); d = ImageDraw.Draw(A)
    cells, sides = L.keycap_cells()
    f_big = font(SANS, 15 * S); f_small = font(SANS, 10 * S); f_tiny = font(SANS_R, 8 * S)
    for r, x, legend, wu, kind, (u0, v0, u1, v1) in cells:
        box = (int(u0 * W * S), int(v0 * H * S), int(u1 * W * S), int(v1 * H * S))
        d.rectangle(box, fill=L.KEY_COLOURS[kind])
        # a hint of the cap's dish: the centre a touch lighter
        cx, cy = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
        col = tuple(min(255, int(c * 1.07)) for c in hexrgb(L.KEY_COLOURS[kind]))
        d.ellipse((cx - (box[2] - box[0]) * 0.36, cy - (box[3] - box[1]) * 0.36, cx + (box[2] - box[0]) * 0.36, cy + (box[3] - box[1]) * 0.36), fill=col)
        if not legend: continue
        f = f_big if len(legend) == 1 else f_small if len(legend) <= 4 else f_tiny
        d.text((box[0] + 7 * S, box[1] + 6 * S), legend, font=f, fill=L.KEY_LEGEND[kind])
    for kind, (u0, v0, u1, v1) in sides.items():
        d.rectangle((int(u0 * W * S), int(v0 * H * S), int(u1 * W * S), int(v1 * H * S)), fill=L.KEY_COLOURS[kind])
    save(A.resize((W, H), Image.LANCZOS), "keycaps.png")


# ---------------------------------------------------------------- book spines, covers, pages, manga
def spines():
    W, H = L.SPINE_ATLAS; S = 2
    A = Image.new("RGB", (W * S, H * S), "#d8c9a7"); d = ImageDraw.Draw(A)
    rng = random.Random(5)
    for i, (base, band, text, title, kind) in enumerate(L.SPINES):
        x0, x1 = i * 64 * S, (i + 1) * 64 * S; h = 512 * S
        d.rectangle((x0, 0, x1, h), fill=base)
        style = i % 4
        if style == 0: d.rectangle((x0, int(h * 0.08), x1, int(h * 0.12)), fill=band); d.rectangle((x0, int(h * 0.86), x1, int(h * 0.88)), fill=band)
        elif style == 1: d.rectangle((x0, 0, x1, int(h * 0.16)), fill=band); d.rectangle((x0, int(h * 0.90), x1, h), fill=band)
        elif style == 2: d.rectangle((x0 + 6 * S, int(h * 0.05), x1 - 6 * S, int(h * 0.95)), outline=band, width=2 * S)
        else: d.ellipse((x0 + 20 * S, int(h * 0.80), x1 - 20 * S, int(h * 0.80) + 24 * S), fill=band)
        # the title runs down the spine: drawn flat, then turned
        tw, th = (56 * S, 300 * S); strip = Image.new("RGBA", (th, tw), (0, 0, 0, 0)); sd = ImageDraw.Draw(strip)
        f = font(JP, 24 * S, 700) if kind == "jp" else font(SANS, 20 * S)
        sd.text((8 * S, (tw - 28 * S) // 2), title, font=f, fill=text)
        strip = strip.rotate(-90, expand=True)
        A.paste(strip, (x0 + 4 * S, int(h * 0.18)), strip)
        # a small number / author band
        sd2 = ImageDraw.Draw(A); sd2.text((x0 + 18 * S, int(h * 0.92)), f"{rng.randint(1, 30):02d}", font=font(SANS_R, 9 * S), fill=text)
        # the cover: plain, a faint title band
        d.rectangle((x0, 512 * S, x1, 768 * S), fill=base); d.rectangle((x0 + 10 * S, 540 * S, x1 - 10 * S, 548 * S), fill=band)
    # wear: the spines' head and tail lighter, with a little noise
    a = np.asarray(A, dtype=np.float32) / 255
    ys = np.arange(H * S)[:, None, None] / (512 * S)
    wear = np.clip(1 - np.minimum(ys, 1 - ys) / 0.05, 0, 1) * (ys < 1.0)
    nz = np.asarray(Image.fromarray((fnoise(256, 1.0, seed=61) * 255).astype(np.uint8)).resize((W * S, H * S)), dtype=np.float32)[..., None] / 255
    a = a * (1 - 0.25 * wear * nz) + 0.25 * wear * nz * 0.9
    A = Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(A)
    # the page block: cream with fine lines
    x0, y0, x1, y1 = 0, 768 * S, 256 * S, 1024 * S; d.rectangle((x0, y0, x1, y1), fill="#efe6d2")
    for y in range(y0, y1, 3 * S): d.line((x0, y, x1, y), fill=rng.choice(("#e4dac4", "#f4ecdb", "#ded3bb")), width=1)
    # manga spines (short, a coloured band and a volume number)
    for i, (base, band, text) in enumerate(L.MANGA):
        x0, x1 = (256 + i * 64) * S, (256 + (i + 1) * 64) * S; y0, y1 = 768 * S, 1024 * S
        d.rectangle((x0, y0, x1, y1), fill=base); d.rectangle((x0, y0, x1, y0 + 30 * S), fill=band)
        d.text((x0 + 22 * S, y1 - 40 * S), str(i + 3), font=font(SANS, 16 * S), fill=text)
        strip = Image.new("RGBA", (160 * S, 56 * S), (0, 0, 0, 0)); sd = ImageDraw.Draw(strip)
        sd.text((6 * S, 10 * S), "少年", font=font(JP, 22 * S, 900), fill=text); strip = strip.rotate(-90, expand=True)
        A.paste(strip, (x0 + 4 * S, y0 + 40 * S), strip)
    save(A.resize((W, H), Image.LANCZOS), "spines.png")


# ---------------------------------------------------------------- decals: dust, scuffs, scratches, stains, stickers (no brands)
def decals():
    W, H = L.DECAL_ATLAS; S = 2
    A = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0)); d = ImageDraw.Draw(A); rng = random.Random(77)

    def box(name): x0, y0, x1, y1 = L.DECALS[name]; return x0 * S, y0 * S, x1 * S, y1 * S

    def soft_blob(name, col, alpha, n_blobs, rmin, rmax, blur):
        x0, y0, x1, y1 = box(name); layer = Image.new("L", (x1 - x0, y1 - y0), 0); ld = ImageDraw.Draw(layer)
        for _ in range(n_blobs):
            r = rng.uniform(rmin, rmax) * S; cx, cy = rng.uniform(r, x1 - x0 - r), rng.uniform(r, y1 - y0 - r)
            ld.ellipse((cx - r, cy - r * rng.uniform(0.4, 1), cx + r, cy + r * rng.uniform(0.4, 1)), fill=rng.randint(80, 255))
        layer = layer.filter(ImageFilter.GaussianBlur(blur * S))
        # fade to the cell's edge so that nothing cuts off
        ar = np.asarray(layer, dtype=np.float32) / 255; h, w = ar.shape
        yy, xx = np.mgrid[0:h, 0:w]; edge = np.minimum(np.minimum(xx, w - 1 - xx), np.minimum(yy, h - 1 - yy)) / (0.18 * min(w, h))
        ar = ar * np.clip(edge, 0, 1) * alpha
        col_im = Image.new("RGBA", (w, h), (*hexrgb(col), 255)); col_im.putalpha(Image.fromarray((ar * 255).astype(np.uint8)))
        A.paste(col_im, (x0, y0), col_im)

    soft_blob("scuff_a", "#2a2622", 0.55, 14, 10, 40, 6)
    soft_blob("scuff_b", "#3a3028", 0.45, 9, 14, 60, 9)
    soft_blob("dust", "#d9d2c4", 0.55, 40, 6, 36, 5)
    soft_blob("dust_edge", "#cfc8ba", 0.5, 40, 6, 24, 5)
    soft_blob("floor_wear", "#e8dcc4", 0.35, 30, 40, 120, 18)
    # scratches: thin light lines
    x0, y0, x1, y1 = box("scratches"); layer = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0)); ld = ImageDraw.Draw(layer)
    for _ in range(26):
        ax, ay = rng.uniform(20, x1 - x0 - 20), rng.uniform(20, y1 - y0 - 20); ang = rng.uniform(0, math.pi); ln = rng.uniform(30, 160) * S
        ld.line((ax, ay, ax + ln * math.cos(ang), ay + ln * math.sin(ang)), fill=(235, 225, 205, rng.randint(90, 170)), width=rng.choice((1, 1, 2)) * S)
    layer = layer.filter(ImageFilter.GaussianBlur(0.6 * S)); A.paste(layer, (x0, y0), layer)
    # a coffee ring
    x0, y0, x1, y1 = box("ring"); layer = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0)); ld = ImageDraw.Draw(layer)
    c = (x1 - x0) // 2; r = int(c * 0.78)
    ld.ellipse((c - r, c - r, c + r, c + r), outline=(92, 60, 30, 150), width=4 * S)
    ld.arc((c - r, c - r, c + r, c + r), 20, 140, fill=(92, 60, 30, 210), width=6 * S)
    layer = layer.filter(ImageFilter.GaussianBlur(1.2 * S)); A.paste(layer, (x0, y0), layer)
    # a wall rub: a horizontal grey smear
    x0, y0, x1, y1 = box("wall_scuff"); layer = Image.new("L", (x1 - x0, y1 - y0), 0); ld = ImageDraw.Draw(layer)
    for _ in range(16):
        cx = rng.uniform(0.15, 0.85) * (x1 - x0); cy = rng.uniform(0.3, 0.7) * (y1 - y0); w = rng.uniform(30, 90) * S; h = rng.uniform(4, 14) * S
        ld.ellipse((cx - w, cy - h, cx + w, cy + h), fill=rng.randint(60, 200))
    layer = layer.filter(ImageFilter.GaussianBlur(5 * S)); ar = np.asarray(layer, dtype=np.float32) / 255 * 0.45
    col_im = Image.new("RGBA", layer.size, (70, 66, 62, 255)); col_im.putalpha(Image.fromarray((ar * 255).astype(np.uint8))); A.paste(col_im, (x0, y0), col_im)
    # a drip stain (down a wall or a fridge door)
    x0, y0, x1, y1 = box("drip"); layer = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0)); ld = ImageDraw.Draw(layer)
    for k in range(3):
        cx = (x1 - x0) * (0.3 + 0.2 * k); ln = (y1 - y0) * rng.uniform(0.4, 0.9)
        ld.line((cx, 10 * S, cx + rng.uniform(-6, 6) * S, ln), fill=(120, 100, 70, 70), width=rng.randint(2, 4) * S)
        ld.ellipse((cx - 5 * S, ln - 5 * S, cx + 5 * S, ln + 5 * S), fill=(120, 100, 70, 90))
    layer = layer.filter(ImageFilter.GaussianBlur(1.5 * S)); A.paste(layer, (x0, y0), layer)
    # masking tape and a plain label
    x0, y0, x1, y1 = box("tape"); d.rectangle((x0 + 4 * S, y0 + 6 * S, x1 - 4 * S, y1 - 6 * S), fill=(214, 198, 160, 215))
    for y in range(y0 + 8 * S, y1 - 8 * S, 5 * S): d.line((x0 + 6 * S, y, x1 - 6 * S, y + 1), fill=(200, 184, 146, 120), width=1)
    x0, y0, x1, y1 = box("label"); d.rectangle((x0 + 4 * S, y0 + 4 * S, x1 - 4 * S, y1 - 4 * S), fill=(245, 242, 234, 255))
    d.rectangle((x0 + 4 * S, y0 + 4 * S, x1 - 4 * S, y0 + 16 * S), fill=(214, 70, 60, 255))
    d.text((x0 + 10 * S, y0 + 22 * S), "こもの", font=font(JP, 13 * S, 500), fill=(60, 56, 50, 255))

    # stickers: white-bordered, die cut (an alpha shape), simple original drawings
    def sticker(name, draw_fn, shape="round", border="#f7f4ee"):
        x0, y0, x1, y1 = box(name); w, h = x1 - x0, y1 - y0; st = Image.new("RGBA", (w, h), (0, 0, 0, 0)); sd = ImageDraw.Draw(st)
        pad = 8 * S
        if shape == "round": sd.ellipse((pad, pad, w - pad, h - pad), fill=border)
        else: sd.rounded_rectangle((pad, pad, w - pad, h - pad), radius=12 * S, fill=border)
        draw_fn(sd, w, h)
        A.paste(st, (x0, y0), st)

    def cat(sd, w, h):
        c = w // 2; sd.ellipse((c - 34 * S, c - 26 * S, c + 34 * S, c + 34 * S), fill="#3b2a30")
        sd.polygon([(c - 32 * S, c - 10 * S), (c - 26 * S, c - 44 * S), (c - 8 * S, c - 24 * S)], fill="#3b2a30"); sd.polygon([(c + 32 * S, c - 10 * S), (c + 26 * S, c - 44 * S), (c + 8 * S, c - 24 * S)], fill="#3b2a30")
        sd.ellipse((c - 16 * S, c - 4 * S, c - 8 * S, c + 4 * S), fill="#f7f4ee"); sd.ellipse((c + 8 * S, c - 4 * S, c + 16 * S, c + 4 * S), fill="#f7f4ee")
        sd.polygon([(c - 4 * S, c + 10 * S), (c + 4 * S, c + 10 * S), (c, c + 15 * S)], fill="#f2a7b8")

    def fuji(sd, w, h):
        sd.rectangle((12 * S, 12 * S, w - 12 * S, h - 12 * S), fill="#2d3b5c")
        sd.polygon([(14 * S, h - 26 * S), (w // 2, 30 * S), (w - 14 * S, h - 26 * S)], fill="#4a5e8a")
        sd.polygon([(w // 2 - 22 * S, 52 * S), (w // 2, 30 * S), (w // 2 + 22 * S, 52 * S), (w // 2 + 12 * S, 50 * S), (w // 2, 56 * S), (w // 2 - 12 * S, 50 * S)], fill="#f7f4ee")
        sd.ellipse((w - 44 * S, 20 * S, w - 24 * S, 40 * S), fill="#d9472b")

    def tokyo(sd, w, h):
        sd.ellipse((12 * S, 12 * S, w - 12 * S, h - 12 * S), fill="#d9472b")
        f = font(JP, 30 * S, 900); sd.text((w // 2 - 30 * S, h // 2 - 36 * S), "東", font=f, fill="#f7f4ee"); sd.text((w // 2 - 2 * S, h // 2 - 2 * S), "京", font=f, fill="#f7f4ee")

    def star(sd, w, h):
        c = w // 2; pts = []
        for k in range(10):
            r = (44 if k % 2 == 0 else 20) * S; a = -math.pi / 2 + k * math.pi / 5; pts.append((c + r * math.cos(a), c + r * math.sin(a)))
        sd.polygon(pts, fill="#f2c12e")

    def record(sd, w, h):
        c = w // 2; sd.ellipse((c - 44 * S, c - 44 * S, c + 44 * S, c + 44 * S), fill="#1f1f24")
        for r in (36, 28, 20): sd.ellipse((c - r * S, c - r * S, c + r * S, c + r * S), outline="#3a3a44", width=1 * S)
        sd.ellipse((c - 14 * S, c - 14 * S, c + 14 * S, c + 14 * S), fill="#e8b23a"); sd.ellipse((c - 3 * S, c - 3 * S, c + 3 * S, c + 3 * S), fill="#f7f4ee")

    def smile(sd, w, h):
        c = w // 2; sd.ellipse((c - 44 * S, c - 44 * S, c + 44 * S, c + 44 * S), fill="#f6dd6b")
        sd.ellipse((c - 20 * S, c - 16 * S, c - 10 * S, c - 6 * S), fill="#3b3326"); sd.ellipse((c + 10 * S, c - 16 * S, c + 20 * S, c - 6 * S), fill="#3b3326")
        sd.arc((c - 26 * S, c - 20 * S, c + 26 * S, c + 28 * S), 20, 160, fill="#3b3326", width=4 * S)

    def wave(sd, w, h):
        sd.rounded_rectangle((12 * S, 12 * S, w - 12 * S, h - 12 * S), radius=10 * S, fill="#1f2a44")
        for k in range(4):
            y = 40 * S + k * 18 * S
            sd.arc((16 * S, y, 60 * S, y + 24 * S), 180, 360, fill="#7aa6c2", width=3 * S); sd.arc((56 * S, y, 100 * S, y + 24 * S), 180, 360, fill="#7aa6c2", width=3 * S)

    def onigiri(sd, w, h):
        c = w // 2; sd.polygon([(c - 40 * S, c + 36 * S), (c, c - 40 * S), (c + 40 * S, c + 36 * S)], fill="#f7f4ee")
        sd.rectangle((c - 14 * S, c + 8 * S, c + 14 * S, c + 36 * S), fill="#2e4a2b"); sd.ellipse((c - 10 * S, c - 10 * S, c - 4 * S, c - 4 * S), fill="#3b2a30"); sd.ellipse((c + 4 * S, c - 10 * S, c + 10 * S, c - 4 * S), fill="#3b2a30")

    sticker("sticker_cat", cat); sticker("sticker_fuji", fuji, "rect"); sticker("sticker_tokyo", tokyo); sticker("sticker_star", star)
    sticker("sticker_record", record); sticker("sticker_smile", smile); sticker("sticker_wave", wave, "rect"); sticker("sticker_onigiri", onigiri)
    save(A.resize((W, H), Image.LANCZOS), "decals.png")


def lifted():
    """brighter copies of tex_prep's oak and door maps: the vertex colour (1/gain) brings them back, except on worn edges"""
    for name, k in (("oak", L.GAIN["oak"]), ("door", L.GAIN["door"])):
        a = np.asarray(Image.open(f"{O}/{name}_diff.jpg").convert("RGB"), dtype=np.float32) * k
        save(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)), f"{name}_diff_hard.jpg")


def build():
    floor(); walls(); surfaces(); lifted(); keycaps(); spines(); decals()


if __name__ == "__main__":
    build()
