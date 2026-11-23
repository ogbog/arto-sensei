# SPDX-License-Identifier: MIT
"""Local-only progress: <Krita app data>/arto_sensei/progress.json. No network, ever."""
import json
import os
import time

from krita import Krita

from . import devlog


class Progress(object):
    def __init__(self):
        base = Krita.instance().getAppDataLocation()
        self.dir = os.path.join(base, "arto_sensei")
        self.path = os.path.join(self.dir, "progress.json")
        self.data = {"done": {}, "calibration": {}, "dojo": {}, "last": None}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data.update(json.load(f))
        except FileNotFoundError:
            pass
        except Exception:
            devlog.log_exc("progress load")

    def save(self):
        try:
            os.makedirs(self.dir, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            devlog.log_exc("progress save")

    def mark(self, lesson_id, bite_id):
        self.data["done"]["%s/%s" % (lesson_id, bite_id)] = time.strftime("%Y-%m-%d %H:%M")
        self.data["last"] = [lesson_id, bite_id]
        self.save()

    def is_done(self, lesson_id, bite_id):
        return ("%s/%s" % (lesson_id, bite_id)) in self.data["done"]

    def dojo_best(self, drill, score=None):
        d = self.data.setdefault("dojo", {}).setdefault(drill, {"best": 0, "best_streak": 0})
        if score is not None and score > d["best"]:
            d["best"] = round(score)
            self.save()
        return d
