# SPDX-License-Identifier: MIT
"""Challenge checks. Same grammar as Blender Bites: every check is data.

A check returns True/False and may call ctx.say("coach line") to talk back.
Teaching tool, not assessment tool: the coach line matters more than the bool.
"""
import re
import time

from krita import Krita

from . import devlog
from . import krita_state as ks
from .metrics import judge, orientation_spread_deg, _cv


class Ctx(object):
    def __init__(self, tap, actions, progress):
        self.tap, self.actions, self.progress = tap, actions, progress
        self.snap, self.since, self.flags, self.coach = {}, time.time(), set(), ""
        self.counter = ""
        self._memo, self._throttle = {}, {}

    def begin(self):
        self.snap = ks.snapshot()
        self.since = time.time()
        self.flags = set()
        self.coach = ""
        self.counter = ""
        self._memo, self._throttle = {}, {}

    def say(self, text):
        self.coach = text

    def strokes(self):
        return [s for s in self.tap.strokes_since(self.since) if s.metrics]

    def calib(self):
        return self.progress.data.get("calibration", {})

    def stroke_key(self):
        last = self.tap.last()
        return (len(self.tap.history), last.t_end if last else 0)

    def throttled(self, key, seconds, fn):
        """Expensive reads (pixels, presets) at most every `seconds`."""
        now = time.time()
        hit = self._throttle.get(key)
        if hit and now - hit[0] < seconds:
            return hit[1]
        val = fn()
        self._throttle[key] = (now, val)
        return val


def _aslist(v):
    return v if isinstance(v, (list, tuple)) else [v]


def _angle_diff(a, b):
    return abs(((a - b + 180.0) % 360.0) - 180.0)


# ------------------------------------------------------------------ view

def c_read(spec, ctx):
    return False


def c_has_document(spec, ctx):
    ok = ks.doc() is not None and ks.view() is not None
    if not ok:
        ctx.say("Open or make a canvas first (File > New), or hit Set me up.")
    return ok


def c_zoom_changed(spec, ctx):
    c = ks.canvas()
    z0 = ctx.snap.get("zoom")
    if c is None or not z0:
        return False
    r = c.zoomLevel() / z0
    f = spec.get("factor", 1.5)
    if abs(r - 1) > 0.01:
        ctx.say("Zoom is %d%% of where you started." % round(100 * r))
    if spec.get("direction") == "in":
        return r >= f
    if spec.get("direction") == "out":
        return r <= 1.0 / f
    return r >= f or r <= 1.0 / f


def c_rotated(spec, ctx):
    c = ks.canvas()
    if c is None or "rotation" not in ctx.snap:
        return False
    d = _angle_diff(c.rotation(), ctx.snap["rotation"])
    if d > 0.5:
        ctx.say("Turned %.0f degrees." % d)
    return d >= spec.get("degrees", 20)


def c_rotation_is(spec, ctx):
    c = ks.canvas()
    return c is not None and _angle_diff(c.rotation(), spec.get("degrees", 0)) <= spec.get("tolerance", 0.5)


def c_mirrored(spec, ctx):
    c = ks.canvas()
    return c is not None and bool(c.mirror()) == bool(spec.get("value", True))


def c_wrap_around(spec, ctx):
    c = ks.canvas()
    return c is not None and bool(c.wrapAroundMode()) == bool(spec.get("value", True))


def c_panned(spec, ctx):
    if "pan" in ctx.flags:
        return True
    t = ks.flake_transform()
    if t is None or "dx" not in ctx.snap:
        return False
    moved = ((t.dx() - ctx.snap["dx"]) ** 2 + (t.dy() - ctx.snap["dy"]) ** 2) ** 0.5
    c = ks.canvas()
    zoom_same = c is not None and abs(c.zoomLevel() - ctx.snap.get("zoom", 0)) < 1e-6
    return zoom_same and moved >= spec.get("pixels", 120)


def c_views(spec, ctx):
    n = ks.views_of_active_doc()
    return n >= spec.get("min", 2)


# ------------------------------------------------------------------ actions, tools, dockers

def c_action(spec, ctx):
    names = spec.get("names") or [spec["name"]]
    return any(ctx.actions.fired(n, ctx.since) for n in names)


