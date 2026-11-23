# SPDX-License-Identifier: MIT
"""The Arto Sensei docker: Lessons (scrollytelling cards) and Dojo (free sandbox).

Startup rule: nothing here touches Krita's View or canvas until ks.app_up() and
ks.ready() say so. Every Qt callback is wrapped in devlog.safe, because PyQt5
turns an uncaught exception in a slot into a Krita crash.
"""
import json
import os
import random
import time

from krita import DockWidget

from . import devlog
from . import krita_state as ks
from . import library
from .checks import Ctx, run as run_check, action_names, PEN_CHECKS
from .metrics import drill_score
from .pen import PenTap, ActionLog
from .progress import Progress
from .qt import QtCore, QtWidgets, E, RICH
from .widgets import Card, Seismograph, INK, EMBER, TEAL, GOLD

HERE = os.path.dirname(os.path.abspath(__file__))
LESSON_DIR = os.path.join(HERE, "lessons")
VERSION = "1.0.0"
PRAISE = ("Nailed it.", "Clean!", "That's the stuff.", "Your hand just learned something.",
          "Sargent would nod. Probably.", "Yes. Exactly that.")

STYLE = """
QWidget#senseiRoot { background:#171412; color:%s; }
QTabWidget::pane { border:none; }
QPushButton { padding:3px 10px; }
QLabel#senseiBig { font-size:28px; font-weight:bold; color:%s; }
QWidget#senseiRoot QLabel { color:%s; }
QWidget#senseiInner { background:transparent; }
QScrollArea#senseiScroll { background:transparent; border:none; }
""" % (INK, GOLD, INK)

DRILLS = [
    ("free", "Free draw (just watch the seismograph)"),
    ("rhythm", "Rhythm: clean marks in 10 seconds (quantity!)"),
    ("even", "Even pressure: same weight, end to end"),
    ("swell", "Swell: thin, THICK, thin"),
    ("steady", "Steady speed: no braking"),
    ("flick", "Flick: fast and dead straight"),
    ("hatch", "Hatching: lanes of parallel strokes (dots help)"),
]
POSE_TIMES = [("30 s", 30), ("1 min", 60), ("2 min", 120), ("5 min", 300), ("10 min", 600)]


def _shrinkable(combo):
    """Long item labels must not force the docker wide."""
    combo.setSizeAdjustPolicy(E(QtWidgets.QComboBox, "SizeAdjustPolicy", "AdjustToMinimumContentsLengthWithIcon"))
    combo.setMinimumContentsLength(8)


