"""Draws the doctor's-office decorations as images (our own content, committed in textures/).

Run with any Python that has Pillow: python3 make_textures.py
build_scene.py imports the PNGs; rerun this only to change how they look.
"""
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "textures")
FONT_DIRS = ["/System/Library/Fonts/Supplemental", "/System/Library/Fonts", "C:/Windows/Fonts"]


def font(names, size):
    for folder in FONT_DIRS:
        for name in names:
            path = os.path.join(folder, name)
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
    return ImageFont.load_default()


SERIF = ["Georgia.ttf", "Times New Roman.ttf", "georgia.ttf", "times.ttf"]
SANS = ["Arial.ttf", "Helvetica.ttc", "arial.ttf"]
SANS_BOLD = ["Arial Bold.ttf", "arialbd.ttf", "Arial.ttf"]


def centered(draw, y, text, f, fill, width):
    w = draw.textlength(text, font=f)
    draw.text(((width - w) / 2, y), text, font=f, fill=fill)


def eye_chart():
    w, h = 600, 1000
    img = Image.new("RGB", (w, h), (248, 247, 242))
    d = ImageDraw.Draw(img)
    rows = ["E", "F P", "T O Z", "L P E D", "P E C F D", "E D F C Z P", "F E L O P Z D", "D E F P O T E C"]
    y = 60
    for i, row in enumerate(rows):
        size = int(150 * (0.72 ** i)) + 10
        f = font(SANS_BOLD, size)
        centered(d, y, row, f, (20, 20, 20), w)
        y += size + 22
        d.text((30, y - size // 2 - 10), str(i + 1), font=font(SANS, 18), fill=(150, 30, 30))
    d.line((40, h - 70, w - 40, h - 70), fill=(200, 40, 40), width=3)
    return img


def poster():
    w, h = 700, 1000
    img = Image.new("RGB", (w, h), (236, 244, 247))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w, 150), fill=(30, 105, 135))
    centered(d, 40, "Healthy Heart", font(SANS_BOLD, 64), (255, 255, 255), w)
    # a simple heart
    cx, cy, s = w // 2, 360, 150
    d.ellipse((cx - s, cy - s // 1.4, cx, cy + s // 3), fill=(205, 60, 70))
    d.ellipse((cx, cy - s // 1.4, cx + s, cy + s // 3), fill=(205, 60, 70))
    d.polygon([(cx - s + 8, cy + 10), (cx + s - 8, cy + 10), (cx, cy + s + 60)], fill=(205, 60, 70))
    d.line([(cx - 120, cy + 20), (cx - 50, cy + 20), (cx - 25, cy - 40), (cx + 5, cy + 70), (cx + 30, cy + 20), (cx + 120, cy + 20)],
           fill=(255, 255, 255), width=8)
    tips = ["Move 30 minutes a day", "Eat more vegetables", "Know your blood pressure", "Do not smoke", "Sleep 7 to 8 hours"]
    y = 600
    for tip in tips:
        d.ellipse((90, y + 8, 114, y + 32), fill=(30, 105, 135))
        d.text((135, y), tip, font=font(SANS, 34), fill=(30, 50, 60))
        y += 70
    return img


def clock_face():
    s = 512
    img = Image.new("RGB", (s, s), (250, 250, 250))
    d = ImageDraw.Draw(img)
    c = s // 2
    d.ellipse((8, 8, s - 8, s - 8), outline=(40, 40, 40), width=14)
    for k in range(60):
        a = 2 * math.pi * k / 60
        r1 = c - 30 if k % 5 == 0 else c - 22
        d.line((c + r1 * math.sin(a), c - r1 * math.cos(a), c + (c - 14) * math.sin(a), c - (c - 14) * math.cos(a)),
               fill=(40, 40, 40), width=8 if k % 5 == 0 else 3)
    f = font(SANS, 44)
    for n in range(1, 13):
        a = 2 * math.pi * n / 12
        tx, ty = c + (c - 80) * math.sin(a), c - (c - 80) * math.cos(a)
        t = str(n)
        d.text((tx - d.textlength(t, font=f) / 2, ty - 26), t, font=f, fill=(30, 30, 30))
    for angle, length, width in ((310, 0.5, 14), (60, 0.72, 9)):  # ten past ten
        a = math.radians(angle)
        d.line((c, c, c + length * c * math.sin(a), c - length * c * math.cos(a)), fill=(25, 25, 25), width=width)
    d.ellipse((c - 14, c - 14, c + 14, c + 14), fill=(180, 40, 40))
    return img


def window_view():
    w, h = 1024, 1024
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):  # sky: pale blue to almost white near the horizon
        t = y / h
        d.line((0, y, w, y), fill=(int(170 + 70 * t), int(200 + 45 * t), int(235 + 15 * t)))
    rng = random.Random(4)
    for _ in range(9):  # distant buildings
        x = rng.randint(-50, w)
        bw, bh = rng.randint(120, 260), rng.randint(150, 420)
        tone = rng.randint(185, 215)
        d.rectangle((x, h - bh, x + bw, h), fill=(tone, tone + 5, tone + 12))
    for _ in range(40):  # trees in front
        x, r = rng.randint(0, w), rng.randint(60, 140)
        y = h - rng.randint(0, 160)
        g = rng.randint(90, 130)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(g - 40, g + 20, g - 50))
    return img.filter(ImageFilter.GaussianBlur(10))


def main():
    os.makedirs(OUT, exist_ok=True)
    images = {
        "T_EyeChart": eye_chart(),
        "T_Poster": poster(),
        "T_Clock": clock_face(),
        "T_WindowView": window_view(),
    }
    for name, image in images.items():
        image.save(os.path.join(OUT, name + ".png"), optimize=True)
        print("wrote", name)


if __name__ == "__main__":
    main()
