"""Validate every lesson: ids, check types, setups, criteria keys, Krita action names, house style.

Run:  python tests/validate_lessons.py [path/to/actions_index.tsv]
The optional TSV (name<TAB>shortcut<TAB>text<TAB>file) is built from Krita's share/krita/actions/*.action
files; with it, every action name a lesson uses must exist in the real Krita install.
"""
import json
import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                       # fake krita module
sys.path.insert(0, os.path.dirname(HERE))      # the plugin package
from PyQt5 import QtWidgets  # noqa: E402
_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from arto_sensei.checks import CHECKS, action_names  # noqa: E402
from arto_sensei.krita_state import SETUPS  # noqa: E402

LESSONS = os.path.join(os.path.dirname(HERE), "arto_sensei", "lessons")
CRITERIA = {"source", "min_length_mm", "min_extent_frac", "max_mean_pressure", "min_mean_pressure",
            "pressure_span_min", "ramp_min", "taper", "pressure_cv_max", "speed_mm_s_max",
            "speed_mm_s_min", "speed_cv_max", "straightness_min", "orientation_deg", "orientation_tol"}
BITE_KEYS = {"id", "title", "body", "hint", "check", "setup", "praise", "buttons", "quiet", "button", "unlock"}
# canvas-input profile keys and blend-mode actions with spaces are fine; everything else must exist
errors, warnings = [], []


def err(where, msg):
    errors.append("%s: %s" % (where, msg))


def walk_checks(spec, where):
    t = spec.get("type", "read")
    if t not in CHECKS:
        err(where, "unknown check type %r" % t)
    if t in ("all", "any"):
        for s in spec.get("checks", []):
            walk_checks(s, where)
    if t == "stroke":
        bad = set(spec.get("criteria", {})) - CRITERIA
        if bad:
            err(where, "unknown stroke criteria %s" % sorted(bad))


def walk_setups(items, where):
    for it in items or []:
        name = it if isinstance(it, str) else it.get("do")
        if name not in SETUPS:
            err(where, "unknown setup %r" % name)


def main():
    real = None
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            real = {line.split("\t")[0] for line in f if line.strip()}
    with open(os.path.join(LESSONS, "curriculum.json"), encoding="utf-8") as f:
        cur = json.load(f)
    ids = [l["id"] for l in cur["lessons"]]
    all_lessons = []
    for lid in ids:
        path = os.path.join(LESSONS, lid + ".json")
        if not os.path.exists(path):
            err(lid, "lesson file missing")
            continue
        raw = open(path, encoding="utf-8").read()
        if "\u2014" in raw:
            err(lid, "em dash found (house style: never)")
        lesson = json.loads(raw)
        all_lessons.append(lesson)
        if lesson.get("id") != lid:
            err(lid, "id mismatch %r" % lesson.get("id"))
        seen = set()
        for b in lesson.get("bites", []):
            where = "%s/%s" % (lid, b.get("id"))
            for k in ("id", "title", "body", "check"):
                if k not in b:
                    err(where, "missing %s" % k)
            extra = set(b) - BITE_KEYS
            if extra:
                err(where, "unknown bite keys %s" % sorted(extra))
            if b.get("id") in seen:
                err(where, "duplicate bite id")
            seen.add(b.get("id"))
            walk_checks(b.get("check", {}), where)
            walk_setups(b.get("setup"), where)
            for btn in b.get("buttons", []):
                walk_setups(btn.get("setup"), where + " (button)")
        if not lesson.get("bites") or lesson["bites"][-1]["id"] != "cleared":
            warnings.append("%s: last card is not 'cleared'" % lid)
    names = action_names(all_lessons)
    if real is not None:
        for n in names:
            if n not in real:
                err("actions", "not a Krita action: %r" % n)
    for w in warnings:
        print("WARN ", w)
    for e in errors:
        print("ERROR", e)
    n_bites = sum(len(l.get("bites", [])) for l in all_lessons)
    print("%d lessons, %d cards, %d action names%s, %d errors" % (
        len(all_lessons), n_bites, len(names), " (checked against Krita)" if real else "", len(errors)))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
