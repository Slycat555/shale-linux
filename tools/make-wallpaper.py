#!/usr/bin/env python3
"""Renders the default Shale wallpaper: layered, softly curving strata on #1e1e1e.

Usage: make-wallpaper.py OUT.png [WIDTH HEIGHT]
"""
import math
import random
import sys

from PIL import Image, ImageDraw, ImageFilter

out = sys.argv[1]
W, H = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (3840, 2160)
S = 2  # supersampling
w, h = W * S, H * S
rng = random.Random(7)

img = Image.new("RGB", (w, h), (30, 30, 30))
draw = ImageDraw.Draw(img)

# Bands from top to bottom: colour gets slightly lighter and bluer towards the middle.
bands = [
    ((34, 35, 37), 0.30), ((39, 41, 45), 0.40), ((45, 49, 55), 0.49),
    ((54, 60, 69), 0.56), ((66, 76, 89), 0.62), ((52, 59, 69), 0.68),
    ((43, 47, 53), 0.75), ((37, 39, 42), 0.83), ((32, 33, 34), 0.92),
]


def curve(base, seed):
    r = random.Random(seed)
    waves = [(r.uniform(0.6, 1.6), r.uniform(0, math.tau), r.uniform(0.010, 0.030))
             for _ in range(3)]
    tilt = r.uniform(-0.06, 0.02)
    pts = []
    for i in range(0, w + 1, 8):
        x = i / w
        y = base + tilt * (x - 0.5)
        for freq, phase, amp in waves:
            y += amp * math.sin(freq * math.tau * x + phase)
        pts.append((i, y * h))
    return pts


for idx, (color, base) in enumerate(bands):
    top = curve(base - 0.03, idx)
    draw.polygon(top + [(w, h), (0, h)], fill=color)

img = img.filter(ImageFilter.GaussianBlur(3 * S))
img = img.resize((W, H), Image.LANCZOS)

# Subtle vignette and grain to avoid banding.
vignette = Image.new("L", (W, H))
vd = vignette.load()
for y in range(0, H, 4):
    for x in range(0, W, 4):
        dx, dy = (x / W - 0.5) * 1.2, (y / H - 0.45)
        v = int(min(255, 255 * max(0.0, (dx * dx + dy * dy) - 0.05) * 1.6))
        for yy in range(y, min(y + 4, H)):
            for xx in range(x, min(x + 4, W)):
                vd[xx, yy] = v
vignette = vignette.filter(ImageFilter.GaussianBlur(40))
img = Image.composite(Image.new("RGB", (W, H), (22, 22, 22)), img, vignette)
noise = Image.effect_noise((W, H), 6).convert("RGB")
img = Image.blend(img, noise, 0.015)
img.save(out, optimize=True)
