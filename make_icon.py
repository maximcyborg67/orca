"""Рисует значок программы (icon.png и icon.ico). Запуск один раз: python make_icon.py"""
import os
import sys

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (QGuiApplication, QImage, QPainter, QColor, QLinearGradient, QPainterPath, QBrush, QPen)

HERE = os.path.dirname(os.path.abspath(__file__))
app = QGuiApplication(sys.argv)
S = 512
img = QImage(S, S, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)

bg = QLinearGradient(0, 0, S, S)
bg.setColorAt(0, QColor("#2b3a55"))
bg.setColorAt(1, QColor("#161b27"))
p.setBrush(QBrush(bg))
p.setPen(Qt.NoPen)
p.drawRoundedRect(QRectF(16, 16, S - 32, S - 32), 110, 110)

# задняя часть папки
back = QPainterPath()
back.moveTo(90, 170)
back.lineTo(90, 145)
back.quadTo(90, 125, 112, 125)
back.lineTo(205, 125)
back.quadTo(222, 125, 232, 140)
back.lineTo(246, 160)
back.lineTo(400, 160)
back.quadTo(422, 160, 422, 182)
back.lineTo(422, 360)
back.lineTo(90, 360)
back.closeSubpath()
g1 = QLinearGradient(0, 120, 0, 360)
g1.setColorAt(0, QColor("#e0a92e"))
g1.setColorAt(1, QColor("#c98d14"))
p.setBrush(QBrush(g1))
p.drawPath(back)

# передняя часть
front = QPainterPath()
front.addRoundedRect(QRectF(70, 205, 372, 190), 28, 28)
g2 = QLinearGradient(0, 205, 0, 395)
g2.setColorAt(0, QColor("#ffd96b"))
g2.setColorAt(1, QColor("#f5b83a"))
p.setBrush(QBrush(g2))
p.drawPath(front)

# лупа поиска-акцент справа снизу
p.setBrush(Qt.NoBrush)
pen = QPen(QColor("#5b9dff"), 26, Qt.SolidLine, Qt.RoundCap)
p.setPen(pen)
p.drawEllipse(QPointF(370, 330), 52, 52)
p.drawLine(QPointF(408, 368), QPointF(450, 410))
p.end()

png = os.path.join(HERE, "icon.png")
img.save(png)
from PIL import Image
im = Image.open(png)
im.save(os.path.join(HERE, "icon.ico"), sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("ok")