def c_action_checked(spec, ctx):
    a = Krita.instance().action(spec["name"])
    return a is not None and a.isCheckable() and a.isChecked() == bool(spec.get("value", True))


def c_tool_active(spec, ctx):
    ids = _aslist(spec.get("id") or spec.get("ids"))
    return any(ctx.actions.fired(i, ctx.since) or ks.tool_checked(i) for i in ids)


def c_docker_visible(spec, ctx):
    return ks.docker_visible(spec["name"]) == bool(spec.get("value", True))


def c_flag(spec, ctx):
    return spec["name"] in ctx.flags


# ------------------------------------------------------------------ brush

def c_brush_changed(spec, ctx):
    v = ks.view()
    if v is None:
        return False
    p = v.currentBrushPreset()
    return p is not None and p.name() != ctx.snap.get("preset")


def c_brush_size_changed(spec, ctx):
    v = ks.view()
    s0 = ctx.snap.get("brush_size")
    if v is None or not s0:
        return False
    r = v.brushSize() / s0
    f = spec.get("factor", 1.5)
    if spec.get("direction") == "up":
        return r >= f
    if spec.get("direction") == "down":
        return r <= 1.0 / f
    return r >= f or r <= 1.0 / f


def _slider(spec, ctx, getter, key):
    v = ks.view()
    if v is None:
        return False
    val = getattr(v, getter)()
    if "below" in spec:
        ctx.say("Now at %d%%." % round(100 * val))
        return val <= spec["below"]
    if "above" in spec:
        ctx.say("Now at %d%%." % round(100 * val))
        return val >= spec["above"]
    return abs(val - ctx.snap.get(key, val)) >= spec.get("delta", 0.15)


def c_opacity(spec, ctx):
    return _slider(spec, ctx, "paintingOpacity", "opacity")


def c_flow(spec, ctx):
    return _slider(spec, ctx, "paintingFlow", "flow")


def c_brush_blend(spec, ctx):
    v = ks.view()
    if v is None:
        return False
    mode = v.currentBlendingMode()
    if "not" in spec:
        return mode not in _aslist(spec["not"])
    return mode in _aslist(spec.get("mode", "normal"))


def c_preset_added(spec, ctx):
    n = ctx.throttled("presets", 1.5, ks.preset_count)
    return n > ctx.snap.get("presets", n)


# ------------------------------------------------------------------ color

def c_fg_value(spec, ctx):
    qc = ks.fg_qcolor()
    if qc is None:
        return False
    val = ks.value_of(qc)
    want, tol = spec["value"], spec.get("tol", 0.05)
    if spec.get("max_sat") is not None and qc.hsvSaturationF() > spec["max_sat"]:
        ctx.say("That has color in it. Keep it a pure gray (saturation near zero).")
        return False
    if abs(val - want) <= tol:
        return True
    ctx.say("Your color is %d%% value; aim for %d%%. %s" % (
        round(100 * val), round(100 * want), "Lighter." if val < want else "Darker."))
    return False


def c_fg_changed(spec, ctx):
    qc = ks.fg_qcolor()
    return qc is not None and (qc.red(), qc.green(), qc.blue()) != ctx.snap.get("fg")


# ------------------------------------------------------------------ layers

def _node_match(info, f, ctx):
    if not info:
        return False
    if "node_type" in f and info["type"] not in _aslist(f["node_type"]):
        return False
    if "name_is" in f and info["name"].lower() != f["name_is"].lower():
        return False
    if "name_contains" in f and not any(s.lower() in info["name"].lower() for s in _aslist(f["name_contains"])):
        return False
    if "blend" in f and info["blend"] not in _aslist(f["blend"]):
        return False
    for key in ("visible", "locked", "alpha_locked", "inherit_alpha"):
        if key in f and bool(info[key]) != bool(f[key]):
            return False
    if "opacity_max" in f and info["opacity"] > (f["opacity_max"] * 255 if f["opacity_max"] <= 1 else f["opacity_max"]):
        return False
    if "opacity_min" in f and info["opacity"] < (f["opacity_min"] * 255 if f["opacity_min"] <= 1 else f["opacity_min"]):
        return False
    if "parent_type" in f and info["parent_type"] not in _aslist(f["parent_type"]):
        return False
    if f.get("created") and info["uid"] in ctx.snap.get("node_uids", set()):
        return False
    return True


