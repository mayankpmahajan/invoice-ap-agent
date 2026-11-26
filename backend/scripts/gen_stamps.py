"""Render rubber-stamp impressions as raster PNGs (transparent, real ink texture) for the UI.
Usage: uv run python scripts/gen_stamps.py"""
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parents[2] / "frontend" / "public" / "stamps"
FONT = "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf"
STAMPS = {  # key: (word, sub, rgb)
    "approved": ("APPROVED", "FOR PAYMENT", (23, 104, 63)),
    "needs_review": ("HOLD", "FOR REVIEW", (176, 74, 6)),
    "rejected": ("VOID", "DO NOT PAY", (179, 38, 30)),
    "failed": ("ERROR", "RUN FAILED", (79, 93, 89)),
    "running": ("IN PROCESS", "", (49, 44, 134)),
}


def noise(size, scale, seed):
    rnd = random.Random(seed)
    w, h = size
    small = Image.new("L", (max(1, w // scale), max(1, h // scale)))
    small.putdata([rnd.randrange(256) for _ in range(small.width * small.height)])
    return small.resize(size, Image.BICUBIC)


def render(word, sub, color, seed, H=220):
    S = 3  # supersample
    big = ImageFont.truetype(FONT, int(H * 0.52 * S))
    small = ImageFont.truetype(FONT, int(H * 0.15 * S))
    wb = big.getbbox(word)
    tw = wb[2] - wb[0]
    W = int(tw / S + H * 0.55)
    w, h = W * S, H * S
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    pad, lw = int(h * .07), int(h * .045)
    d.rectangle([pad, pad, w - pad, h - pad], outline=255, width=lw)
    d.rectangle([pad + lw * 2, pad + lw * 2, w - pad - lw * 2, h - pad - lw * 2], outline=255, width=max(2, lw // 3))
    ty = h * (0.18 if sub else 0.24)
    d.text(((w - tw) / 2 - wb[0], ty - wb[1]), word, font=big, fill=255)
    if sub:
        sb = small.getbbox(sub)
        d.text(((w - (sb[2] - sb[0])) / 2 - sb[0], h * .70 - sb[1]), sub, font=small, fill=255)
    # Ink: uneven pressure, speckled voids, soft rough edges.
    pressure = noise((w, h), 90 * S // 3, seed).point(lambda v: 175 + v * 80 // 255)
    grain = noise((w, h), 3, seed + 1).point(lambda v: 0 if v < 22 else 255)
    voids = noise((w, h), 26, seed + 2).point(lambda v: 0 if v < 28 else 255)
    m = m.filter(ImageFilter.GaussianBlur(S * .6))
    m = ImageChops.multiply(m, pressure)
    m = ImageChops.multiply(m, grain)
    m = ImageChops.multiply(m, voids)
    m = m.resize((W, H), Image.LANCZOS)
    img = Image.new("RGBA", (W, H), color + (0,))
    img.putalpha(m)
    return img


for i, (key, (word, sub, rgb)) in enumerate(STAMPS.items()):
    render(word, sub, rgb, seed=11 + i).save(OUT / f"{key}.png", optimize=True)
    render(word, "", rgb, seed=31 + i, H=80).save(OUT / f"{key}-sm.png", optimize=True)
print(sorted(p.name for p in OUT.glob("*.png")))
