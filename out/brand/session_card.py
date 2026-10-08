"""Post card for X (1600x900): real render + orange SUB-01 tape + 'Session NNN' line.

    python out/brand/session_card.py 002 "First contact with the market" out/sub01_fibres_angle.png
"""
import sys

from PIL import Image, ImageDraw, ImageFont

MONO = "/System/Library/Fonts/SFNSMono.ttf"
ORANGE = (255, 106, 0)


def font(s, bold=False):
    f = ImageFont.truetype(MONO, s)
    if bold:
        try:
            f.set_variation_by_name("Bold")
        except Exception:
            pass
    return f


num, title, src = sys.argv[1], sys.argv[2], sys.argv[3]
bg = Image.open(src).convert("RGB")
bg = bg.resize((1600, int(1600 * bg.height / bg.width)), Image.LANCZOS)
C = Image.new("RGB", (1600, 900), (4, 4, 6))
C.paste(bg, (200, (900 - bg.height) // 2))                 # art right, text left
d = ImageDraw.Draw(C)
d.rectangle((60, 60, 330, 138), fill=ORANGE)
d.text((78, 64), "SUB-01", font=font(62, True), fill=(10, 10, 10))
d.text((64, 160), f"SESSION {num}", font=font(28), fill=(235, 235, 242))
d.text((64, 200), title, font=font(24), fill=(170, 170, 184))
d.text((64, 846), "real MRI · OpenNeuro ds000031 · not a mind", font=font(16), fill=(110, 110, 124))
out = f"out/brand/session_{num}.png"
C.save(out)
print(out)
