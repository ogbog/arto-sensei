"""Fake krita module for offscreen gyms.

Startup trap reproduced on purpose: until STATE['up'] is True, activeWindow()
returns a window that is not visible and a hollow View whose
flakeToCanvasTransform() hard-kills the process (os._exit), exactly like
Krita 5.3.4's C++ null deref. If any code path touches it early, the gym dies.
"""
import os
import tempfile
from PyQt5 import QtWidgets, QtGui

STATE = {"up": False}


class ManagedColor:
    @staticmethod
    def fromQColor(qc, canvas=None):
        return ManagedColor()


class _Res:
    def __init__(s, n): s._n = n
    def name(s): return s._n


class _Canvas:
    def zoomLevel(s): return 1.0
    def rotation(s): return 0.0
    def mirror(s): return False


class _View:
    def document(s): return object() if STATE["up"] else None
    def canvas(s): return _Canvas()
    def flakeToCanvasTransform(s):
        if not STATE["up"]:
            print("FATAL: hollow View.flakeToCanvasTransform() called during startup", flush=True)
            os._exit(139)
        return QtGui.QTransform()
    def currentBrushPreset(s): return _Res("b) Basic-5 Size Opacity")
    def brushSize(s): return 10.0


class _QWin:
    def __init__(s): s.w = QtWidgets.QMainWindow()
    def isVisible(s): return STATE["up"]
    def findChild(s, cls): return None
    def findChildren(s, cls): return []


class _Window:
    def __init__(s): s._q, s._v = _QWin(), _View()
    def qwindow(s): return s._q
    def activeView(s): return s._v


class _K:
    _i = None
    tmp = tempfile.mkdtemp()
    @classmethod
    def instance(c):
        if not c._i:
            c._i = c()
            c._i._win = _Window()
        return c._i
    def version(s): return "5.3.4.1 (fake)"
    def action(s, n): return None
    def activeWindow(s): return s._win
    def activeDocument(s): return None
    def documents(s): return []
    def getAppDataLocation(s): return s.tmp
    def resources(s, t): return {"b) Basic-5 Size Opacity": _Res("b) Basic-5 Size Opacity")}
    def addDockWidgetFactory(s, f): pass


Krita = _K


class DockWidget(QtWidgets.QDockWidget):
    pass


class DockWidgetFactoryBase:
    DockRight = 1


class DockWidgetFactory:
    def __init__(s, *a): pass