def load_lessons():
    with open(os.path.join(LESSON_DIR, "curriculum.json"), "r", encoding="utf-8") as f:
        cur = json.load(f)
    out = []
    for entry in cur["lessons"]:
        lesson = dict(entry)
        path = os.path.join(LESSON_DIR, entry["id"] + ".json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    lesson.update(json.load(f))
            except Exception:
                devlog.log_exc("lesson load %s" % path)
        out.append(lesson)
    return out


class ArtoSenseiDocker(DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Arto Sensei")
        devlog.boot_facts()
        devlog.fact("arto_sensei_version", VERSION)
        self.progress = Progress()
        self.tap = PenTap(self)
        self.actions = ActionLog(self)
        self.ctx = Ctx(self.tap, self.actions, self.progress)
        self.lessons = load_lessons()
        self.lesson = None
        self.cards = []
        self.current = -1
        self._passed_at = None
        self._pending = None
        self._facts_done = False
        self.hatch_set = []
        self.streak = 0
        self.rhythm_t0, self.rhythm_n = None, 0
        self.pose_n, self.pose_end, self.downloader = 0, None, None

        root = QtWidgets.QWidget()
        root.setObjectName("senseiRoot")
        root.setStyleSheet(STYLE)
        outer = QtWidgets.QVBoxLayout(root)
        outer.setContentsMargins(4, 4, 4, 4)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_lessons(), "Lessons")
        self.tabs.addTab(self._build_dojo(), "Dojo")
        outer.addWidget(self.tabs)
        self.setWidget(root)

        self.tap.nav_gesture.connect(self._on_gesture)
        self.tap.stroke_done.connect(self._on_stroke)
        self._tick_timer = QtCore.QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(150)
        self._attach_timer = QtCore.QTimer(self)
        self._attach_timer.timeout.connect(self._attach)
        self._attach_timer.start(1000)
        self._pose_timer = QtCore.QTimer(self)
        self._pose_timer.timeout.connect(self._pose_tick)

        last = self.progress.data.get("last")
        start = 0
        if last:
            start = next((i for i, l in enumerate(self.lessons) if l["id"] == last[0]), 0)
        self.lesson_box.setCurrentIndex(start)
        self._load_lesson(start)
        devlog.log("docker init ok (v%s), waiting for the main window before touching Krita" % VERSION)

    # ------------------------------------------------------------ Krita hooks
    @devlog.safe
    def canvasChanged(self, canvas):
        QtCore.QTimer.singleShot(0, self._attach)

    def _try_pending(self):
        if self._pending is not None and ks.app_up():
            i, self._pending = self._pending, None
            self._goto(i)

    @devlog.safe
    def _attach(self):
        self._try_pending()
        if not ks.ready():
            return
        self.tap.refresh()
        if self.tap.widget is not None and not self.ctx.snap:
            self.ctx.snap = ks.snapshot()
        if self.tap.widget is not None and not self._facts_done:
            self._facts_done = True
            self.actions.watch(action_names(self.lessons) + [
                "view_zoom_in", "view_zoom_out", "zoom_to_100pct", "zoom_to_fit",
                "rotate_canvas_left", "rotate_canvas_right", "reset_canvas_rotation",
                "mirror_canvas", "view_show_canvas_only", "erase_action",
                "toggle_fg_bg", "reset_fg_bg", "increase_brush_size", "decrease_brush_size"])
            ks.api_facts()
            for c in self.cards:
                c.refresh_text()

    @devlog.safe
    def _on_gesture(self, kind):
        self.ctx.flags.add(kind)

    # ------------------------------------------------------------ Lessons tab
    def _build_lessons(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(2, 6, 2, 2)
        top = QtWidgets.QHBoxLayout()
        self.lesson_box = QtWidgets.QComboBox()
        for i, l in enumerate(self.lessons):
            ready = bool(l.get("bites"))
            self.lesson_box.addItem("%s%s" % (l["title"], "" if ready else "  (coming)"))
            if not ready:
                item = self.lesson_box.model().item(i)
                if item is not None:
                    item.setEnabled(False)
        self.lesson_box.activated.connect(self._load_lesson)
        _shrinkable(self.lesson_box)
        setup_btn = QtWidgets.QPushButton("Set me up")
        setup_btn.setToolTip("Re-run this card's setup (canvas, brush, guides).")
        setup_btn.clicked.connect(lambda: self._goto(self.current))
        top.addWidget(self.lesson_box, 1)
        top.addWidget(setup_btn)
        lay.addLayout(top)

        self.lesson_seis = Seismograph(self.tap, self.progress, 96)
        self.lesson_seis.hide()
        lay.addWidget(self.lesson_seis)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setObjectName("senseiScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(E(QtWidgets.QFrame, "Shape", "NoFrame"))
        self.card_host = QtWidgets.QWidget()
        self.card_host.setObjectName("senseiInner")
        self.scroll.viewport().setAutoFillBackground(False)
        self.card_lay = QtWidgets.QVBoxLayout(self.card_host)
        self.card_lay.setSpacing(10)
        # the host must grow with its cards, or the scroll area squashes them into the viewport
        self.card_lay.setSizeConstraint(E(QtWidgets.QLayout, "SizeConstraint", "SetMinimumSize"))
        self.card_lay.addStretch(1)
        self.scroll.setWidget(self.card_host)
        lay.addWidget(self.scroll, 1)
        self.anim = QtCore.QPropertyAnimation(self.scroll.verticalScrollBar(), b"value", self)
        self.anim.setDuration(450)
        self.anim.setEasingCurve(E(QtCore.QEasingCurve, "Type", "OutCubic"))
        foot = QtWidgets.QLabel("Arto Sensei %s  |  code MIT, lessons CC BY 4.0" % VERSION)
        foot.setStyleSheet("color:#6f665d; font-size:10px;")
        lay.addWidget(foot)
        return w

    @devlog.safe
    def _load_lesson(self, idx):
        lesson = self.lessons[idx]
        if not lesson.get("bites"):
            return
        self.lesson = lesson
        if self.lesson_box.currentIndex() != idx:
            self.lesson_box.setCurrentIndex(idx)
        for c in self.cards:
            c.setParent(None)
            c.deleteLater()
        self.cards = []
        for i, bite in enumerate(lesson["bites"]):
            card = Card(i, bite)
            card.jump.connect(self._goto)
            card.next_clicked.connect(self._advance_from)
            card.setup_clicked.connect(self._card_setup)
            self.card_lay.insertWidget(self.card_lay.count() - 1, card)
            self.cards.append(card)
        first = next((i for i, b in enumerate(lesson["bites"])
                      if not self.progress.is_done(lesson["id"], b["id"])), 0)
        self.current = -1
        self._pending = first
        self._try_pending()

    @devlog.safe
    def _goto(self, i):
        if not self.cards or i < 0 or i >= len(self.cards):
            return
        self.current = i
        self._passed_at = None
        for j, c in enumerate(self.cards):
            done = self.progress.is_done(self.lesson["id"], c.bite["id"])
            c.set_state("current" if j == i else ("passed" if done and j < i else "ahead"), done)
            if j != i:
                c.coach("")
        bite = self.cards[i].bite
        ks.run_setups(bite.get("setup"))
        self.ctx.begin()
        ctype = bite.get("check", {}).get("type")
        self.lesson_seis.setVisible(ctype in PEN_CHECKS and not bite.get("quiet"))
        self.cards[i].coach("")
        self.cards[i].counter.setText("")
        card = self.cards[i]
        self.anim.stop()
        self.anim.setStartValue(self.scroll.verticalScrollBar().value())
        self.anim.setEndValue(max(0, card.y() - 8))
        self.anim.start()

    @devlog.safe
    def _card_setup(self, setups):
        ks.run_setups(setups)
        self.ctx.snap = ks.snapshot()

    @devlog.safe
    def _advance_from(self, i):
        if i == self.current:
            if i < len(self.cards) - 1:
                self._goto(i + 1)
            else:
                self._next_lesson()
        elif self.cards[i].state == "passed":
            self._goto(i + 1)

    def _next_lesson(self):
        idx = self.lessons.index(self.lesson)
        for j in range(idx + 1, len(self.lessons)):
            if self.lessons[j].get("bites"):
                self._load_lesson(j)
                return

    @devlog.safe
    def _tick(self):
        if self.current < 0 or not self.cards or self._passed_at is not None:
            return
        card = self.cards[self.current]
        spec = card.bite.get("check", {"type": "read"})
        if spec.get("type", "read") == "read":
            return
        ok = run_check(spec, self.ctx)
        if self.ctx.counter and self.ctx.counter != card.counter.text():
            card.counter.setText(self.ctx.counter)
        if ok:
            self.progress.mark(self.lesson["id"], card.bite["id"])
            card.set_state("passed", True)
            card.coach(card.bite.get("praise") or random.choice(PRAISE), praise=True)
            self._passed_at = self.current
            nxt = self.current + 1
            if nxt < len(self.cards):
                QtCore.QTimer.singleShot(1400, lambda: self._goto(nxt) if self._passed_at == nxt - 1 else None)
        elif self.ctx.coach and self.ctx.coach != card.status.text():
            card.coach(self.ctx.coach)
            devlog.log("coach [%s/%s] %s" % (self.lesson["id"], card.bite["id"], self.ctx.coach))

    # ------------------------------------------------------------ Dojo tab
    def _build_dojo(self):
        w = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("senseiScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(E(QtWidgets.QFrame, "Shape", "NoFrame"))
        inner = QtWidgets.QWidget()
        inner.setObjectName("senseiInner")
        scroll.viewport().setAutoFillBackground(False)
        scroll.setHorizontalScrollBarPolicy(E(QtCore.Qt, "ScrollBarPolicy", "ScrollBarAlwaysOff"))
        lay = QtWidgets.QVBoxLayout(inner)
        lay.setContentsMargins(2, 6, 2, 2)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        intro = QtWidgets.QLabel(
            "<b>The Dojo.</b> No lessons, no gates. Warm up here every session. "
            "Pick a drill, paint on any layer, chase your best.")
        intro.setWordWrap(True)
        intro.setTextFormat(RICH)
        lay.addWidget(intro)
        self.drill_box = QtWidgets.QComboBox()
        for key, label in DRILLS:
            self.drill_box.addItem(label, key)
        self.drill_box.currentIndexChanged.connect(self._drill_changed)
        _shrinkable(self.drill_box)
        lay.addWidget(self.drill_box)

        row = QtWidgets.QHBoxLayout()
        for text, setups in (
                ("Fresh layer", ["ensure_document", {"do": "practice_layer", "clear": True}, "pressure_brush"]),
                ("Show dots", ["ensure_document", "practice_layer", {"do": "guides_hatching", "angle": 45}]),
                ("Hide dots", ["clear_guides"])):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(lambda _=False, s=setups: ks.run_setups(s))
            row.addWidget(b)
        lay.addLayout(row)

        self.dojo_seis = Seismograph(self.tap, self.progress, 140)
        lay.addWidget(self.dojo_seis)
        score_row = QtWidgets.QHBoxLayout()
        self.score_lbl = QtWidgets.QLabel("--")
        self.score_lbl.setObjectName("senseiBig")
        self.best_lbl = QtWidgets.QLabel("")
        self.best_lbl.setTextFormat(RICH)
        score_row.addWidget(self.score_lbl)
        score_row.addWidget(self.best_lbl, 1)
        lay.addLayout(score_row)
        self.stats_lbl = QtWidgets.QLabel("")
        self.stats_lbl.setTextFormat(RICH)
        self.stats_lbl.setWordWrap(True)
        lay.addWidget(self.stats_lbl)

        # ---- figure drawing
        lay.addWidget(self._heading("Timed figure drawing"))
        fig = QtWidgets.QGridLayout()
        self.set_box = QtWidgets.QComboBox()
        self.time_box = QtWidgets.QComboBox()
        _shrinkable(self.set_box)
        for label, secs in POSE_TIMES:
            self.time_box.addItem(label, secs)
        self.time_box.setCurrentIndex(1)
        self.pose_btn = QtWidgets.QPushButton("Start poses")
        self.pose_btn.clicked.connect(self._pose_start)
        skip = QtWidgets.QPushButton("Next")
        skip.clicked.connect(self._pose_next)
        stop = QtWidgets.QPushButton("Stop")
        stop.clicked.connect(self._pose_stop)
        fig.addWidget(self.set_box, 0, 0, 1, 2)
        fig.addWidget(self.time_box, 0, 2)
        fig.addWidget(self.pose_btn, 1, 0)
        fig.addWidget(skip, 1, 1)
        fig.addWidget(stop, 1, 2)
        lay.addLayout(fig)
        self.pose_lbl = QtWidgets.QLabel("")
        self.pose_lbl.setObjectName("senseiBig")
        lay.addWidget(self.pose_lbl)
        self.credit_lbl = QtWidgets.QLabel("")
        self.credit_lbl.setWordWrap(True)
        self.credit_lbl.setStyleSheet("color:#a89a8a; font-size:10px;")
        lay.addWidget(self.credit_lbl)

        # ---- library
        lay.addWidget(self._heading("Public-domain library"))
        lib_row = QtWidgets.QHBoxLayout()
        self.lib_box = QtWidgets.QComboBox()
        _shrinkable(self.lib_box)
        dl = QtWidgets.QPushButton("Download")
        dl.setToolTip("Fetch about 24 public-domain images from Wikimedia Commons (license-checked).")
        dl.clicked.connect(self._download)
        opn = QtWidgets.QPushButton("Open folder")
        opn.clicked.connect(lambda: __import__("webbrowser").open("file:///" + library.root().replace("\\", "/")))
        lib_row.addWidget(self.lib_box, 1)
        lib_row.addWidget(dl)
        lib_row.addWidget(opn)
        lay.addLayout(lib_row)
        self.lib_lbl = QtWidgets.QLabel("Drop your own JPGs or PNGs into any folder in the library, too.")
        self.lib_lbl.setWordWrap(True)
        self.lib_lbl.setStyleSheet("color:#a89a8a;")
        lay.addWidget(self.lib_lbl)
        lay.addStretch(1)
        self._refresh_sets()
        self._drill_changed()
        return w

    def _heading(self, text):
        h = QtWidgets.QLabel("<b>%s</b>" % text)
        h.setTextFormat(RICH)
        h.setStyleSheet("color:%s; margin-top:10px;" % EMBER)
        return h

    def _refresh_sets(self):
        for box in (self.set_box, self.lib_box):
            cur = box.currentData()
            box.clear()
            for key in library.set_names():
                box.addItem("%s (%d)" % (library.label(key), len(library.images(key))), key)
            if cur:
                i = box.findData(cur)
                if i >= 0:
                    box.setCurrentIndex(i)

    @devlog.safe
    def _download(self, *_):
        key = self.lib_box.currentData()
        if not key or key not in library.SETS:
            self.lib_lbl.setText("That folder is yours: fill it by hand.")
            return
        if self.downloader is not None and self.downloader.isRunning():
            self.lib_lbl.setText("Already downloading, hang on.")
            return
        self.downloader = library.Downloader(key, parent=self)
        self.downloader.progress.connect(self.lib_lbl.setText)
        self.downloader.finished_set.connect(lambda k, n: self._refresh_sets())
        self.downloader.start()

    @devlog.safe
    def _pose_start(self, *_):
        key = self.set_box.currentData() or "any"
        if not library.images(key):
            self.pose_lbl.setText("")
            self.credit_lbl.setText("No images in that set yet. Download one below, or drop images in its folder.")
            return
        self.pose_n = 0
        self._pose_next()

    @devlog.safe
    def _pose_next(self, *_):
        key = self.set_box.currentData() or "any"
        imgs = library.images(key)
        if not imgs:
            return
        d = ks.doc()
        if d is not None and self.pose_n and d.nodeByName("Pose %d" % self.pose_n) is not None:
            d.nodeByName("Pose %d" % self.pose_n).setVisible(False)
        self.pose_n += 1
        path = random.choice(imgs)
        ks.run_setups([{"do": "reference_doc", "path": path, "name": "Sensei Figure Drawing",
                        "fixed": [2400, 1500], "layer": "Pose %d" % self.pose_n, "clear": True}])
        c = library.credit_for(path)
        self.credit_lbl.setText(("%s | %s | %s" % (c.get("title", ""), c.get("artist", ""), c.get("license", "")))
                                if c else os.path.basename(path))
        self.pose_end = time.time() + int(self.time_box.currentData() or 60)
        self._pose_timer.start(250)
        self._pose_tick()

    @devlog.safe
    def _pose_tick(self):
        if self.pose_end is None:
            return
        left = int(round(self.pose_end - time.time()))
        if left <= 0:
            self._pose_next()
            return
        self.pose_lbl.setText("Pose %d  %d:%02d" % (self.pose_n, left // 60, left % 60))

    @devlog.safe
    def _pose_stop(self, *_):
        self._pose_timer.stop()
        self.pose_end = None
        self.pose_lbl.setText("Done. %d poses." % self.pose_n if self.pose_n else "")

    def _drill(self):
        return self.drill_box.currentData() or "free"

    @devlog.safe
    def _drill_changed(self, *_):
        self.hatch_set, self.streak = [], 0
        self.rhythm_t0, self.rhythm_n = None, 0
        best = self.progress.dojo_best(self._drill())
        self.score_lbl.setText("--")
        self.best_lbl.setText("best <b>%d</b>  |  best streak <b>%d</b>" % (best["best"], best["best_streak"]))
        self.dojo_seis.setVisible(self._drill() != "rhythm")  # rhythm is about speed: no graph lag

    @devlog.safe
    def _on_stroke(self, st):
        if self.tabs.currentIndex() != 1:
            return
        m = st.metrics
        drill = self._drill()
        if drill == "rhythm":
            now = time.time()
            if self.rhythm_t0 is None or now - self.rhythm_t0 > 10:
                if self.rhythm_t0 is not None:
                    self._rhythm_done()
                self.rhythm_t0, self.rhythm_n = now, 0
                QtCore.QTimer.singleShot(10000, self._rhythm_done)
            if m["length_mm"] >= 8:
                self.rhythm_n += 1
            self.score_lbl.setText("%d" % self.rhythm_n)
            return
        self.stats_lbl.setText(
            "<span style='color:%s'>pressure</span> %d to %d%% (wobble %d%%)  "
            "<span style='color:%s'>speed</span> %.0f mm/s (wobble %d%%)<br>"
            "length %.0f mm  |  straightness %d%%  |  angle %.0f deg  |  reach %d%% of screen"
            % (EMBER, 100 * m["p_min"], 100 * m["p_max"], 100 * m["p_cv"],
               TEAL, m["speed_mm_s"], 100 * m["speed_cv"], m["length_mm"],
               100 * m["straightness"], m["orientation_deg"], 100 * m["extent_frac"]))
        if drill == "free":
            return
        if drill == "hatch":
            self.hatch_set = (self.hatch_set + [m])[-10:]
            score = drill_score(drill, m, self.hatch_set)
        else:
            score = drill_score(drill, m)
        if score is None:
            self.score_lbl.setText("...")
            return
        self.streak = self.streak + 1 if score >= 70 else 0
        best = self.progress.dojo_best(drill, score)
        if self.streak > best["best_streak"]:
            best["best_streak"] = self.streak
            self.progress.save()
        self.score_lbl.setText("%d" % score)
        self.best_lbl.setText("best <b>%d</b>  |  streak <b>%d</b>  |  best streak <b>%d</b>"
                              % (best["best"], self.streak, best["best_streak"]))

    @devlog.safe
    def _rhythm_done(self):
        if self.rhythm_t0 is None or time.time() - self.rhythm_t0 < 9.9:
            return
        n, self.rhythm_t0 = self.rhythm_n, None
        best = self.progress.dojo_best("rhythm", n)
        self.score_lbl.setText("%d" % n)
        self.best_lbl.setText("Time! <b>%d</b> marks in 10 s  |  best <b>%d</b>" % (n, best["best"]))