def c_node(spec, ctx):
    """Some layer (or the active one, with "active": true) matches every filter given."""
    if spec.get("active"):
        n = ks.active_node()
        return n is not None and _node_match(ks.node_info(n), spec, ctx)
    hits = sum(1 for n in ks.all_nodes() if _node_match(ks.node_info(n), spec, ctx))
    return hits >= spec.get("min_count", 1)


def c_node_count(spec, ctx):
    n = len(ks.all_nodes())
    d = n - ctx.snap.get("node_count", n)
    want = spec.get("delta", 1)
    return d >= want if want > 0 else d <= want


def c_active_changed(spec, ctx):
    n = ks.active_node()
    return n is not None and ks.node_uid(n) != ctx.snap.get("active_uid")


def c_layer_stack(spec, ctx):
    """Layers named like `order` exist bottom-to-top in that order; `rules` add blend modes."""
    infos = [ks.node_info(n) for n in ks.all_nodes()]
    infos = [i for i in infos if i and i["type"] != "grouplayer"]
    pos = []
    for pat in spec["order"]:
        idx = next((k for k, i in enumerate(infos) if pat.lower() in i["name"].lower()), None)
        if idx is None:
            ctx.say("Missing a layer with \"%s\" in its name." % pat)
            return False
        pos.append((pat, idx))
    for (a, ia), (b, ib) in zip(pos, pos[1:]):
        if ib < ia:
            ctx.say("\"%s\" should sit above \"%s\" in the stack. Drag it up." % (b, a))
            return False
    for pat, rule in (spec.get("rules") or {}).items():
        info = next((i for i in infos if pat.lower() in i["name"].lower()), None)
        if info and "blend" in rule and info["blend"] not in _aslist(rule["blend"]):
            ctx.say("\"%s\" should use blend mode %s (it's %s)." % (
                info["name"], " or ".join(_aslist(rule["blend"])), info["blend"]))
            return False
        if info and "inherit_alpha" in rule and bool(info["inherit_alpha"]) != bool(rule["inherit_alpha"]):
            ctx.say("Clip \"%s\" to the shapes below: turn on Inherit Alpha." % info["name"])
            return False
    return True


def c_has_selection(spec, ctx):
    d = ks.doc()
    if d is None:
        return False
    has = d.selection() is not None
    return has == bool(spec.get("value", True))


def c_doc_saved(spec, ctx):
    d = ks.doc()
    if d is None:
        return False
    fn = d.fileName() or ""
    ext = spec.get("ext")
    if not fn or (ext and not fn.lower().endswith(ext)):
        ctx.say("Not saved as %s yet." % (ext or "a file"))
        return False
    return not d.modified()


def c_reference_loaded(spec, ctx):
    d = ks.doc()
    ok = d is not None and d.nodeByName(ks.REFERENCE_LAYER) is not None
    if not ok:
        ctx.say("Press the button on this card to load a plate (or pick your own image).")
    return ok


# ------------------------------------------------------------------ values

def c_value_boxes(spec, ctx):
    vals = ctx.throttled("boxes", 0.6, ks.box_values)
    if vals is None:
        ctx.say("I lost track of the value boxes. Hit Set me up to rebuild them.")
        return False
    targets = ks.BOXES["targets"]
    tol = spec.get("tol", 0.08)
    idx = spec.get("indices") or range(len(vals))
    wrong = [(i, vals[i], targets[i]) for i in idx if abs(vals[i] - targets[i]) > tol]
    if not wrong:
        return True
    i, got, want = wrong[0]
    ctx.say("%d of %d boxes on target. Box %d (%d%%) reads %d%%: %s." % (
        len(list(idx)) - len(wrong), len(list(idx)), i + 1, round(100 * want), round(100 * got),
        "darker" if got > want else "lighter"))
    return False


# ------------------------------------------------------------------ pen

def c_pen_detected(spec, ctx):
    for s in ctx.strokes():
        if s.source == "tablet":
            ctx.progress.data.setdefault("calibration", {})["tablet_ok"] = True
            ctx.progress.save()
            return True
        ctx.say("That came in as a mouse. Check your tablet driver is running, then try "
                "Settings > Configure Krita > Tablet Settings and switch the tablet input API.")
    return False


