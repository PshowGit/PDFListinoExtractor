"""Genera assets/icona.ico (piu' risoluzioni): un foglio con la piega, una banda "PDF" e una griglia.

    uv run python tools/crea_icona.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LATO = 256
DESTINAZIONE = Path(__file__).resolve().parent.parent / "assets" / "icona.ico"


def disegna() -> Image.Image:
    img = Image.new("RGBA", (LATO, LATO), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # foglio con angolo piegato
    x0, y0, x1, y1, piega = 40, 16, 216, 240, 52
    d.polygon([(x0, y0), (x1 - piega, y0), (x1, y0 + piega), (x1, y1), (x0, y1)], fill=(255, 255, 255, 255),
              outline=(60, 60, 60, 255), width=6)
    d.polygon([(x1 - piega, y0), (x1 - piega, y0 + piega), (x1, y0 + piega)], fill=(200, 200, 200, 255),
              outline=(60, 60, 60, 255), width=5)
    # banda rossa "PDF"
    d.rectangle((x0 + 3, 70, x1 - 3, 122), fill=(200, 40, 40, 255))
    try:
        font = ImageFont.truetype("arialbd.ttf", 44)
    except OSError:
        font = ImageFont.load_default()
    d.text(((x0 + x1) / 2, 96), "PDF", fill="white", font=font, anchor="mm")
    # griglia verde da foglio di calcolo
    gx0, gy0, gx1, gy1 = 64, 140, 192, 220
    d.rectangle((gx0, gy0, gx1, gy1), fill=(225, 242, 228, 255), outline=(30, 120, 60, 255), width=5)
    for y in range(gy0 + 20, gy1, 20):
        d.line((gx0, y, gx1, y), fill=(30, 120, 60, 255), width=4)
    for x in (gx0 + 43, gx0 + 86):
        d.line((x, gy0, x, gy1), fill=(30, 120, 60, 255), width=4)
    return img


if __name__ == "__main__":
    DESTINAZIONE.parent.mkdir(exist_ok=True)
    disegna().save(DESTINAZIONE, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(DESTINAZIONE)
