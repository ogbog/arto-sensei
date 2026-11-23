# SPDX-License-Identifier: MIT
"""Read Krita's state for checks, and perform lesson setups.

Setups are data in the lesson JSON: a string ("reset_view") or a dict
({"do": "rotate_view", "degrees": 35}). Unknown setups are logged, never fatal.

TRAP (crashed Krita 5.3.4 on launch): during startup activeView() returns a
View wrapper with no canvas, and View.flakeToCanvasTransform() on it is a C++
null dereference that Python cannot catch. Everything goes through view(),
which never hands out a hollow View, and ready().
"""
import math
import os
import random

from krita import Krita, ManagedColor

from . import devlog
from .qt import QtCore, QtGui, QtWidgets, E, Qt, ANTIALIAS, ARGB32, image_bytes

GUIDE_LAYER = "Sensei Guides"
PRACTICE_LAYER = "Sensei Practice"
REFERENCE_LAYER = "Reference"
PRESSURE_BRUSHES = ("b) Basic-5 Size Opacity", "b) Basic-5 Size", "b) Basic-2 Opacity",
                    "c) Pencil-2", "d) Ink-2 Fineliner")
ALIGN_CENTER = E(Qt, "AlignmentFlag", "AlignCenter")
SMOOTH = E(Qt, "TransformationMode", "SmoothTransformation")
# value boxes painted by the last value_ladder setup: {"doc": name, "rects": [...], "targets": [...]}
BOXES = {}


# ------------------------------------------------------------------ safe getters

def app_up():
    try:
        w = Krita.instance().activeWindow()
        return w is not None and w.qwindow() is not None and w.qwindow().isVisible()
    except Exception:
        return False


def window():
    return Krita.instance().activeWindow() if app_up() else None


def view():
    w = window()
    if w is None:
        return None
    v = w.activeView()
    if v is None or v.document() is None:
        return None
    return v


def canvas():
    v = view()
    return v.canvas() if v else None


def doc():
    return Krita.instance().activeDocument() if app_up() else None


def ready():
    if view() is None:
        return False
    from .pen import find_canvas_widget
    return find_canvas_widget() is not None


def flake_transform(v=None):
    if not ready():
        return None
    v = v or view()
    if v is None or not hasattr(v, "flakeToCanvasTransform"):
        return None
    try:
        return v.flakeToCanvasTransform()
    except Exception:
        return None


# ------------------------------------------------------------------ nodes

def all_nodes(d=None):
    d = d or doc()
    out = []
    if d is None:
        return out

    def walk(n):
        for c in n.childNodes():
            out.append(c)
            walk(c)
    walk(d.rootNode())
    return out


def node_uid(n):
    try:
        return n.uniqueId().toString()
    except Exception:
        return str(id(n))


def node_info(n):
    try:
        parent = n.parentNode()
        return {
            "name": n.name(), "type": n.type(), "blend": n.blendingMode(),
            "opacity": n.opacity(), "visible": n.visible(), "locked": n.locked(),
            "alpha_locked": n.alphaLocked(), "inherit_alpha": n.inheritAlpha(),
            "uid": node_uid(n),
            "parent_type": parent.type() if parent is not None else None,
        }
    except Exception:
        devlog.log_exc("node_info")
        return {}


def active_node():
    d = doc()
    return d.activeNode() if d else None


# ------------------------------------------------------------------ colors

def fg_qcolor():
    v = view()
    if v is None:
        return None
    try:
        return v.foregroundColor().colorForCanvas(v.canvas())
    except Exception:
        return None


def value_of(qc):
    """0 (black) .. 1 (white): the plain average of R, G, B. Beginner value, no color science."""
    return (qc.red() + qc.green() + qc.blue()) / (3 * 255.0)


def set_fg_gray(value):
    v = view()
    if v is None:
        return
    g = int(round(255 * max(0.0, min(1.0, value))))
    mc = ManagedColor.fromQColor(QtGui.QColor(g, g, g), v.canvas())
    setter = getattr(v, "setForeGroundColor", None) or getattr(v, "setForegroundColor", None)
    if setter:
        setter(mc)


def preset_count():
    try:
        return len(Krita.instance().resources("preset"))
    except Exception:
        return 0


# ------------------------------------------------------------------ tools and dockers

def _clean(t):
    return (t or "").replace("&", "").strip().lower()


