#!/usr/bin/env python3
"""Renders the round Shale logo as fastfetch text art: "▀" half blocks with 24-bit
foreground/background colours, so every character shows two pixels.

Usage: make-fastfetch-logo.py LOGO.svg OUT.txt   (needs rsvg-convert)
The result is a raw ANSI logo, see "type": "file-raw" in system/etc/xdg/fastfetch/config.jsonc.
"""
import subprocess
import sys

from PySide6.QtGui import QImage

COLS, ROWS = 32, 16  # characters; the logo is COLS x (2 * ROWS) pixels
S = 8                # supersampling per pixel

png = subprocess.run(["rsvg-convert", "-w", str(COLS * S), "-h", str(ROWS * 2 * S),
                      sys.argv[1]], check=True, capture_output=True).stdout
img = QImage.fromData(png)


def pixel(x, y):
    """Average colour of one logo pixel, or None if it is mostly transparent."""
    r = g = b = a = 0
    for dy in range(S):
        for dx in range(S):
            c = img.pixelColor(x * S + dx, y * S + dy)
            r += c.red() * c.alpha()
            g += c.green() * c.alpha()
            b += c.blue() * c.alpha()
            a += c.alpha()
    if a < 255 * S * S // 2:
        return None
    return r // a, g // a, b // a


def fg(c):
    return f"\x1b[38;2;{c[0]};{c[1]};{c[2]}m"


def bg(c):
    return f"\x1b[48;2;{c[0]};{c[1]};{c[2]}m"


lines = []
for row in range(ROWS):
    line = ""
    for col in range(COLS):
        top, bottom = pixel(col, row * 2), pixel(col, row * 2 + 1)
        if top and bottom:
            line += fg(top) + bg(bottom) + "▀"
        elif top:
            line += "\x1b[49m" + fg(top) + "▀"
        elif bottom:
            line += "\x1b[49m" + fg(bottom) + "▄"
        else:
            line += "\x1b[49m "
    lines.append(line + "\x1b[0m")
with open(sys.argv[2], "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
