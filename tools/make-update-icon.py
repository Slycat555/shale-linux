#!/usr/bin/env python3
"""Writes the Software Update icon: the round Shale logo with a white refresh ring.

Usage: make-update-icon.py LOGO.svg OUT.svg
Plain paths and strokes only, so Qt's SVG renderer draws it like everything else.
"""
import math
import sys

CX = CY = 64
RING = 27      # radius of the arrows
WIDTH = 9      # arrow stroke width
HEAD = 13      # arrowhead length


def point(angle, r=RING):
    a = math.radians(angle)
    return CX + r * math.cos(a), CY + r * math.sin(a)


def arrow(start, end):
    """A clockwise arc from start to end (degrees, SVG y-down) with an arrowhead."""
    x0, y0 = point(start)
    x1, y1 = point(end - 14)  # leave room for the head
    arc = f'<path d="M{x0:.2f},{y0:.2f} A{RING},{RING} 0 0 1 {x1:.2f},{y1:.2f}" ' \
          f'fill="none" stroke="#ffffff" stroke-width="{WIDTH}" stroke-linecap="round"/>'
    # Head: a triangle pointing along the clockwise tangent at `end`.
    tx, ty = point(end)
    a = math.radians(end)
    dx, dy = -math.sin(a), math.cos(a)          # clockwise tangent
    nx, ny = math.cos(a), math.sin(a)           # outward normal
    bx, by = tx - dx * HEAD, ty - dy * HEAD
    w = HEAD * 0.85
    head = (f'<path fill="#ffffff" stroke="#ffffff" stroke-width="2" stroke-linejoin="round" '
            f'd="M{tx + dx * 3:.2f},{ty + dy * 3:.2f} L{bx + nx * w:.2f},{by + ny * w:.2f} '
            f'L{bx - nx * w:.2f},{by - ny * w:.2f} Z"/>')
    return arc + "\n  " + head


with open(sys.argv[1], encoding="utf-8") as f:
    logo = f.read().strip()
body = logo[:logo.rindex("</svg>")].rstrip()
overlay = [
    f'  <circle cx="{CX}" cy="{CY}" r="43" fill="#1e2630" fill-opacity="0.55"/>',
    "  " + arrow(200, 330),
    "  " + arrow(20, 150),
]
with open(sys.argv[2], "w", encoding="utf-8") as f:
    f.write(body + "\n" + "\n".join(overlay) + "\n</svg>\n")
