# SPDX-License-Identifier: MIT
"""Seismograph (live pressure + speed trace) and the lesson Card."""
import re

from . import devlog
from .metrics import series
from .pen import shortcut_text
from .qt import QtCore, QtGui, QtWidgets, Signal, E, ANTIALIAS, RICH, POINTING

INK = "#f2e8d5"      # warm paper
EMBER = "#ff7a45"    # pressure
TEAL = "#4fd1c5"     # speed
GOLD = "#ffd166"     # praise


def expand_tokens(text):
    """{key:action_name|fallback} -> the student's REAL shortcut, bolded."""
    def sub(m):
        name, _, fb = m.group(1).partition("|")
        return "<b>%s</b>" % shortcut_text(name, fb)
    text = re.sub(r"\{key:([A-Za-z0-9_/ ]+(?:\|[^}]*)?)\}", sub, text)
    return text.replace("\n", "<br>")


class Seismograph(QtWidgets.QWidget):
    """Ember = pressure (0..100%), teal = speed (auto-scaled). Time runs left to right."""

    def __init__(self, tap, progress, height=96, parent=None):
        super().__init__(parent)
        self.tap, self.progress = tap, progress
        self.setMinimumHeight(height)
        self._seen = None
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)  # 20 fps is plenty; the pen matters more than the graph

    def _stroke(self):
        return self.tap.live or self.tap.last()

    @devlog.safe
    def _tick(self):
        st = self._stroke()
        key = (id(st), len(st.samples) if st else 0)
        if key != self._seen and self.isVisible():
            self._seen = key
            self.update()

    @devlog.safe
    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        try:
            self._paint(p)
        finally:
            p.end()

    def _paint(self, p):
        p.setRenderHint(ANTIALIAS)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(QtGui.QPen(QtGui.QColor("#3a3330"), 1))
        p.setBrush(QtGui.QColor("#1d1917"))
        p.drawRoundedRect(r, 8, 8)
        inner = r.adjusted(8, 8, -8, -18)
        grid = QtGui.QPen(QtGui.QColor(255, 255, 255, 22), 1)
        p.setPen(grid)
        for f in (0.25, 0.5, 0.75):
            y = inner.bottom() - f * inner.height()
            p.drawLine(QtCore.QPointF(inner.left(), y), QtCore.QPointF(inner.right(), y))
        cal = self.progress.data.get("calibration", {})
        band = QtGui.QPen(QtGui.QColor(255, 122, 69, 70), 1)
        band.setStyle(E(QtCore.Qt, "PenStyle", "DashLine"))
        p.setPen(band)
        for k in ("light", "heavy"):
            if k in cal:
                y = inner.bottom() - cal[k] * inner.height()
                p.drawLine(QtCore.QPointF(inner.left(), y), QtCore.QPointF(inner.right(), y))

        st = self._stroke()
        label = "draw on the canvas: ember = pressure, teal = speed"
        if st and len(st.samples) > 2:
            smp = st.samples
            if len(smp) > 240:  # decimate: drawing cost stays flat however long the stroke
                step = len(smp) / 240.0
                smp = [smp[int(i * step)] for i in range(240)] + [smp[-1]]
            ts, ps, vs = series(smp)
            span = max(ts[-1], 0.25)
            vmax = max(max(vs), 1.0)
            path_p, path_v = QtGui.QPainterPath(), QtGui.QPainterPath()
            for i, (t, pr, v) in enumerate(zip(ts, ps, vs)):
                x = inner.left() + (t / span) * inner.width()
                yp = inner.bottom() - pr * inner.height()
                yv = inner.bottom() - (v / vmax) * inner.height()
                if i == 0:
                    path_p.moveTo(x, inner.bottom())
                    path_p.lineTo(x, yp)
                    path_v.moveTo(x, yv)
                else:
                    path_p.lineTo(x, yp)
                    path_v.lineTo(x, yv)
            path_p.lineTo(inner.left() + (ts[-1] / span) * inner.width(), inner.bottom())
            path_p.closeSubpath()
            p.setPen(QtGui.QPen(QtGui.QColor(EMBER), 1.5))
            p.setBrush(QtGui.QColor(255, 122, 69, 60))
            p.drawPath(path_p)
            p.setBrush(QtGui.QColor(0, 0, 0, 0))
            p.setPen(QtGui.QPen(QtGui.QColor(TEAL), 1.6))
            p.drawPath(path_v)
            m = st.metrics
            if m:
                label = "%.0f mm  |  %.0f mm/s  |  pressure %d to %d%%  |  %s" % (
                    m["length_mm"], m["speed_mm_s"], 100 * m["p_min"], 100 * m["p_max"], st.source)
            else:
                label = "drawing..."
        p.setPen(QtGui.QColor(INK))
        f = p.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() * 0.85))
        p.setFont(f)
        p.drawText(QtCore.QPointF(r.left() + 10, r.bottom() - 5), label)


