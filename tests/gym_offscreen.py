"""Offscreen gym: fake krita module + real PyQt5. Run: python tests/gym_offscreen.py"""
import sys, math, os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
os.environ["QT_QPA_PLATFORM"]="offscreen"
from PyQt5 import QtWidgets, QtCore, QtGui
app = QtWidgets.QApplication([])
from arto_sensei import metrics as M

def line(n=120, dur=0.6, L=400, pf=lambda f:0.5, ang=45, jitter=0):
    out=[]
    for i in range(n):
        f=i/(n-1); t=dur*f
        out.append((t, 100+L*f*math.cos(math.radians(ang)), 500-L*f*math.sin(math.radians(ang)), pf(f)))
    return out
ppm=4.0
m=M.stroke_metrics(line(pf=lambda f:0.1+0.8*f),ppm,2000)
print("ramp r", round(m["ramp_r"],3), "len mm", round(m["length_mm"]), "speed", round(m["speed_mm_s"]), "orient", round(m["orientation_deg"]))
print("judge ramp", M.judge(m, {"min_length_mm":40,"ramp_min":0.6,"pressure_span_min":0.5}))
sw=M.stroke_metrics(line(pf=lambda f:0.1+0.8*math.sin(math.pi*f)),ppm)
print("judge taper", M.judge(sw, {"taper":True}), "peak", round(sw["p_peak_frac"],2))
print("taper on ramp", M.judge(m, {"taper":True}))
ev=M.stroke_metrics(line(L=400,pf=lambda f:0.5+0.02*math.sin(20*f)),ppm)
print("even cv", round(ev["p_cv"],3), M.judge(ev, {"min_length_mm":60,"pressure_cv_max":0.12}))
slow=M.stroke_metrics(line(dur=4.0),ppm); print("slow", round(slow["speed_mm_s"]), M.judge(slow,{"speed_mm_s_max":50}))
fast=M.stroke_metrics(line(dur=0.3),ppm); print("fast", round(fast["speed_mm_s"]), M.judge(fast,{"speed_mm_s_min":200,"straightness_min":0.9}))
print("hatch spread", round(M.orientation_spread_deg([44,46,45,43,47]),2), round(M.orientation_spread_deg([179,1,2,178]),2))
print("drill scores", {d: M.drill_score(d, x) for d,x in [("even",ev),("swell",sw),("steady",m),("flick",fast)]})

# docker smoke + real QTabletEvent through PenTap
from arto_sensei.docker import ArtoSenseiDocker
import krita as fake
d = ArtoSenseiDocker(); d.show()
# --- startup trap: splash phase, hollow View. Pump events, fire every hook.
for _ in range(5):
    app.processEvents(); d.canvasChanged(None); d._attach(); d._tick()
QtCore.QTimer.singleShot(50, app.quit); app.exec_()
print("survived startup with hollow View; pending goto:", d._pending, "current:", d.current)
assert d.current == -1, "touched lessons before Krita was up"
fake.STATE["up"] = True
d._attach(); app.processEvents()
print("after window up: current", d.current)
assert d.current == 0
print("lessons", [l["id"] for l in d.lessons if l.get("bites")], "cards", len(d.cards), "current", d.current)
w = QtWidgets.QWidget(); w.resize(800,600); w.show()
d.tap.install(); d.tap.widget = w

class KritaInputManagerStandIn(QtCore.QObject):
    """Mimics KisInputManager: installed on the canvas AFTER us, consumes tablet events."""
    def eventFilter(self, obj, ev):
        return ev.type() in (QtCore.QEvent.TabletPress, QtCore.QEvent.TabletMove, QtCore.QEvent.TabletRelease)
eater = KritaInputManagerStandIn(); w.installEventFilter(eater)
got=[]; d.tap.stroke_done.connect(lambda s: got.append(s))
def tab(kind, x, y, p, btn=QtCore.Qt.LeftButton, ts=0):
    e = QtGui.QTabletEvent(kind, QtCore.QPointF(x,y), QtCore.QPointF(x,y), QtGui.QTabletEvent.Stylus, QtGui.QTabletEvent.Pen,
        p, 0, 0, 0, 0, 0, QtCore.Qt.NoModifier, 1, btn, btn if kind!=QtCore.QEvent.TabletRelease else QtCore.Qt.NoButton)
    e.setTimestamp(ts)
    QtWidgets.QApplication.sendEvent(w, e)
pts=line(n=80,dur=0.5,pf=lambda f:0.1+0.8*f)
for i,(t,x,y,p) in enumerate(pts):
    k = QtCore.QEvent.TabletPress if i==0 else (QtCore.QEvent.TabletRelease if i==len(pts)-1 else QtCore.QEvent.TabletMove)
    tab(k,x,y,p,ts=int(1000+t*1000))
print("strokes captured", len(got), "source", got[0].source if got else None, "samples", got[0].metrics["n"] if got else 0,
      "ramp", round(got[0].metrics["ramp_r"],2) if got else None)
# go to pen-pressure lesson crescendo bite, check passes with that stroke
idx=[l["id"] for l in d.lessons].index("pen-pressure"); d._load_lesson(idx); app.processEvents()
d._goto(1); d.ctx.since -= 0  # crescendo
for i,(t,x,y,p) in enumerate(pts):
    k = QtCore.QEvent.TabletPress if i==0 else (QtCore.QEvent.TabletRelease if i==len(pts)-1 else QtCore.QEvent.TabletMove)
    tab(k,x,y,p,ts=int(5000+t*1000))