def tool_checked(action_id):
    """True if the toolbox button for this tool is checked (clicked or hotkeyed)."""
    w = window()
    a = Krita.instance().action(action_id)
    if w is None or a is None:
        return False
    want = _clean(a.text())
    for b in w.qwindow().findChildren(QtWidgets.QToolButton):
        if b.isCheckable() and b.isChecked():
            if b.objectName() == action_id:
                return True
            tip = _clean(b.toolTip())
            if want and (tip.startswith(want) or _clean(b.text()).startswith(want)):
                return True
    return False


def docker_visible(name):
    w = window()
    if w is None:
        return False
    key = name.lower()
    for dk in w.dockers():
        if (dk.objectName().lower() == key or key in _clean(dk.windowTitle())) and dk.isVisible():
            return True
    return False


def views_of_active_doc():
    w, d = window(), doc()
    if w is None or d is None:
        return 0
    n = 0
    for v in w.views():
        vd = v.document()
        if vd is not None and vd.name() == d.name() and vd.fileName() == d.fileName():
            n += 1
    return n


# ------------------------------------------------------------------ snapshot

def snapshot():
    snap = {}
    if not ready():
        return snap
    c, v, d = canvas(), view(), doc()
    if c is not None:
        snap["zoom"] = c.zoomLevel()
        snap["rotation"] = c.rotation()
        snap["mirror"] = c.mirror()
    t = flake_transform(v)
    if t is not None:
        snap["dx"], snap["dy"] = t.dx(), t.dy()
    for key, getter in (("brush_size", "brushSize"), ("opacity", "paintingOpacity"),
                        ("flow", "paintingFlow"), ("brush_blend", "currentBlendingMode")):
        try:
            snap[key] = getattr(v, getter)()
        except Exception:
            pass
    try:
        p = v.currentBrushPreset()
        snap["preset"] = p.name() if p else None
    except Exception:
        pass
    qc = fg_qcolor()
    if qc is not None:
        snap["fg"] = (qc.red(), qc.green(), qc.blue())
    if d is not None:
        nodes = all_nodes(d)
        snap["doc"] = d.name()
        snap["node_uids"] = set(node_uid(n) for n in nodes)
        snap["node_count"] = len(nodes)
        n = d.activeNode()
        snap["active_uid"] = node_uid(n) if n else None
    snap["presets"] = preset_count()
    return snap


def api_facts():
    if not ready():
        return
    v, c, w = view(), canvas(), window()
    devlog.fact("view_methods", {m: hasattr(v, m) for m in (
        "flakeToCanvasTransform", "currentBrushPreset", "setCurrentBrushPreset", "brushSize",
        "setBrushSize", "paintingOpacity", "setPaintingOpacity", "paintingFlow",
        "currentBlendingMode", "setCurrentBlendingMode", "foregroundColor", "setForeGroundColor")})
    devlog.fact("canvas_methods", {m: hasattr(c, m) for m in (
        "zoomLevel", "setZoomLevel", "resetZoom", "rotation", "setRotation",
        "resetRotation", "mirror", "setMirror", "wrapAroundMode")})
    try:
        devlog.fact("dockers", sorted("%s | %s" % (dk.objectName(), dk.windowTitle()) for dk in w.dockers()))
        devlog.fact("checked_tool_buttons", [b.toolTip()[:60] for b in
                    w.qwindow().findChildren(QtWidgets.QToolButton) if b.isCheckable() and b.isChecked()][:20])
        devlog.fact("brush_blend", v.currentBlendingMode())
    except Exception as e:
        devlog.fact("ui_facts", "ERR %s" % e)
    try:
        names = sorted(Krita.instance().resources("preset").keys())
        devlog.fact("preset_count", len(names))
        devlog.fact("presets_blend_smudge",
                    [n for n in names if "blend" in n.lower() or "smudge" in n.lower()][:30])
    except Exception as e:
        devlog.fact("presets", "ERR %s" % e)


# ------------------------------------------------------------------ setups

def _find_doc(name):
    for d in Krita.instance().documents():
        if d.name() == name:
            return d
    return None


def _show_doc(d):
    w = window()
    if w is None:
        return
    for v in w.views():
        vd = v.document()
        if vd is not None and vd.name() == d.name():
            w.showView(v)
            return
    w.addView(d)


