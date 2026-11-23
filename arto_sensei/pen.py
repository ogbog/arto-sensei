# SPDX-License-Identifier: MIT
"""PenTap: listens to the real Krita canvas and records what the hand did.

Krita's Python API has no pen-pressure hook, so we install a Qt event filter
on the canvas widget and read QTabletEvents ourselves. We never consume the
events (always return False), so painting is untouched.
"""
import time

from krita import Krita

from . import devlog
from .metrics import stroke_metrics
from .qt import (QtCore, QtWidgets, Signal, ET, LEFT, MIDDLE, KEY_SPACE, E, Qt,
                 global_xy, ev_time)

RIGHT = E(Qt, "MouseButton", "RightButton")

_WATCHED = frozenset(ET[k] for k in (
    "TabletPress", "TabletMove", "TabletRelease", "MouseButtonPress", "MouseMove",
    "MouseButtonRelease", "KeyPress", "KeyRelease", "FocusOut"))

MAX_SAMPLES = 20000
MAX_HISTORY = 60


def find_canvas_widget():
    """The widget Krita paints into for the active view (largest *Canvas* widget)."""
    win = Krita.instance().activeWindow()
    if win is None:
        return None
    qwin = win.qwindow()
    mdi = qwin.findChild(QtWidgets.QMdiArea)
    root = None
    if mdi is not None:
        root = mdi.currentSubWindow() or mdi.activeSubWindow()
    root = root or qwin
    best, best_area = None, 0
    for w in root.findChildren(QtWidgets.QWidget):
        cn = w.metaObject().className()
        if "Canvas" not in cn or "Controller" in cn or not w.isVisible():
            continue
        area = w.width() * w.height()
        if cn in ("KisOpenGLCanvas2", "KisQPainterCanvas"):
            area *= 10  # known names win ties
        if area > best_area:
            best, best_area = w, area
    return best


def screen_info(widget):
    """(px_per_mm, screen_diag_px) for the screen the canvas lives on."""
    try:
        scr = widget.screen() if hasattr(widget, "screen") else None
        scr = scr or QtWidgets.QApplication.primaryScreen()
        dpi = scr.physicalDotsPerInch() or 96.0
        g = scr.geometry()
        return dpi / 25.4, (g.width() ** 2 + g.height() ** 2) ** 0.5
    except Exception:
        return 96.0 / 25.4, 2203.0


class Stroke(object):
    __slots__ = ("samples", "source", "nav", "metrics", "t_end")

    def __init__(self, source, nav):
        self.samples = []
        self.source = source
        self.nav = nav
        self.metrics = None
        self.t_end = 0.0


