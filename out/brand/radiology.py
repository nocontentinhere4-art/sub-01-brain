"""Real-data brand set: SUB-01's actual T1 slices (skull-stripped) laid out like radiology film."""
import nibabel as nib
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

MONO = "/System/Library/Fonts/SFNSMono.ttf"
ORANGE = (255, 106, 0)
t = nib.load("out/t1_brain_1mm.nii.gz")
v = nib.as_closest_canonical(t).get_fdata()                 # RAS: x=R, y=A, z=S
v = v / np.percentile(v[v > 0], 99.5)


def font(s, bold=False):
    f = ImageFont.truetype(MONO, s)
    if bold:
        try:
            f.set_variation_by_name("Bold")
        except Exception:
            pass
    return f


def axial(z):
    sl = np.rot90(np.clip(v[:, :, z], 0, 1))                # nose up, radiological look
    ys, xs = np.nonzero(v.max(2).T[::-1] > 0.05)
    im = Image.fromarray((sl * 255).astype(np.uint8))
    return im.crop((xs.min() - 6, ys.min() - 6, xs.max() + 6, ys.max() + 6))


zs = np.nonzero(v.max((0, 1)) > 0.05)[0]
z0, z1 = zs.min(), zs.max()


def grain(im, amount=10):
    n = np.random.default_rng(0).normal(0, amount, (im.height, im.width, 1))
    a = np.clip(np.asarray(im).astype(float) + n, 0, 255).astype(np.uint8)
    return Image.fromarray(a)


# ---- banner 1500x500: film strip of 7 real axial slices on the right ----
B = Image.new("RGB", (1500, 500), (4, 4, 6))
d = ImageDraw.Draw(B)
levels = np.linspace(z0 + 0.40 * (z1 - z0), z0 + 0.86 * (z1 - z0), 6).astype(int)
x = 560
for i, z in enumerate(levels):
    s = axial(z)
    s = s.resize((int(s.width * 190 / s.height), 190), Image.LANCZOS).convert("RGB")
    B.paste(s, (x + i * 152, 165))
    d.text((x + i * 152 + 2, 364), f"z{z - z0:03d}", font=font(13), fill=(110, 110, 120))
d.text((560, 128), "SUB-01   T1W   SES-2022   0.8 MM   AXIAL", font=font(15), fill=(150, 150, 160))
d.rectangle((560, 390, 560 + 6 * 152 - 12, 391), fill=(60, 60, 66))
# orange label tape, like a hand-labelled film
d.rectangle((70, 70, 470, 190), fill=ORANGE)
d.text((92, 78), "SUB-01", font=font(96, True), fill=(10, 10, 10))
d.text((74, 222), "A real human brain.", font=font(31), fill=(224, 224, 232))
d.text((74, 264), "Wired on-chain.", font=font(31), fill=(224, 224, 232))
d.text((74, 330), "real MRI · OpenNeuro ds000031", font=font(18), fill=(120, 120, 134))
grain(B, 6).save("out/brand/x_banner_film.png")

# ---- avatar 400x400: one real mid-axial slice with orange 01 tag ----
s = axial(int(z0 + 0.62 * (z1 - z0)))
s = s.resize((int(s.width * 330 / s.height), 330), Image.LANCZOS).convert("RGB")
A = Image.new("RGB", (400, 400), (4, 4, 6))
A.paste(s, ((400 - s.width) // 2, 22))
d = ImageDraw.Draw(A)
d.rectangle((150, 300, 250, 352), fill=ORANGE)
d.text((168, 302), "01", font=font(44, True), fill=(10, 10, 10))
grain(A, 5).save("out/brand/x_logo_film.png")
print("saved film set")