def _new_doc(name, w=2400, h=1600):
    app = Krita.instance()
    d = app.createDocument(w, h, name, "RGBA", "U8", "", 300.0)
    win = app.activeWindow() or app.openWindow()
    win.addView(d)
    return d


def _ensure_document(spec):
    if doc() is not None and view() is not None and not spec.get("name"):
        return
    name = spec.get("name", "Arto Sensei Practice")
    d = _find_doc(name)
    if d is not None:
        _show_doc(d)
        return
    _new_doc(name, spec.get("w", 2400), spec.get("h", 1600))


def _new_document(spec):
    _new_doc(spec.get("name", "Arto Sensei Practice"), spec.get("w", 2400), spec.get("h", 1600))


def _reset_view(spec):
    c = canvas()
    if c is None:
        return
    c.resetZoom()
    c.resetRotation()
    c.setMirror(False)


def _rotate_view(spec):
    c = canvas()
    if c is not None:
        c.setRotation(float(spec.get("degrees", 30)))


def _zoom_view(spec):
    c = canvas()
    if c is not None:
        c.setZoomLevel(float(spec.get("level", 2.0)))


def _top_child(d):
    kids = d.rootNode().childNodes()
    return kids[-1] if kids else None


def _remove_named(d, name):
    n = d.nodeByName(name)
    while n is not None:
        n.remove()
        n = d.nodeByName(name)


def _paint_image_layer(d, name, img, locked=True, opacity=255):
    _remove_named(d, name)
    n = d.createNode(name, "paintlayer")
    d.rootNode().addChildNode(n, _top_child(d))
    n.setPixelData(image_bytes(img), 0, 0, d.width(), d.height())
    n.setLocked(locked)
    n.setOpacity(opacity)
    return n


def _practice_layer(spec):
    """A paint layer to work on, kept under the guide layer so dots stay visible."""
    d = doc()
    if d is None:
        return
    name = spec.get("name", PRACTICE_LAYER)
    n = d.nodeByName(name)
    if n is None:
        n = d.createNode(name, "paintlayer")
        guides = d.nodeByName(GUIDE_LAYER)
        if guides is None:
            d.rootNode().addChildNode(n, _top_child(d))
        else:
            kids = d.rootNode().childNodes()
            idx = [node_uid(k) for k in kids].index(node_uid(guides))
            d.rootNode().addChildNode(n, kids[idx - 1] if idx > 0 else None)
    if spec.get("clear"):
        n.setPixelData(QtCore.QByteArray(bytes(d.width() * d.height() * 4)), 0, 0, d.width(), d.height())
    d.setActiveNode(n)
    d.refreshProjection()


def _pick_preset(names=(), contains=()):
    presets = Krita.instance().resources("preset")
    for name in names:
        if name and name in presets:
            return name, presets[name]
    for key in contains:
        for name in sorted(presets):
            if key.lower() in name.lower():
                return name, presets[name]
    return None, None


def _pressure_brush(spec):
    v = view()
    if v is None:
        return
    name, res = _pick_preset([spec.get("preset")] + list(PRESSURE_BRUSHES))
    if res is not None:
        v.setCurrentBrushPreset(res)
        devlog.log("brush ->", name)


def _brush(spec):
    """{"do": "brush", "preset": "...", "contains": ["Blender"], "opacity": 0.2, "size": 40, "blend": "normal"}"""
    v = view()
    if v is None:
        return
    if spec.get("preset") or spec.get("contains"):
        name, res = _pick_preset([spec.get("preset")], spec.get("contains", []))
        if res is not None:
            v.setCurrentBrushPreset(res)
            devlog.log("brush ->", name)
    if "opacity" in spec:
        v.setPaintingOpacity(float(spec["opacity"]))
    if "flow" in spec:
        v.setPaintingFlow(float(spec["flow"]))
    if "size" in spec:
        v.setBrushSize(float(spec["size"]))
    if "blend" in spec:
        v.setCurrentBlendingMode(spec["blend"])


def _fg_gray(spec):
    set_fg_gray(float(spec.get("value", 0.0)))


