"""Draw FINN's app icons (the same dark "F" tile as the in-app logo).

    python web/scripts/make_icons.py      (needs Pillow; run from the repo root)

Writes public/icons/{icon,maskable}-{192,512}.png, app/icon.png and app/apple-icon.png.
"Maskable" icons are full-bleed with the letter inside the central safe zone, as
Android's adaptive launcher icons crop them.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WEB = Path(__file__).resolve().parents[1]
INK, PAPER = (21, 23, 27, 255), (244, 243, 238, 255)
FONTS = [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


def font(px):
    for f in FONTS:
        if Path(f).exists():
            return ImageFont.truetype(f, px)
    return ImageFont.load_default(px)


def tile(size, *, maskable):
    s = size * 4                                     # draw large, then downsample for smooth edges
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if maskable:
        d.rectangle([0, 0, s, s], fill=INK)
        letter = int(s * 0.46)
    else:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=INK)
        letter = int(s * 0.62)
    f = font(letter)
    box = d.textbbox((0, 0), "F", font=f)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((s - w) / 2 - box[0], (s - h) / 2 - box[1]), "F", font=f, fill=PAPER)
    return img.resize((size, size), Image.LANCZOS)


def main():
    out = WEB / "public" / "icons"
    out.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        tile(size, maskable=False).save(out / f"icon-{size}.png", optimize=True)
        tile(size, maskable=True).save(out / f"maskable-{size}.png", optimize=True)
    tile(64, maskable=False).save(WEB / "app" / "icon.png", optimize=True)
    tile(180, maskable=True).convert("RGB").save(WEB / "app" / "apple-icon.png", optimize=True)
    print("icons written to", out)


if __name__ == "__main__":
    main()
