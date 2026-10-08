"""X profile assets from the real fibre renders: out/x_logo*.png (400x400), out/x_banner.png (1500x500)."""
from PIL import Image, ImageDraw, ImageFont, ImageOps

MONO = "/System/Library/Fonts/SFNSMono.ttf"


def font(size, weight=None):
    f = ImageFont.truetype(MONO, size)
    if weight:
        try:
            f.set_variation_by_name(weight)
        except Exception:
            pass
    return f


def crop_content(img, pad=0.06):
    """Crop to the non-black content, square-ish padding."""
    bbox = img.convert("L").point(lambda v: 255 if v > 12 else 0).getbbox()
    x0, y0, x1, y1 = bbox
    px, py = int((x1 - x0) * pad), int((y1 - y0) * pad)
    return img.crop((max(0, x0 - px), max(0, y0 - py), min(img.width, x1 + px), min(img.height, y1 + py)))


# ---- logo: top view of the fibres, centred on black ----
raw = crop_content(Image.open("out/logo_raw.png").convert("RGB"), pad=0.04)
side = int(max(raw.size) / 0.84)   # X crops avatars to a circle: keep the brain inside it
sq = Image.new("RGB", (side, side), "black")
sq.paste(raw, ((side - raw.width) // 2, (side - raw.height) // 2))
logo = sq.resize((400, 400), Image.LANCZOS)
logo.save("out/x_logo.png")

# variant with a small "01" tag for when the name must be readable at avatar size
tag = logo.copy()
d = ImageDraw.Draw(tag)
f = font(46, "Bold")
t = "01"
w = d.textlength(t, font=f)
d.rounded_rectangle((200 - w / 2 - 14, 318, 200 + w / 2 + 14, 374), radius=8, fill=(0, 0, 0))
d.text((200 - w / 2, 320), t, font=f, fill=(255, 255, 255))
tag.save("out/x_logo_01.png")

# ---- banner 1500x500: side view on the right, clinical text on the left (avatar covers bottom-left) ----
B = Image.new("RGB", (1500, 500), "black")
br = crop_content(Image.open("out/banner_raw.png").convert("RGB"), pad=0.03)
scale = 470 / br.height
br = br.resize((int(br.width * scale), 470), Image.LANCZOS)
B.paste(br, (1500 - br.width - 40, 15))
d = ImageDraw.Draw(B)
d.text((70, 70), "SUB-01", font=font(96, "Bold"), fill=(240, 240, 246))
d.text((74, 190), "A real human brain.", font=font(30), fill=(210, 210, 222))
d.text((74, 232), "Traced from MRI. Wired on-chain.", font=font(30), fill=(210, 210, 222))
d.text((74, 300), "923,000 nerve fibres · 214 regions · live", font=font(20), fill=(128, 128, 146))
B.save("out/x_banner.png")
print("saved out/x_logo.png, out/x_logo_01.png, out/x_banner.png")
