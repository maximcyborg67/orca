"""Общие кусочки интерфейса: шрифт значков и кнопки."""
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QToolButton

# Значки Windows (есть в Windows 10 и 11)
G = dict(
    back="", forward="", up="", refresh="", home="",
    newfolder="", cut="", copy="", paste="", rename="",
    delete="", icons="", compact="", details="", hidden="",
    split="", preview="", filter="", more="", chev="",
    newtab="", undo="", search="", sidebar="",
)


def icon_font(px=16):
    f = QFont()
    f.setFamilies(["Segoe Fluent Icons", "Segoe MDL2 Assets"])
    f.setPixelSize(px)
    return f


def glyph_button(glyph, tip="", px=16, checkable=False):
    b = QToolButton()
    b.setText(glyph)
    b.setFont(icon_font(px))
    b.setToolTip(tip)
    b.setAutoRaise(True)
    b.setCheckable(checkable)
    return b
