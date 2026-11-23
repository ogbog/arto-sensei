# SPDX-License-Identifier: MIT
"""Dev breadcrumbs: _dev/log.txt and _dev/selftest.json beside the plugin.

These exist so an agent (or Oscar) can read what the live Krita actually
exposes without guessing. Delete _dev/ any time; it is rebuilt on launch.
"""
import json
import os
import sys
import time
import traceback

DEV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_dev")
_facts = {}


def _ensure():
    try:
        os.makedirs(DEV_DIR, exist_ok=True)
    except Exception:
        pass


def log(*parts):
    _ensure()
    try:
        with open(os.path.join(DEV_DIR, "log.txt"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + " ".join(str(p) for p in parts) + "\n")
    except Exception:
        pass


def log_exc(where):
    log("ERROR in", where, "\n" + traceback.format_exc())


def safe(fn):
    """Wrap anything Qt calls back into (slots, timers, paintEvent).

    PyQt5 turns an uncaught exception in a slot or virtual into qFatal(),
    which kills Krita. Log it instead and carry on.
    """
    import functools

    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except Exception:
            log_exc(getattr(fn, "__qualname__", str(fn)))
            return None
    return wrapper


def fact(key, value):
    """Record a verified API fact and rewrite selftest.json."""
    _facts[key] = value
    _ensure()
    try:
        with open(os.path.join(DEV_DIR, "selftest.json"), "w", encoding="utf-8") as f:
            json.dump(_facts, f, indent=2, default=str)
    except Exception:
        pass


def boot_facts():
    from .qt import KRITA_VERSION, QT6, QtCore
    from krita import Krita
    fact("time", time.strftime("%Y-%m-%d %H:%M:%S"))
    fact("krita_version", KRITA_VERSION)
    fact("qt6", QT6)
    fact("qt_version", QtCore.qVersion())
    fact("pyqt_version", QtCore.PYQT_VERSION_STR)
    fact("python", sys.version.split()[0])
    try:
        fact("app_data", Krita.instance().getAppDataLocation())
    except Exception as e:
        fact("app_data", "ERR %s" % e)