def _guides_hatching(spec):
    """Red start dots and target rings on a locked layer: hatching lanes."""
    d = doc()
    if d is None:
        return
    w, h = d.width(), d.height()
    img = QtGui.QImage(w, h, ARGB32)
    img.fill(0)
    p = QtGui.QPainter(img)
    p.setRenderHint(ANTIALIAS)
    red = QtGui.QColor(224, 48, 42)
    p.setPen(QtGui.QPen(red, max(2, w // 900)))
    lanes = int(spec.get("lanes", 10))
    ang = math.radians(float(spec.get("angle", 45)))
    length = float(spec.get("length", 0.28)) * min(w, h)
    gap = float(spec.get("gap", 0.035)) * min(w, h)
    r = max(4, int(min(w, h) * 0.006))
    ux, uy = math.cos(ang), -math.sin(ang)
    nx, ny = -uy, ux
    cx, cy = w * float(spec.get("cx", 0.5)), h * float(spec.get("cy", 0.5))
    for i in range(lanes):
        off = (i - (lanes - 1) / 2.0) * gap
        sx, sy = cx + nx * off - ux * length / 2, cy + ny * off - uy * length / 2
        ex, ey = sx + ux * length, sy + uy * length
        p.setBrush(red)
        p.drawEllipse(QtCore.QPointF(sx, sy), r, r)
        p.setBrush(QtGui.QColor(0, 0, 0, 0))
        p.drawEllipse(QtCore.QPointF(ex, ey), r * 1.6, r * 1.6)
    p.end()
    _paint_image_layer(d, GUIDE_LAYER, img, locked=True, opacity=200)
    _practice_layer({})


def _clear_guides(spec):
    d = doc()
    if d is not None:
        _remove_named(d, GUIDE_LAYER)
        d.refreshProjection()


def _value_ladder(spec):
    """Reference swatches (top row) + 10 empty boxes to paint (bottom row).

    mode "ladder": both rows. mode "blank": only the empty boxes, 0% and 100% labeled.
    Box values are plain gray steps i/9: 0, 11, 22 ... 100 percent.
    """
    name = spec.get("name", "Sensei Value Ladder")
    d = _find_doc(name)
    if d is None:
        d = _new_doc(name, 2600, 1200)
    else:
        _show_doc(d)
    w, h = d.width(), d.height()
    n = 10
    margin, gapx = 100, 24
    box = (w - 2 * margin - gapx * (n - 1)) // n
    top_y, bot_y = 160, 160 + box + 240
    ladder = spec.get("mode", "ladder") == "ladder"
    img = QtGui.QImage(w, h, ARGB32)
    img.fill(0)
    p = QtGui.QPainter(img)
    p.setRenderHint(ANTIALIAS)
    f = p.font()
    f.setPixelSize(44)
    p.setFont(f)
    rects, targets = [], []
    for i in range(n):
        x = margin + i * (box + gapx)
        val = i / float(n - 1)
        g = int(round(255 * val))
        if ladder:
            p.setPen(QtGui.QPen(QtGui.QColor(128, 128, 128), 3))
            p.setBrush(QtGui.QColor(g, g, g))
            p.drawRect(x, top_y, box, box)
        p.setPen(QtGui.QPen(QtGui.QColor(150, 150, 150), 4))
        p.setBrush(QtGui.QColor(0, 0, 0, 0))
        p.drawRect(x, bot_y, box, box)
        if ladder or i in (0, n - 1):
            p.setPen(QtGui.QColor(90, 90, 90))
            p.drawText(QtCore.QRect(x, bot_y + box + 14, box, 60), ALIGN_CENTER, "%d%%" % round(100 * val))
        rects.append((x, bot_y, box, box))
        targets.append(val)
    p.end()
    _paint_image_layer(d, GUIDE_LAYER, img, locked=True)
    BOXES.clear()
    BOXES.update({"doc": name, "rects": rects, "targets": targets})
    _practice_layer({"clear": bool(spec.get("clear", False))})


def box_values(d=None):
    """Average value (0..1) inside the inner 40% of every value box, over the projection."""
    d = d or doc()
    if d is None or not BOXES or d.name() != BOXES.get("doc"):
        return None
    out = []
    for (x, y, bw, bh) in BOXES["rects"]:
        ix, iy = int(x + bw * 0.3), int(y + bh * 0.3)
        iw, ih = max(4, int(bw * 0.4)), max(4, int(bh * 0.4))
        data = bytes(d.pixelData(ix, iy, iw, ih))
        tot, cnt = 0.0, 0
        for k in range(0, len(data) - 3, 16):  # every 4th pixel is plenty
            b, g, r, a = data[k], data[k + 1], data[k + 2], data[k + 3]
            af = a / 255.0
            tot += ((b + g + r) / 765.0) * af + (1.0 - af)  # unpainted = white paper
            cnt += 1
        out.append(tot / cnt if cnt else 1.0)
    return out


def _reference_doc(spec):
    """Sight-size setup: reference image on the left, blank paper on the right, same size."""
    from . import library
    path = spec.get("path")
    if not path and spec.get("pick"):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            None, "Pick a reference image", library.root(),
            "Images (*.png *.jpg *.jpeg *.tif *.tiff *.webp)")
    if not path:
        imgs = library.images(spec.get("set", "bargue"))
        if not imgs:
            devlog.log("reference_doc: library set empty", spec.get("set"))
            return
        path = random.choice(imgs)
    src = QtGui.QImage(path)
    if src.isNull():
        devlog.log("reference_doc: could not load", path)
        return
    if spec.get("fixed"):  # figure drawing: one canvas size for every pose
        w, h = int(spec["fixed"][0]), int(spec["fixed"][1])
        half = (w - 40) // 2
        src = src.scaled(half, h, E(Qt, "AspectRatioMode", "KeepAspectRatio"), SMOOTH).convertToFormat(ARGB32)
    else:  # sight size: reference and paper exactly the same size
        target_h = int(spec.get("height", 1600))
        src = src.scaledToHeight(target_h, SMOOTH).convertToFormat(ARGB32)
        w, h = src.width() * 2 + 40, target_h
    name = spec.get("name", "Sensei Sight Size")
    d = _find_doc(name)
    if d is None or d.width() != w or d.height() != h:
        d = _new_doc(name, w, h)
    else:
        _show_doc(d)
    img = QtGui.QImage(w, h, ARGB32)
    img.fill(0)
    p = QtGui.QPainter(img)
    split = (w - 40) // 2 if spec.get("fixed") else src.width()
    p.drawImage(max(0, (split - src.width()) // 2), (h - src.height()) // 2, src)
    p.setPen(QtGui.QPen(QtGui.QColor(200, 60, 50), 3))
    p.drawLine(split + 20, 0, split + 20, h)
    p.end()
    _paint_image_layer(d, REFERENCE_LAYER, img, locked=True)
    _practice_layer({"name": spec.get("layer", "Copy"), "clear": bool(spec.get("clear", True))})
    devlog.log("reference_doc:", os.path.basename(path))
    BOXES.clear()
    return path


def _paint_blob(spec):
    """A filled shape on its own layer, for alpha lock and clipping lessons."""
    d = doc()
    if d is None:
        return
    w, h = d.width(), d.height()
    img = QtGui.QImage(w, h, ARGB32)
    img.fill(0)
    p = QtGui.QPainter(img)
    p.setRenderHint(ANTIALIAS)
    c = spec.get("color", [200, 60, 50])
    p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 0)))
    p.setBrush(QtGui.QColor(*c))
    r = min(w, h) * float(spec.get("radius", 0.25))
    p.drawEllipse(QtCore.QPointF(w * float(spec.get("cx", 0.5)), h * float(spec.get("cy", 0.55))), r, r * 0.92)
    p.end()
    n = _paint_image_layer(d, spec.get("name", "Apple"), img, locked=False)
    d.setActiveNode(n)
    d.refreshProjection()


SETUPS = {
    "ensure_document": _ensure_document,
    "new_document": _new_document,
    "reset_view": _reset_view,
    "rotate_view": _rotate_view,
    "zoom_view": _zoom_view,
    "practice_layer": _practice_layer,
    "pressure_brush": _pressure_brush,
    "brush": _brush,
    "fg_gray": _fg_gray,
    "guides_hatching": _guides_hatching,
    "clear_guides": _clear_guides,
    "value_ladder": _value_ladder,
    "reference_doc": _reference_doc,
    "paint_blob": _paint_blob,
}


def run_setups(items):
    if not app_up():
        devlog.log("setups skipped, Krita not up yet:", items)
        return
    for it in items or []:
        spec = {"do": it} if isinstance(it, str) else dict(it)
        fn = SETUPS.get(spec.get("do"))
        if fn is None:
            devlog.log("unknown setup", spec)
            continue
        try:
            fn(spec)
        except Exception:
            devlog.log_exc("setup %s" % spec.get("do"))
