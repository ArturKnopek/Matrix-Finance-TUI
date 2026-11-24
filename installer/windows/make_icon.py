"""
Generuje ikonę programu (installer/windows/MatrixFinance.ico) — potrzebny Pillow:
    pip install pillow && python installer/windows/make_icon.py
Ikona jest w repozytorium, więc zwykle nie trzeba jej generować ponownie.
"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
GREEN = (0, 255, 65)
DIM = (0, 90, 25)
BG = (4, 12, 6)
FONT_CANDIDATES = ["DejaVuSansMono-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
                   "consolab.ttf", "C:/Windows/Fonts/consolab.ttf"]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(size: int) -> Image.Image:
    scale = 4  # rysujemy większe i zmniejszamy (gładkie krawędzie)
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = int(s * 0.18)
    border = max(scale, int(s * 0.035))
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=BG + (255,))
    if size >= 48:  # cyfrowy deszcz w tle (przycięty do zaokrąglonego kwadratu)
        rain = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        rd = ImageDraw.Draw(rain)
        rnd = random.Random(7)
        f = _font(int(s * 0.075))
        cols = 9
        for c in range(cols):
            x = int((c + 0.5) * s / cols) - int(s * 0.02)
            length = rnd.randint(3, 8)
            start = rnd.randint(-2, 6)
            for r in range(length):
                y = int((start + r) * s * 0.085)
                shade = int(40 + 110 * (r + 1) / length)
                rd.text((x, y), rnd.choice("01$%+z"), font=f, fill=(0, shade, int(shade * 0.3), 120))
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=255)
        img.alpha_composite(Image.composite(rain, Image.new("RGBA", (s, s), (0, 0, 0, 0)), mask))
    d.rounded_rectangle([border // 2, border // 2, s - 1 - border // 2, s - 1 - border // 2], radius=radius,
                        outline=GREEN + (255,), width=border)
    # litera M z poświatą
    letter = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ld = ImageDraw.Draw(letter)
    f = _font(int(s * (0.70 if size <= 24 else 0.60)))
    box = ld.textbbox((0, 0), "M", font=f)
    w, h = box[2] - box[0], box[3] - box[1]
    top = int(s * (0.10 if size <= 24 else 0.14))
    ld.text(((s - w) / 2 - box[0], top - box[1]), "M", font=f, fill=GREEN + (255,))
    if size >= 32:
        glow = letter.filter(ImageFilter.GaussianBlur(s * 0.03))
        img.alpha_composite(glow)
    img.alpha_composite(letter)
    # pasek postępu (motyw aplikacji: ━━━━━──)
    bar_y = int(s * (0.80 if size > 24 else 0.82))
    bar_h = max(scale * 2, int(s * 0.07))
    x0, x1 = int(s * 0.16), int(s * 0.84)
    split = x0 + int((x1 - x0) * 0.68)
    d = ImageDraw.Draw(img)
    d.rectangle([x0, bar_y, x1, bar_y + bar_h], fill=DIM + (255,))
    d.rectangle([x0, bar_y, split, bar_y + bar_h], fill=GREEN + (255,))
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    images = [render(n) for n in sizes]
    out = HERE / "MatrixFinance.ico"
    images[-1].save(out, format="ICO", sizes=[(n, n) for n in sizes], append_images=images[:-1])
    images[-1].save(HERE / "MatrixFinance.png")
    print(f"zapisano {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