d._tick(); print("crescendo passed:", d._passed_at==1, "| coach:", d.cards[1].status.text())
d._on_stroke(got[0]); print("dojo stats ok:", bool(d.stats_lbl.text()))
d.lesson_seis.repaint(); d.dojo_seis.grab().save(os.path.join(HERE, "out", "seis.png"))
d.tabs.setCurrentIndex(0); d.resize(360,700); d.grab().save(os.path.join(HERE, "out", "docker.png"))
print("selftest", open(os.path.join(os.path.dirname(M.__file__),"_dev","selftest.json")).read()[:300])
log=os.path.join(os.path.dirname(M.__file__),"_dev","log.txt")
print("LOG:", open(log).read() if os.path.exists(log) else "(empty)")

# --- feather calibration: a light line the driver chopped into 4 pieces must count as one
from arto_sensei.pen import Stroke
from arto_sensei.checks import c_calibrate, _gestures
d.ctx.begin(); d.ctx.since = 0
d.tap.history = []
t0 = 100.0
for k in range(4):  # 4 x 12 mm pieces, 0.05 s gaps, 2 mm apart
    st = Stroke("tablet", False)
    st.samples = [(t0 + k * 0.25 + i * 0.01, 100 + k * 78 + i * 4.0, 300, 0.08) for i in range(18)]
    st.metrics = M.stroke_metrics(st.samples, d.tap.px_per_mm, 2200)
    st.t_end = 10**12
    d.tap.history.append(st)
g = _gestures(d.tap.history, d.tap.px_per_mm)
print("feather gestures:", [(round(a), round(b, 2), n) for a, b, n in g])
ok = c_calibrate({"which": "light"}, d.ctx)
print("feather calibrated:", ok, "| coach:", d.ctx.coach)
assert ok and len(g) == 1 and g[0][2] == 4

# --- v1 checks: layer stack, node filters, value boxes, quiet rhythm counter
from arto_sensei import checks as C, krita_state as KS
class FakeNode:
    def __init__(s, **kw): s.kw = kw
infos = [dict(name="Flats", type="paintlayer", blend="normal", opacity=255, visible=True, locked=False,
              alpha_locked=False, inherit_alpha=False, uid="a", parent_type="grouplayer"),
         dict(name="Local", type="paintlayer", blend="normal", opacity=255, visible=True, locked=False,
              alpha_locked=False, inherit_alpha=True, uid="b", parent_type="grouplayer"),
         dict(name="Shadow", type="paintlayer", blend="normal", opacity=255, visible=True, locked=False,
              alpha_locked=False, inherit_alpha=True, uid="c", parent_type="grouplayer")]
nodes = [FakeNode(**i) for i in infos]
KS.all_nodes = lambda d=None: nodes
KS.node_info = lambda n: n.kw
d.ctx.snap = {"node_uids": {"a"}}
stack = {"type": "layer_stack", "order": ["flats", "local", "shadow"], "rules": {"shadow": {"blend": "multiply"}}}
r1 = C.run(stack, d.ctx); coach1 = d.ctx.coach
nodes[2].kw["blend"] = "multiply"
r2 = C.run(stack, d.ctx)
print("layer_stack wrong blend:", r1, "|", coach1, "| fixed:", r2)
assert (r1, r2) == (False, True)
nodes[1], nodes[2] = nodes[2], nodes[1]
r3 = C.run(stack, d.ctx); print("layer_stack out of order:", r3, "|", d.ctx.coach); assert not r3
assert C.run({"type": "node", "node_type": "paintlayer", "created": True, "inherit_alpha": True}, d.ctx)
assert not C.run({"type": "node", "node_type": "grouplayer", "created": True}, d.ctx)
KS.BOXES.update({"doc": "x", "rects": [None] * 10, "targets": [i / 9 for i in range(10)]})
d.ctx._throttle = {}
KS.box_values = lambda d=None: [i / 9 + (0.2 if i == 4 else 0.01) for i in range(10)]
rv = C.run({"type": "value_boxes", "tol": 0.08}, d.ctx); print("value_boxes one off:", rv, "|", d.ctx.coach); assert not rv
d.ctx._throttle = {}
KS.box_values = lambda d=None: [i / 9 for i in range(10)]
assert C.run({"type": "value_boxes", "tol": 0.08}, d.ctx)
d.ctx.begin(); d.ctx.since = 0; d.tap.history = []
for k in range(12):
    st = Stroke("tablet", False)
    st.samples = [(200 + k * 0.5 + i * 0.01, 100 + i * 6.0, 300 + k * 20, 0.5) for i in range(15)]
    st.metrics = M.stroke_metrics(st.samples, d.tap.px_per_mm, 2200); st.t_end = 10**12
    d.tap.history.append(st)
rc = C.run({"type": "stroke_count", "count": 10, "within_s": 8, "min_length_mm": 10, "orientation_spread_max": 8}, d.ctx)
print("stroke_count:", rc, d.ctx.counter); assert rc

# --- every card of every lesson builds and visits without blowing up
import arto_sensei.krita_state as KS2
KS2.run_setups = lambda items: None   # setups need a real Krita; UI flow is what we test here
n_cards = 0
for li, lesson in enumerate(d.lessons):
    if not lesson.get("bites"):
        continue
    d._load_lesson(li); app.processEvents()
    for ci in range(len(d.cards)):
        d._goto(ci); d._tick(); n_cards += 1
print("visited cards:", n_cards)
d.tabs.setCurrentIndex(0); d.resize(380, 820); d._load_lesson([l["id"] for l in d.lessons].index("hand-motion"))
d._goto(1); app.processEvents(); d.grab().save(os.path.join(HERE, "out", "quiet_card.png"))