class PenTap(QtCore.QObject):
    stroke_done = Signal(object)   # Stroke
    nav_gesture = Signal(str)      # "pan"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.widget = None
        self.live = None
        self.history = []
        self.px_per_mm, self.diag = 96.0 / 25.4, 2203.0
        self._space = False
        self._mid_drag = False
        self._last_tablet = 0.0
        self._t_fallback0 = None
        self.tablet_events = 0
        self.mouse_strokes = 0
        self._cost_s, self._calls, self._cost_t0 = 0.0, 0, time.time()
        self._facted = False

    # -------------------------------------------------- attach / detach
    # TRAP (seen live 2026-11-22): a filter installed on the canvas widget loses
    # the pen whenever Krita's KisInputManager re-installs its own filter on top
    # (Qt calls the newest filter first, and Krita consumes tablet events). We
    # then only saw the synthesized mouse events. An application-level filter
    # runs before every object filter, so Krita can never get in front of it.
    def install(self):
        app = QtWidgets.QApplication.instance()
        if app is not None and not getattr(self, "_installed", False):
            app.installEventFilter(self)
            self._installed = True
            devlog.fact("pen_filter", "application-level")

    def refresh(self):
        self.install()
        w = find_canvas_widget()
        if w is self.widget:
            return
        self.widget = w
        if w is not None:
            self.px_per_mm, self.diag = screen_info(w)
            devlog.fact("canvas_widget_class", w.metaObject().className())
            devlog.fact("screen_px_per_mm", round(self.px_per_mm, 3))
            devlog.fact("screen_diag_px", round(self.diag, 1))

    def detach(self):
        app = QtWidgets.QApplication.instance()
        if app is not None and getattr(self, "_installed", False):
            try:
                app.removeEventFilter(self)
            except Exception:
                pass
            self._installed = False
        self.widget = None

    # -------------------------------------------------- the filter
    def _t(self, ev):
        t = ev_time(ev)
        if t <= 0:
            t = time.perf_counter()
        return t

    def _add(self, ev, p):
        if self.live is None or len(self.live.samples) >= MAX_SAMPLES:
            return
        x, y = global_xy(ev)
        t = self._t(ev)
        smp = self.live.samples
        if smp and t < smp[-1][0]:
            t = smp[-1][0]
        smp.append((t, x, y, p))

    def _begin(self, ev, source, p):
        self.live = Stroke(source, nav=self._space)
        self._add(ev, p)

    def _end(self, ev, p):
        st = self.live
        self.live = None
        if st is None:
            return
        self._add_to(st, ev, p)
        st.t_end = time.time()
        if st.nav:
            self.nav_gesture.emit("pan")
            return
        st.metrics = stroke_metrics(st.samples, self.px_per_mm, self.diag)
        if st.metrics is None:
            devlog.log("stroke dropped (too tiny):", st.source, "samples", len(st.samples))
            return
        m = st.metrics
        prev = self.history[-1] if self.history else None
        gap = ""
        if prev is not None and prev.samples:
            gap_s = st.samples[0][0] - prev.samples[-1][0]
            gap_mm = ((st.samples[0][1] - prev.samples[-1][1]) ** 2 +
                      (st.samples[0][2] - prev.samples[-1][2]) ** 2) ** 0.5 / self.px_per_mm
            gap = " | gap %.2fs %.0fmm" % (gap_s, gap_mm)
        devlog.log("stroke %s n=%d len=%.0fmm dur=%.2fs speed=%.0fmm/s p=%.2f..%.2f mean=%.2f%s" % (
            st.source, m["n"], m["length_mm"], m["duration_s"], m["speed_mm_s"],
            m["p_min"], m["p_max"], m["p_mean"], gap))
        self.history.append(st)
        del self.history[:-MAX_HISTORY]
        if st.source == "tablet" and not self._facted:
            self._facted = True
            devlog.fact("first_tablet_stroke", {
                "samples": st.metrics["n"], "p_min": round(st.metrics["p_min"], 3),
                "p_max": round(st.metrics["p_max"], 3),
                "speed_mm_s": round(st.metrics["speed_mm_s"], 1),
                "duration_s": round(st.metrics["duration_s"], 3)})
        self.stroke_done.emit(st)

    def _add_to(self, st, ev, p):
        keep, self.live = self.live, st
        self._add(ev, p)
        self.live = keep

    def eventFilter(self, obj, ev):
        # App-wide filter: this runs for EVERY event in Krita. Bail fast.
        try:
            et = ev.type()
            if et not in _WATCHED:
                return False
            if self.widget is None or obj is not self.widget:
                return False
            t0 = time.perf_counter()
            self._handle(et, ev)
            self._cost_s += time.perf_counter() - t0
            self._calls += 1
            if time.time() - self._cost_t0 > 30 and self._calls:
                devlog.log("pen filter: %d canvas events in %.0fs, %.1f ms total handling" % (
                    self._calls, time.time() - self._cost_t0, 1000 * self._cost_s))
                self._cost_s, self._calls, self._cost_t0 = 0.0, 0, time.time()
        except Exception:
            devlog.log_exc("PenTap.eventFilter")
        return False

    def _handle(self, et, ev):
        if True:
            if et in (ET["TabletPress"], ET["TabletMove"], ET["TabletRelease"]):
                self.tablet_events += 1
                self._last_tablet = time.time()
                p = float(ev.pressure())
                if et == ET["TabletPress"]:
                    if ev.button() == LEFT:
                        self._begin(ev, "tablet", p)
                    elif ev.button() == RIGHT:
                        self.nav_gesture.emit("popup")
                elif et == ET["TabletMove"]:
                    if self.live is not None:
                        self._add(ev, p)
                elif self.live is not None:
                    self._end(ev, p)
            elif et in (ET["MouseButtonPress"], ET["MouseMove"], ET["MouseButtonRelease"]):
                if time.time() - self._last_tablet < 0.5:
                    return  # synthesized from the pen, ignore
                if et == ET["MouseButtonPress"]:
                    if ev.button() == RIGHT:
                        self.nav_gesture.emit("popup")
                    elif ev.button() == MIDDLE:
                        self._mid_drag = True
                    elif ev.button() == LEFT:
                        self._begin(ev, "mouse", 1.0)
                elif et == ET["MouseMove"]:
                    if self.live is not None:
                        self._add(ev, 1.0)
                else:
                    if self._mid_drag:
                        self._mid_drag = False
                        self.nav_gesture.emit("pan")
                    if self.live is not None and self.live.source == "mouse":
                        self.mouse_strokes += 1
                        self._end(ev, 1.0)
            elif et == ET["KeyPress"]:
                if ev.key() == KEY_SPACE and not ev.isAutoRepeat():
                    self._space = True
            elif et == ET["KeyRelease"]:
                if ev.key() == KEY_SPACE and not ev.isAutoRepeat():
                    self._space = False
            elif et == ET["FocusOut"]:
                self._space = False

    # -------------------------------------------------- queries
    def strokes_since(self, t):
        return [s for s in self.history if s.t_end >= t]

    def last(self):
        return self.history[-1] if self.history else None


class ActionLog(QtCore.QObject):
    """Remembers when named Krita actions fire (menu, button or shortcut)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hits = []
        self._watched = set()

    def watch(self, names):
        app = Krita.instance()
        if not hasattr(self, "_found"):
            self._found = {}
        for n in names:
            if n in self._watched or n in self._found:
                continue
            a = app.action(n)
            self._found[n] = "MISSING" if a is None else (a.shortcut().toString() or "(none)")
            if a is None:
                continue
            self._watched.add(n)
            a.triggered.connect(lambda *_a, n=n: self.hits.append((n, time.time())))
        devlog.fact("actions", self._found)

    def fired(self, name, since):
        return any(n == name and t >= since for n, t in self.hits)


def shortcut_text(name, fallback=""):
    """The student's real shortcut. If the action exists but has none, say so
    honestly and name the menu item; the JSON fallback is only for missing actions."""
    a = Krita.instance().action(name)
    if a is None:
        return fallback or name
    txt = a.shortcut().toString()
    if txt:
        return txt
    if fallback:  # e.g. a Canvas Input key (5 = reset rotation) that no QAction reports
        return fallback
    label = a.text().replace("&", "") or name
    return ("%s</b> (no shortcut on your Krita yet: use the menu, or give it one in "
            "Settings > Configure Krita > Keyboard Shortcuts)<b>" % label)