def c_stroke(spec, ctx):
    """`count` strokes in a row that pass `criteria`, plus optional set rules. Memoized per stroke."""
    key = ("stroke", ctx.stroke_key())
    if key in ctx._memo:
        return ctx._memo[key]
    ctx._memo.clear()
    result = _stroke(spec, ctx)
    ctx._memo[key] = result
    return result


def _stroke(spec, ctx):
    strokes = ctx.strokes()
    if not strokes:
        return False
    crit = spec.get("criteria", {})
    need = int(spec.get("count", 1))
    calib = ctx.calib()
    run, last_msg = [], ""
    for s in strokes:
        ok, msg = judge(s.metrics, crit, calib, s.source)
        run = run + [s] if ok else []
        last_msg = msg
    if run and len(run) < need:
        ctx.say("Yes! %d of %d. Again." % (len(run), need))
    elif not run:
        ctx.say(last_msg)
    if len(run) < need:
        return False
    recent = [s.metrics for s in run[-need:]]
    if spec.get("orientation_spread_max") is not None and need > 1:
        spread = orientation_spread_deg([m["orientation_deg"] for m in recent])
        if spread > spec["orientation_spread_max"]:
            ctx.say("Every stroke good, but the angles drifted %.0f degrees. Lock the wrist, "
                    "slide the arm." % spread)
            return False
    if spec.get("pace_cv_max") is not None and need > 1:
        pace = _cv([m["speed_mm_s"] for m in recent])
        if pace > spec["pace_cv_max"]:
            ctx.say("Rhythm check: your speed changed %d%% across the set. Metronome it." % (100 * pace))
            return False
    return True


def c_stroke_count(spec, ctx):
    """Quiet rhythm counter: quantity, not quality. Cheap per stroke, no coaching per mark."""
    key = ("count", ctx.stroke_key())
    if key in ctx._memo:
        return ctx._memo[key]
    ctx._memo.clear()
    min_mm = spec.get("min_length_mm", 8)
    marks = [s for s in ctx.strokes() if s.metrics["length_mm"] >= min_mm]
    need = int(spec.get("count", 10))
    within = spec.get("within_s")
    if within:
        # best sliding window of marks that started within `within` seconds of each other
        best = 0
        starts = [s.samples[0][0] for s in marks]
        j = 0
        for i in range(len(starts)):
            while starts[i] - starts[j] > within:
                j += 1
            best = max(best, i - j + 1)
        n = best
        ctx.counter = "%d / %d in %ds" % (min(n, need), need, within)
    else:
        n = len(marks)
        ctx.counter = "%d / %d" % (min(n, need), need)
    ok = n >= need
    if ok and spec.get("orientation_spread_max") is not None:
        spread = orientation_spread_deg([s.metrics["orientation_deg"] for s in marks[-need:]])
        if spread > spec["orientation_spread_max"]:
            ctx.say("Count's there! Now keep them parallel: angles drifted %.0f degrees." % spread)
            ok = False
    ctx._memo[key] = ok
    return ok


def _gestures(strokes, px_per_mm, max_gap_s=0.3, max_gap_mm=15.0):
    """Stitch strokes the driver chopped up (feather-light pressure lifts the tip)
    into gestures: [(length_mm, mean_pressure_weighted_by_length, pieces)]."""
    out, cur = [], None
    for s in strokes:
        m = s.metrics
        if cur is not None:
            last = cur["last"]
            gap_s = s.samples[0][0] - last.samples[-1][0]
            gap_mm = ((s.samples[0][1] - last.samples[-1][1]) ** 2 +
                      (s.samples[0][2] - last.samples[-1][2]) ** 2) ** 0.5 / px_per_mm
            if 0 <= gap_s <= max_gap_s and gap_mm <= max_gap_mm:
                cur["len"] += m["length_mm"]
                cur["pw"] += m["p_mean"] * m["length_mm"]
                cur["n"] += 1
                cur["last"] = s
                continue
            out.append(cur)
        cur = {"len": m["length_mm"], "pw": m["p_mean"] * m["length_mm"], "n": 1, "last": s}
    if cur is not None:
        out.append(cur)
    return [(g["len"], g["pw"] / max(g["len"], 1e-6), g["n"]) for g in out]


