"""Final X assets from the Higgsfield concepts: 1500x500 banners with typeset text, 400x400 avatars."""
from PIL import Image, ImageDraw, ImageFont

MONO = "/System/Library/Fonts/SFNSMono.ttf"


def font(size, bold=False):
    f = ImageFont.truetype(MONO, size)
    if bold:
        try:
            f.set_variation_by_name("Bold")
        except Exception:
            pass
    return f


def banner(src, out, y_center=0.5, shift=0):
    im = Image.open(src).convert("RGB")
    w, h = im.size
    ch = w // 3                                          # 3:1 crop
    top = int(min(max(0, y_center * h - ch / 2), h - ch))
    im = im.crop((0, top, w, top + ch)).resize((1500, 500), Image.LANCZOS)
    if shift:                                            # push the art right to free the text area
        c = Image.new("RGB", (1500, 500), "black")
        c.paste(im, (shift, 0))
        im = c
    d = ImageDraw.Draw(im)
    d.text((70, 58), "SUB-01", font=font(104, True), fill=(244, 244, 250))
    d.text((76, 190), "A real human brain.", font=font(31), fill=(214, 214, 226))
    d.text((76, 232), "Wired on-chain.", font=font(31), fill=(214, 214, 226))
    d.text((76, 298), "923,135 fibres  ·  214 regions", font=font(19), fill=(125, 125, 145))
    im.save(out)


def avatar(src, out, fill=0.8):
    im = Image.open(src).convert("RGB")
    bbox = im.convert("L").point(lambda v: 255 if v > 18 else 0).getbbox()
    art = im.crop(bbox)
    side = int(max(art.size) / fill)                      # keep the art inside X's circular crop
    c = Image.new("RGB", (side, side), "black")
    c.paste(art, ((side - art.width) // 2, (side - art.height) // 2))
    c.resize((400, 400), Image.LANCZOS).save(out)


banner("bannerB_chart.png", "x_banner_onchain.png", y_center=0.5)
banner("bannerA_scan.png", "x_banner_scan.png", y_center=0.47)
avatar("logoD_01.png", "x_logo_01fibres.png", fill=0.64)
avatar("logoC_scan.png", "x_logo_scan.png", fill=0.84)
avatar("logoA_seal.png", "x_logo_seal.png", fill=0.95)
print("done")
