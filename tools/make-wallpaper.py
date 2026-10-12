#!/usr/bin/env python3
"""Renders the default Shale wallpaper: layered, crisp curving strata on #1e1e1e.
With --light, renders the same strata in Breeze Light greys on #eff0f1 (for Shale Light).

Usage: make-wallpaper.py [--light] OUT.png [WIDTH HEIGHT]
"""
import math
import random
import sys

from PIL import Image, ImageDraw, ImageFilter

args = sys.argv[1:]
light = "--light" in args
if light:
    args.remove("--light")
out = args[0]
W, H = (int(args[1]), int(args[2])) if len(args) > 2 else (3840, 2160)
S = 2  # supersampling
w, h = W * S, H * S
rng = random.Random(7)

img = Image.new("RGB", (w, h), (239, 240, 241) if light else (30, 30, 30))
draw = ImageDraw.Draw(img)

# Bands from top to bottom: colour gets slightly lighter and bluer towards the middle.
bands = [
    ((34, 35, 37), 0.30), ((39, 41, 45), 0.40), ((45, 49, 55), 0.49),
    ((54, 60, 69), 0.56), ((66, 76, 89), 0.62), ((52, 59, 69), 0.68),
    ((43, 47, 53), 0.75), ((37, 39, 42), 0.83), ((32, 33, 34), 0.92),
]
if light:
    # Same strata, slightly darker and bluer towards the middle instead of lighter.
    bands = [
        ((233, 234, 236), 0.30), ((225, 228, 231), 0.40), ((214, 219, 225), 0.49),
        ((199, 207, 217), 0.56), ((181, 193, 208), 0.62), ((202, 209, 218), 0.68),
        ((217, 221, 227), 0.75), ((227, 229, 232), 0.83), ((234, 235, 237), 0.92),
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

# No blur: the 2x supersampling already gives smooth, crisp edges at 4K.
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
edge = (226, 228, 231) if light else (22, 22, 22)
img = Image.composite(Image.new("RGB", (W, H), edge), img, vignette)
noise = Image.effect_noise((W, H), 6).convert("RGB")
img = Image.blend(img, noise, 0.015)
img.save(out, optimize=True)