def c_calibrate(spec, ctx):
    """Record a personal pressure point ('light' or 'heavy') from a long line."""
    which = spec.get("which", "light")
    need_mm = spec.get("min_length_mm", 25)
    gestures = _gestures([s for s in ctx.strokes() if s.source == "tablet"], ctx.tap.px_per_mm)
    if not gestures:
        mouse = [s for s in ctx.strokes() if s.source != "tablet"]
        ctx.say("That came in as a mouse, not the pen." if mouse else
                "One long line, at least %d mm." % need_mm)
        return False
    length, p_mean, pieces = gestures[-1]
    if length < need_mm:
        ctx.say("That line measured %d mm%s. I need %d mm: go longer." % (
            int(length), " in %d pieces (the pen lifted)" % pieces if pieces > 1 else "", need_mm))
        return False
    cal = ctx.progress.data.setdefault("calibration", {})
    if which == "light":
        if p_mean > spec.get("max_light", 0.3):
            ctx.say("That's a handshake, not a feather: %d%% pressure. Barely kiss the surface."
                    % (100 * p_mean))
            return False
        cal["light"] = round(p_mean, 3)
        ctx.say("Your feather: %d%% pressure." % (100 * p_mean))
        ctx.progress.save()
        return True
    light = cal.get("light", 0.05)
    if p_mean < light + 0.2:
        ctx.say("That was %d%%, barely past your feather (%d%%). Lean in like you mean it."
                % (100 * p_mean, 100 * light))
        return False
    cal["heavy"] = round(p_mean, 3)
    ctx.say("Your range: %d%% to %d%%. Everything from here is graded against YOUR hand."
            % (100 * light, 100 * cal["heavy"]))
    ctx.progress.save()
    return True


def c_all(spec, ctx):
    return all(run(s, ctx) for s in spec["checks"])


def c_any(spec, ctx):
    return any(run(s, ctx) for s in spec["checks"])


CHECKS = {
    "read": c_read, "has_document": c_has_document,
    "zoom_changed": c_zoom_changed, "rotated": c_rotated, "rotation_is": c_rotation_is,
    "mirrored": c_mirrored, "wrap_around": c_wrap_around, "panned": c_panned, "views": c_views,
    "action": c_action, "action_checked": c_action_checked, "tool_active": c_tool_active,
    "docker_visible": c_docker_visible, "flag": c_flag,
    "brush_changed": c_brush_changed, "brush_size_changed": c_brush_size_changed,
    "opacity": c_opacity, "flow": c_flow, "brush_blend": c_brush_blend, "preset_added": c_preset_added,
    "fg_value": c_fg_value, "fg_changed": c_fg_changed,
    "node": c_node, "node_count": c_node_count, "active_changed": c_active_changed,
    "layer_stack": c_layer_stack, "has_selection": c_has_selection, "doc_saved": c_doc_saved,
    "reference_loaded": c_reference_loaded, "value_boxes": c_value_boxes,
    "pen_detected": c_pen_detected, "stroke": c_stroke, "stroke_count": c_stroke_count,
    "calibrate": c_calibrate,
    "all": c_all, "any": c_any,
}

PEN_CHECKS = ("stroke", "calibrate", "pen_detected")


def action_names(lessons):
    """Every Krita action any lesson mentions, so ActionLog can watch them early."""
    out = set()

    def walk(o):
        if isinstance(o, dict):
            if o.get("type") == "action":
                out.update(o.get("names") or [o.get("name")])
            if o.get("type") == "tool_active":
                out.update(_aslist(o.get("id") or o.get("ids")))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            out.update(re.findall(r"\{key:([A-Za-z0-9_/ ]+)", o))
    walk(lessons)
    out.discard(None)
    return sorted(out)


def run(spec, ctx):
    fn = CHECKS.get(spec.get("type", "read"))
    if fn is None:
        devlog.log("unknown check", spec)
        return False
    try:
        return bool(fn(spec, ctx))
    except Exception:  # a broken check must never break Krita
        devlog.log_exc("check %s" % spec.get("type"))
        return False