class Card(QtWidgets.QFrame):
    jump = Signal(int)
    next_clicked = Signal(int)
    setup_clicked = Signal(object)  # list of setups from a card button

    def __init__(self, index, bite, parent=None):
        super().__init__(parent)
        self.index, self.bite = index, bite
        self.setObjectName("senseiCard")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        self.title = QtWidgets.QPushButton(bite.get("title", ""))
        self.title.setFlat(True)
        self.title.setCursor(POINTING)
        self.title.setToolTip("Jump here. Nothing is locked: test out of anything.")
        self.title.setStyleSheet("text-align:left; font-weight:bold; font-size:13px; border:none;")
        self.title.clicked.connect(lambda: self.jump.emit(self.index))
        lay.addWidget(self.title)

        self.body = QtWidgets.QLabel()
        self.body.setTextFormat(RICH)
        self.body.setWordWrap(True)
        lay.addWidget(self.body)

        self.hint = QtWidgets.QLabel()
        self.hint.setTextFormat(RICH)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#c9b79c; font-style:italic;")
        self.hint.hide()

        row = QtWidgets.QHBoxLayout()
        self.hint_btn = QtWidgets.QPushButton("Hint")
        self.hint_btn.clicked.connect(lambda: self.hint.setVisible(not self.hint.isVisible()))
        self.hint_btn.setVisible(bool(bite.get("hint")))
        self.next_btn = QtWidgets.QPushButton(bite.get("button", "Next"))
        self.next_btn.clicked.connect(lambda: self.next_clicked.emit(self.index))
        row.addWidget(self.hint_btn)
        row.addStretch(1)
        row.addWidget(self.next_btn)
        lay.addWidget(self.hint)
        for b in bite.get("buttons", []):
            btn = QtWidgets.QPushButton(b.get("label", "Do it"))
            btn.clicked.connect(lambda _=False, b=b: self.setup_clicked.emit(b.get("setup", [])))
            lay.addWidget(btn)
        self.counter = QtWidgets.QLabel("")
        self.counter.setStyleSheet("font-size:26px; font-weight:bold; color:%s;" % GOLD)
        self.counter.setVisible(bool(bite.get("quiet")))
        lay.addWidget(self.counter)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:%s;" % TEAL)
        lay.addWidget(self.status)
        lay.addLayout(row)
        self.refresh_text()
        self.set_state("ahead")
        pol = E(QtWidgets.QSizePolicy, "Policy", "Minimum")
        self.setSizePolicy(E(QtWidgets.QSizePolicy, "Policy", "Preferred"), pol)

    def minimumSizeHint(self):
        # Word-wrapped labels report a tiny minimum height, so a scroll area full of cards
        # squashes them. Ask the layout what height we need at our current width instead.
        sz = super().minimumSizeHint()
        lay = self.layout()
        if lay is not None and lay.hasHeightForWidth() and self.width() > 50:
            sz.setHeight(max(sz.height(), lay.heightForWidth(self.width())))
        return sz

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.updateGeometry()  # width changed: our needed height changed too

    def refresh_text(self):
        self.body.setText(expand_tokens(self.bite.get("body", "")))
        self.hint.setText(expand_tokens(self.bite.get("hint", "")))

    def set_state(self, state, done=False):
        self.state = state
        is_read = self.bite.get("check", {}).get("type", "read") == "read"
        border = {"current": EMBER, "ahead": "#3a3330", "passed": GOLD}[state]
        self.setStyleSheet("#senseiCard { border:2px solid %s; border-radius:10px; background:%s; }"
                           % (border, "#262120" if state == "current" else "#1d1917"))
        self.body.setStyleSheet("color:%s;" % (INK if state != "ahead" else "#8c8278"))
        self.next_btn.setVisible(state == "current" and is_read or state == "passed")
        if state == "passed":
            self.next_btn.setText("Next")
        prefix = "✓ " if done else ""
        self.title.setText(prefix + self.bite.get("title", ""))
        self.title.setStyleSheet(
            "text-align:left; font-weight:bold; font-size:14px; border:none; color:%s;"
            % ({"current": EMBER, "passed": GOLD}.get(state, "#a89a8a")))

    def coach(self, text, praise=False):
        self.status.setStyleSheet("color:%s;" % (GOLD if praise else TEAL))
        self.status.setText(text)
