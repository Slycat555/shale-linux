#!/usr/bin/env python3
"""Writes the round Shale logo (src/shale/logo.svg): wavy strata inside a circle.

Usage: make-logo.py OUT.svg
The stripes are intersected with the circle here and written as plain paths, because
Qt's SVG renderer (Plasma panel, About page, installer) ignores clipPath and would
draw a square.
"""
import math
import sys

CX = CY = 64
R = 58
BG = "#2b3440"
# (fill, top curve, bottom curve); each curve is a cubic Bezier from x=6 to x=122.
STRIPES = [
    ("#c3cfdc", [(6, 22), (38, 14), (76, 28), (122, 18)], [(6, 40), (40, 30), (74, 46), (122, 34)]),
    ("#8a9bb0", [(6, 46), (40, 36), (70, 52), (122, 40)], [(6, 64), (42, 54), (76, 70), (122, 58)]),
    ("#5f7187", [(6, 70), (46, 60), (78, 76), (122, 64)], [(6, 88), (44, 76), (80, 92), (122, 80)]),
    ("#43536a", [(6, 94), (42, 84), (80, 100), (122, 88)], [(6, 112), (44, 100), (82, 116), (122, 104)]),
]
STEP = 0.5


def bezier(p, t):
    u = 1 - t
    return tuple(u ** 3 * p[0][i] + 3 * u * u * t * p[1][i] + 3 * u * t * t * p[2][i]
                 + t ** 3 * p[3][i] for i in (0, 1))


def curve_y(p, x):
    """y of a Bezier whose x grows monotonically, at the given x."""
    lo, hi = 0.0, 1.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if bezier(p, mid)[0] < x:
            lo = mid
        else:
            hi = mid
    return bezier(p, lo)[1]


def bounds(top, bottom, x):
    """Top and bottom edge of a stripe within the circle at x (top > bottom if empty)."""
    h = math.sqrt(max(R * R - (x - CX) ** 2, 0))
    return max(curve_y(top, x), CY - h), min(curve_y(bottom, x), CY + h)


def edge(top, bottom, inside, outside):
    """x between inside and outside where the stripe's height drops to zero."""
    for _ in range(50):
        mid = (inside + outside) / 2
        t, b = bounds(top, bottom, mid)
        inside, outside = (mid, outside) if t < b else (inside, mid)
    return inside


def stripe_path(top, bottom):
    xs = [CX - R + i * STEP for i in range(int(2 * R / STEP) + 1)]
    inside = [x for x in xs if (lambda tb: tb[0] < tb[1])(bounds(top, bottom, x))]
    x0 = edge(top, bottom, inside[0], inside[0] - STEP)
    x1 = edge(top, bottom, inside[-1], inside[-1] + STEP)
    xs = [x0] + inside + [x1]
    upper = [(x, bounds(top, bottom, x)[0]) for x in xs]
    lower = [(x, bounds(top, bottom, x)[1]) for x in reversed(xs)]
    pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in upper + lower)
    return f"M{pts}Z"


out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">',
       f'  <circle cx="{CX}" cy="{CY}" r="{R}" fill="{BG}"/>']
for fill, top, bottom in STRIPES:
    out.append(f'  <path fill="{fill}" d="{stripe_path(top, bottom)}"/>')
out.append("</svg>")
with open(sys.argv[1], "w", encoding="utf-8") as f:
    f.write("\n".join(out) + "\n")
