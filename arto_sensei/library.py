# SPDX-License-Identifier: MIT
"""Public-domain master library for sight-size copies and timed figure drawing.

Images live in <Krita app data>/arto_sensei/library/<set>/ with a credits.json.
Any images a teacher drops into a set folder (or a new folder) are used too.

The downloader searches Wikimedia Commons and keeps ONLY files whose license
metadata says public domain or CC0. It runs in a background thread, never
touches the GUI from that thread, and paces requests politely.
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

from krita import Krita

from . import devlog
from .qt import QtCore, Signal

API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "ArtoSensei/1.0 (Krita teaching plugin; Seriously Open Games OER project)"
EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp")
FREE = re.compile(r"public domain|^pd\b|^pd-|cc0|cc-zero", re.I)

# key: (label, Commons search). Searches are deliberately plain; the license filter does the vetting.
SETS = {
    "bargue": ("Bargue drawing course plates", 'Bargue "Cours de dessin"'),
    "bouguereau": ("Bouguereau drawings and studies", "Bouguereau drawing study"),
    "sargent": ("John Singer Sargent charcoal portraits", "John Singer Sargent charcoal drawing"),
    "leyendecker": ("J. C. Leyendecker (published before 1929)", "Leyendecker illustration"),
    "velazquez": ("Diego Velazquez", "Velazquez portrait painting"),
    "goya": ("Francisco Goya drawings", "Goya drawing"),
    "muybridge": ("Eadweard Muybridge motion studies", "Muybridge Animal Locomotion plate"),
    "william_hogarth": ("William Hogarth (the 1700s engraver)", "William Hogarth engraving"),
}


def root():
    p = os.path.join(Krita.instance().getAppDataLocation(), "arto_sensei", "library")
    os.makedirs(p, exist_ok=True)
    return p


def set_names():
    """Known sets plus any folder a teacher added by hand."""
    names = list(SETS)
    try:
        for d in sorted(os.listdir(root())):
            if d not in names and os.path.isdir(os.path.join(root(), d)):
                names.append(d)
    except Exception:
        pass
    return names


def label(key):
    return SETS.get(key, (key.replace("_", " ").title(), ""))[0]


def images(key=None):
    keys = [key] if key and key != "any" else set_names()
    out = []
    for k in keys:
        folder = os.path.join(root(), k)
        if not os.path.isdir(folder):
            continue
        for f in sorted(os.listdir(folder)):
            if f.lower().endswith(EXTS):
                out.append(os.path.join(folder, f))
    return out


def credit_for(path):
    try:
        with open(os.path.join(os.path.dirname(path), "credits.json"), "r", encoding="utf-8") as f:
            return json.load(f).get(os.path.basename(path))
    except Exception:
        return None


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def _strip(html):
    return re.sub(r"<[^>]+>", "", html or "").strip()


def _safe_name(title):
    base = re.sub(r"^File:", "", title)
    base = re.sub(r"[^\w.\- ]+", "_", base).strip()
    return base[:120]


class Downloader(QtCore.QThread):
    progress = Signal(str)
    finished_set = Signal(str, int)

    def __init__(self, key, limit=24, parent=None):
        super().__init__(parent)
        self.key, self.limit = key, limit
        self.folder = os.path.join(root(), key)

    def run(self):
        got = 0
        try:
            os.makedirs(self.folder, exist_ok=True)
            cred_path = os.path.join(self.folder, "credits.json")
            credits = {}
            if os.path.exists(cred_path):
                with open(cred_path, "r", encoding="utf-8") as f:
                    credits = json.load(f)
            q = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": "6",
                 "gsrsearch": SETS[self.key][1], "gsrlimit": "50", "prop": "imageinfo",
                 "iiprop": "url|extmetadata|mime|size", "iiurlwidth": "1600"}
            self.progress.emit("Searching Wikimedia Commons...")
            data = json.loads(_get(API + "?" + urllib.parse.urlencode(q)).decode("utf-8"))
            pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
            for page in pages:
                if got >= self.limit or self.isInterruptionRequested():
                    break
                info = (page.get("imageinfo") or [{}])[0]
                meta = info.get("extmetadata", {})
                lic = (meta.get("LicenseShortName", {}).get("value") or meta.get("License", {}).get("value") or "")
                if not FREE.search(lic.strip()):
                    continue
                if info.get("mime") not in ("image/jpeg", "image/png", "image/tiff"):
                    continue
                if (info.get("width") or 0) < 600:
                    continue
                url = info.get("thumburl") or info.get("url")
                name = _safe_name(page.get("title", "image"))
                if not name.lower().endswith((".jpg", ".jpeg", ".png")):
                    name += ".jpg"
                dest = os.path.join(self.folder, name)
                if not os.path.exists(dest):
                    self.progress.emit("Downloading %d: %s" % (got + 1, name[:50]))
                    blob = _get(url)
                    with open(dest, "wb") as f:
                        f.write(blob)
                    time.sleep(1.0)  # be a polite guest on Commons
                credits[name] = {
                    "title": page.get("title"),
                    "artist": _strip(meta.get("Artist", {}).get("value")),
                    "license": lic,
                    "source": info.get("descriptionurl"),
                }
                got += 1
            with open(cred_path, "w", encoding="utf-8") as f:
                json.dump(credits, f, indent=2, ensure_ascii=False)
            self.progress.emit("%s: %d public-domain images ready." % (label(self.key), got))
        except Exception as e:
            devlog.log_exc("library download %s" % self.key)
            self.progress.emit("Download stopped: %s" % e)
        self.finished_set.emit(self.key, got)
