#!/usr/bin/env python3
"""Renders the boot-splash wordmark (logo + "Shale Linux") with Qt.

Usage: QT_QPA_PLATFORM=offscreen make-boot-watermark.py LOGO.svg OUT.png
"""
import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

app = QGuiApplication(sys.argv)
W, H, S = 300, 64, 2
img = QImage(W * S, H * S, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
p.scale(S, S)
QSvgRenderer(sys.argv[1]).render(p, QRectF(40, 12, 40, 40))
font = QFont("Noto Sans")
font.setPixelSize(26)
font.setWeight(QFont.Light)
p.setFont(font)
p.setPen(QColor(220, 220, 220))
p.drawText(QRectF(92, 0, 210, H), Qt.AlignVCenter | Qt.AlignLeft, "Shale Linux")
p.end()
img.scaled(W, H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).save(sys.argv[2])
