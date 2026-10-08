"""A made-up car poster for the room's wall (an original drawing, CC0; no real car, maker or badge): a low 80s-style coupe
with pop-up headlights in profile against a striped sunset over a coastal road, with a title. It replaces the record sleeve
in the posters atlas's square slot C; the page pastes it there (web/room.html, "Tripo props"; ?props=old: the sleeve).

    python room_build/poster_car.py          # -> web/room/poster_car.webp (512 x 512)
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
S = 2                                                       # drawn at 2x, then downsampled (clean edges)
W = 512 * S
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
img = Image.new("RGB", (W, W)); d = ImageDraw.Draw(img)


def grad(y0, y1, top, bot):
    for y in range(y0, y1):
        k = (y - y0) / max(1, y1 - y0 - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * k) for i in range(3)))


grad(0, int(W * 0.62), (34, 20, 70), (255, 120, 90))        # dusk sky
r, cx, cy = int(W * 0.24), W // 2, int(W * 0.60)            # the striped sun on the horizon
sun = Image.new("L", (W, W), 0); sd = ImageDraw.Draw(sun); sd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
for i in range(6):
    y = cy - int(r * 0.05) + int(r * 0.13 * i); sd.rectangle((0, y, W, y + 3 * S + i * 2 * S), fill=0)
img.paste((255, 214, 110), (0, 0), sun)
d.rectangle((0, int(W * 0.60), W, int(W * 0.68)), fill=(40, 52, 96))                       # the sea
for i in range(5):
    y = int(W * 0.61) + i * 8 * S; d.line([(int(W * 0.30), y), (int(W * 0.70), y)], fill=(255, 190, 120), width=S)
d.rectangle((0, int(W * 0.68), W, W), fill=(28, 28, 36))                                    # the road
for x in range(0, W, 60 * S):
    d.rectangle((x, int(W * 0.86), x + 34 * S, int(W * 0.87)), fill=(240, 230, 210))

# the coupe in profile (facing left): a long wedge, a low glasshouse, pop-up lamps, wheels
y0 = int(W * 0.80)                                          # the sill line
body = [(int(W * 0.10), y0), (int(W * 0.12), int(W * 0.745)), (int(W * 0.30), int(W * 0.715)), (int(W * 0.40), int(W * 0.66)),
        (int(W * 0.62), int(W * 0.655)), (int(W * 0.76), int(W * 0.70)), (int(W * 0.90), int(W * 0.715)), (int(W * 0.91), y0)]
d.polygon(body, fill=(214, 40, 52))
d.polygon([(int(W * 0.42), int(W * 0.67)), (int(W * 0.50), int(W * 0.668)), (int(W * 0.50), int(W * 0.712)), (int(W * 0.36), int(W * 0.716))], fill=(30, 34, 52))
d.polygon([(int(W * 0.52), int(W * 0.667)), (int(W * 0.61), int(W * 0.665)), (int(W * 0.70), int(W * 0.708)), (int(W * 0.52), int(W * 0.712))], fill=(30, 34, 52))
d.line([(int(W * 0.12), int(W * 0.755)), (int(W * 0.90), int(W * 0.735))], fill=(250, 210, 200), width=2 * S)   # the shoulder line
d.rectangle((int(W * 0.16), int(W * 0.728), int(W * 0.24), int(W * 0.738)), fill=(245, 245, 235))                 # a raised pop-up lamp
d.rectangle((int(W * 0.86), int(W * 0.742), int(W * 0.905), int(W * 0.758)), fill=(255, 60, 60))                 # the tail lamp
d.rectangle((int(W * 0.10), int(W * 0.79), int(W * 0.91), int(W * 0.805)), fill=(24, 24, 28))                   # the bumpers and sill
for wx in (0.25, 0.76):                                      # wheels
    c, rr = int(W * wx), int(W * 0.055)
    d.ellipse((c - rr, y0 - rr + 4 * S, c + rr, y0 + rr + 4 * S), fill=(18, 18, 20))
    d.ellipse((c - rr // 2, y0 - rr // 2 + 4 * S, c + rr // 2, y0 + rr // 2 + 4 * S), fill=(180, 180, 190))
d.text((int(W * 0.07), int(W * 0.06)), "MIDNIGHT", font=ImageFont.truetype(SANS, 52 * S), fill=(255, 240, 220))
d.text((int(W * 0.07), int(W * 0.06) + 60 * S), "COUPE", font=ImageFont.truetype(SANS, 52 * S), fill=(255, 196, 120))
d.text((int(W * 0.07), int(W * 0.06) + 126 * S), "COASTAL ROAD  /  1989", font=ImageFont.truetype(SANS, 13 * S), fill=(255, 230, 210))
img = img.resize((512, 512), Image.LANCZOS)
out = ROOT / "web/room/poster_car.webp"
img.save(out, quality=88)
print(out, out.stat().st_size, "bytes")
