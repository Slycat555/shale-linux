#!/usr/bin/env python3
"""Writes Shale's app icons, both made from the strata of the Shale logo.

Usage: make-app-icons.py LOGO.svg OUTDIR
  shale-update.svg     Software Update: a solid upward arrow over faint strata
  shale-snapshots.svg  Shale Snapshots: the logo with earlier copies fading behind it
  shale-status-*.svg   Shale Snapshots' status badges (ok, warn, error): the snapshots
                       icon with a coloured badge, used in the app's schedule page
Shapes are combined with Qt path operations and written as plain filled paths, so
Qt's SVG renderer (which ignores clipPath) draws them like everything else.
"""
import os
import re
import sys

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainterPath, QPolygonF

BG = "#2b3440"
SYMBOL = "#c3cfdc"  # the logo's lightest stripe
CX = CY = 64
R = 58


def read_logo(path):
    """The logo's stripes as (fill, QPainterPath)."""
    with open(path, encoding="utf-8") as f:
        svg = f.read()
    stripes = []
    for fill, d in re.findall(r'<path fill="(#[0-9a-f]+)" d="M([^"Z]+)Z"', svg):
        pts = [QPointF(*map(float, p.split(","))) for p in d.split()]
        path = QPainterPath()
        path.addPolygon(QPolygonF(pts))
        path.closeSubpath()
        stripes.append((fill, path))
    return stripes


def svg_path(path, fill, extra=""):
    parts = []
    for poly in path.toSubpathPolygons():
        pts = " ".join(f"{p.x():.2f},{p.y():.2f}" for p in poly)
        if pts:
            parts.append(f"M{pts}Z")
    return f'<path fill="{fill}"{extra} d="{"".join(parts)}"/>' if parts else ""


def circle(cx, cy, r):
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), r, r)
    return path


def update_icon(stripes):
    # An upward arrow: head 72 wide, shaft 30 wide.
    arrow = QPainterPath()
    arrow.addPolygon(QPolygonF([QPointF(*p) for p in [
        (64, 14), (101, 54), (79, 54), (79, 112), (49, 112), (49, 54), (27, 54), (64, 14)]]))
    arrow.closeSubpath()
    out = [f'<circle cx="{CX}" cy="{CY}" r="{R}" fill="{BG}"/>']
    # Faint strata behind a solid arrow in the logo's lightest colour.
    out += [svg_path(p, fill, ' fill-opacity="0.22"') for fill, p in stripes]
    out.append(svg_path(arrow.intersected(circle(CX, CY, R)), SYMBOL))
    return out


def snapshots_icon(stripes):
    # Three copies of the logo stepping back diagonally: the front one is now, the
    # fainter ones behind it are earlier snapshots.
    s = 0.66
    out = []
    for (cx, cy), opacity in (((84, 44), 0.35), ((64, 64), 0.6), ((44, 84), 1.0)):
        ox, oy = cx - CX * s, cy - CY * s
        op = "" if opacity == 1 else f' fill-opacity="{opacity}"'
        out.append(f'<g transform="translate({ox:.2f} {oy:.2f}) scale({s})">')
        out.append(f'<circle cx="{CX}" cy="{CY}" r="{R + 4}" fill="#1b222b"/>')
        out.append(f'<circle cx="{CX}" cy="{CY}" r="{R}" fill="{BG}"{op}/>')
        out += [svg_path(p, fill, op) for fill, p in stripes]
        out.append("</g>")
    return out


def status_icon(stripes, colour, glyph):
    # The snapshots icon with a round badge in the bottom-right corner.
    out = snapshots_icon(stripes)
    out.append('<circle cx="99" cy="99" r="27" fill="#1b222b"/>')
    out.append(f'<circle cx="99" cy="99" r="22" fill="{colour}"/>')
    out.append(f'<path d="{glyph}" fill="none" stroke="#ffffff" stroke-width="6" '
               'stroke-linecap="round" stroke-linejoin="round"/>')
    return out


STATUS = {
    "shale-status-ok.svg": ("#3a9d68", "M89 99.5 L96 106.5 L109.5 92"),       # check
    "shale-status-warn.svg": ("#d9952b", "M99 88 V101 M99 110 V110.2"),       # !
    "shale-status-error.svg": ("#d14b4b", "M91 91 L107 107 M107 91 L91 107"),  # x
}

stripes = read_logo(sys.argv[1])
icons = [("shale-update.svg", update_icon(stripes)),
         ("shale-snapshots.svg", snapshots_icon(stripes))]
icons += [(name, status_icon(stripes, colour, glyph)) for name, (colour, glyph) in STATUS.items()]
for name, parts in icons:
    with open(os.path.join(sys.argv[2], name), "w", encoding="utf-8") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">\n  '
                + "\n  ".join(p for p in parts if p) + "\n</svg>\n")
