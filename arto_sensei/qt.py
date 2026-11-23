# SPDX-License-Identifier: MIT
"""One import point for Qt. Krita 5.3 ships PyQt5, Krita 6 ships PyQt6.

Every module does `from .qt import QtCore, QtGui, QtWidgets, E, ...` and never
imports PyQt directly, so the Krita 6 port is this file and nothing else.
"""
from krita import Krita

KRITA_VERSION = Krita.instance().version()
QT6 = KRITA_VERSION.split(".")[0].isdigit() and int(KRITA_VERSION.split(".")[0]) >= 6

if QT6:
    from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: F401
else:
    from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: F401

Qt = QtCore.Qt
QEvent = QtCore.QEvent
Signal = QtCore.pyqtSignal


def E(cls, scope, name):
    """Enum lookup that works for scoped (PyQt6) and flat (PyQt5) enums."""
    s = getattr(cls, scope, None)
    if s is not None and hasattr(s, name):
        return getattr(s, name)
    return getattr(cls, name)


ET = {n: E(QEvent, "Type", n) for n in (
    "TabletPress", "TabletMove", "TabletRelease",
    "MouseButtonPress", "MouseMove", "MouseButtonRelease",
    "KeyPress", "KeyRelease", "FocusOut")}

LEFT = E(Qt, "MouseButton", "LeftButton")
MIDDLE = E(Qt, "MouseButton", "MiddleButton")
KEY_SPACE = E(Qt, "Key", "Key_Space")
RICH = E(Qt, "TextFormat", "RichText")
ANTIALIAS = E(QtGui.QPainter, "RenderHint", "Antialiasing")
ARGB32 = E(QtGui.QImage, "Format", "Format_ARGB32")  # BGRA in memory = Krita RGBA/U8 pixel order
POINTING = E(Qt, "CursorShape", "PointingHandCursor")


def global_xy(ev):
    for name in ("globalPosition", "globalPosF", "globalPos"):
        f = getattr(ev, name, None)
        if f:
            p = f()
            return float(p.x()), float(p.y())
    return 0.0, 0.0


def ev_time(ev):
    try:
        return ev.timestamp() / 1000.0
    except Exception:
        return 0.0


def image_bytes(img):
    ptr = img.constBits()
    n = img.sizeInBytes() if hasattr(img, "sizeInBytes") else img.byteCount()
    ptr.setsize(n)
    return QtCore.QByteArray(bytes(ptr))
