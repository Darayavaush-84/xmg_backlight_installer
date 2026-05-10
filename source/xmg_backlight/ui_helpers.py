"""Small UI and validation helpers."""

from __future__ import annotations

from PySide6 import QtCore, QtGui

FLAG_ICON_CACHE = {}


def build_flag_icon(code):
    cached = FLAG_ICON_CACHE.get(code)
    if cached is not None:
        return cached

    width, height = 20, 14
    pixmap = QtGui.QPixmap(width, height)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
    rect = QtCore.QRect(0, 0, width, height)

    if code == "it":
        third = width // 3
        middle = width - 2 * third
        painter.fillRect(0, 0, third, height, QtGui.QColor("#009246"))
        painter.fillRect(third, 0, middle, height, QtGui.QColor("#ffffff"))
        painter.fillRect(third + middle, 0, third, height, QtGui.QColor("#ce2b37"))
    elif code == "fr":
        third = width // 3
        middle = width - 2 * third
        painter.fillRect(0, 0, third, height, QtGui.QColor("#0055a4"))
        painter.fillRect(third, 0, middle, height, QtGui.QColor("#ffffff"))
        painter.fillRect(third + middle, 0, third, height, QtGui.QColor("#ef4135"))
    elif code == "de":
        third = height // 3
        middle = height - 2 * third
        painter.fillRect(0, 0, width, third, QtGui.QColor("#000000"))
        painter.fillRect(0, third, width, middle, QtGui.QColor("#dd0000"))
        painter.fillRect(0, third + middle, width, third, QtGui.QColor("#ffce00"))
    elif code == "es":
        band = height // 4
        middle = height - 2 * band
        painter.fillRect(0, 0, width, band, QtGui.QColor("#aa151b"))
        painter.fillRect(0, band, width, middle, QtGui.QColor("#f1bf00"))
        painter.fillRect(0, band + middle, width, band, QtGui.QColor("#aa151b"))
    elif code == "en":
        painter.fillRect(rect, QtGui.QColor("#012169"))
        cross = max(4, height // 3)
        inner = max(2, cross // 2)
        cx = width // 2
        cy = height // 2
        painter.fillRect(cx - cross // 2, 0, cross, height, QtGui.QColor("#ffffff"))
        painter.fillRect(0, cy - cross // 2, width, cross, QtGui.QColor("#ffffff"))
        painter.fillRect(cx - inner // 2, 0, inner, height, QtGui.QColor("#c8102e"))
        painter.fillRect(0, cy - inner // 2, width, inner, QtGui.QColor("#c8102e"))
    else:
        painter.fillRect(rect, QtGui.QColor("#64748b"))

    painter.setPen(QtGui.QPen(QtGui.QColor(148, 163, 184, 160)))
    painter.drawRect(0, 0, width - 1, height - 1)
    painter.end()

    icon = QtGui.QIcon(pixmap)
    FLAG_ICON_CACHE[code] = icon
    return icon


def normalize_language_code(value):
    if not value:
        return ""
    return str(value).split("-")[0].split("_")[0].lower()


def clamp_int(value, minimum, maximum, fallback):
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, ivalue))


def sanitize_choice(value, options, fallback):
    return value if value in options else fallback


def set_combo_by_data(combo, value):
    idx = combo.findData(value)
    if idx >= 0:
        combo.setCurrentIndex(idx)
        return True
    return False
