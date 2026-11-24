# SPDX-License-Identifier: MIT
"""Public-domain master library for sight-size copies and timed figure drawing.

Images live in <Krita app data>/arto_sensei/library/<set>/ with a credits.json and
cached thumbnails in .thumbs/. Any images a teacher drops into a set folder (or a
new folder) are used too.

Sources, both filtered to public domain or CC0 only:
  * Wikimedia Commons (always). Standard 1280 px thumbnails, a policy-compliant
    User-Agent, polite pacing and Retry-After backoff, or Commons answers 429.
  * Openverse (museums such as the Met, Smithsonian, Rijksmuseum), when the
    student already connected an Openverse account in Photobash CC: we reuse
    those stored credentials, the same QSettings Photobash CC writes.

Downloads run in a background thread and never touch the GUI from it.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from krita import Krita

from . import devlog
from .qt import QtCore, QtGui, Signal, E, Qt

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
OPENVERSE = "https://api.openverse.org/v1"
# Wikimedia UA policy wants a contact URL or email; compliant agents get a higher rate limit.
USER_AGENT = "ArtoSensei/1.1.0 (https://github.com/ogbog/arto-sensei; Krita teaching plugin) Python-urllib"
# Commons only serves these thumbnail widths cheaply; anything else is strictly rate limited (HTTP 429).
THUMB_WIDTH = "1280"
PACE_S = 2.0
MAX_RETRIES = 3
MAX_BYTES = 25 * 1024 * 1024
EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp")
FREE = re.compile(r"public domain|^pd\b|^pd-|pdm|cc0|cc-zero", re.I)
THUMB_PX = 112

# key: (label, [searches]). Pruned to artists whose work can actually be public domain:
# dead long enough, and (for US work) published before 1931. Living artists, comics,
# and mid-century work are left out because Commons and Openverse can't legally offer them.
SETS = {
    "bargue": ("Bargue drawing course plates", [
        'Bargue "Cours de dessin"', "Charles Bargue drawing plate"]),
    "drawings": ("Master drawings and engravings", [
        "Leonardo da Vinci drawing", "Michelangelo drawing study", "Albrecht Durer engraving",
        "Raphael drawing study", "Andrea del Verrocchio drawing", "Lucas Vorsterman engraving",
        "William Hogarth engraving", "Francisco Goya etching", "John Singer Sargent charcoal",
        "Bouguereau drawing study", "Gaetano Gandolfi drawing", "Aubrey Beardsley"]),
    "academic": ("Academic figure painters", [
        "William-Adolphe Bouguereau", "Jean-Leon Gerome", "Lawrence Alma-Tadema", "Jacques-Louis David",
        "Eugene Delacroix", "Ernest Meissonier", "Guillaume Seignac", "Luis Ricardo Falero",
        "Georgios Jakobides", "Edmund Blair Leighton", "Arthur Hacker", "Juana Romani",
        "Gustave Jacquet", "Leon Maxime Faivre", "Josep Maria Tamburini", "Eugene Hillemacher",
        "Elizabeth Jane Gardner", "Victor Gabriel Gilbert", "Gyula Benczur", "Alexander Rothaug",
        "Vittorio Matteo Corcos", "Ludwig Deutsch", "Gustavo Simoni", "Antoni Fabres",
        "Claudio Rinaldi"]),
    "portraits": ("Portrait painters, 1800s to 1930", [
        "John Singer Sargent portrait", "Anders Zorn", "Joaquin Sorolla", "Giovanni Boldini",
        "Cecilia Beaux", "Mary Cassatt", "Philip de Laszlo", "William Merritt Chase", "Robert Henri",
        "William Orpen", "Ilya Repin", "Peder Severin Kroyer", "Albert Edelfelt", "Franz von Lenbach",
        "Carl Schuch", "Henry Ossawa Tanner", "Raja Ravi Varma", "Charles Sprague Pearce"]),
    "old_masters": ("Old masters", [
        "Rembrandt", "Frans Hals", "Peter Paul Rubens", "Caravaggio", "Johannes Vermeer",
        "Diego Velazquez", "Titian", "Tintoretto", "Giorgione", "Raphael painting", "Anthony van Dyck",
        "Bronzino", "Domenico Fetti", "Giorgio Vasari", "Rosalba Carriera", "Elisabeth Vigee Le Brun",
        "Adelaide Labille-Guiard", "Thomas Gainsborough", "Joshua Reynolds", "John Singleton Copley",
        "Canaletto", "Anne Vallayer-Coster", "Willem van Aelst", "William Gouw Ferguson"]),
    "illustrators": ("Golden Age illustrators (published before 1931)", [
        "Howard Pyle", "N. C. Wyeth", "J. C. Leyendecker", "Maxfield Parrish", "Arthur Rackham",
        "Franklin Booth", "Frederic Remington", "Harvey Dunn", "Dean Cornwell",
        "Elizabeth Shippen Green", "Bernard Boutet de Monvel"]),
    "landscapes": ("Landscapes and seascapes", [
        "Frederic Edwin Church", "Albert Bierstadt", "Thomas Cole", "Asher Brown Durand", "George Inness",
        "Martin Johnson Heade", "William Trost Richards", "Edward Moran", "Ivan Shishkin", "Isaac Levitan",
        "Ivan Aivazovsky", "Lev Lagorio", "Hans Gude", "Carl Friedrich Lessing", "Caspar David Friedrich",
        "J. M. W. Turner", "Peder Monsted", "Sydney Laurence", "Emilio Sanchez-Perrier", "Willem Roelofs",
        "William Wendt", "Francois Diday", "Robert S. Duncanson", "Maynard Dixon", "Winslow Homer"]),
    "naturalism": ("Naturalism and genre scenes", [
        "Stanhope Forbes", "Elizabeth Forbes", "Henry Herbert La Thangue", "Jules Bastien-Lepage",
        "Julien Dupre", "Jean-Eugene Buland", "Albert Anker", "Jakub Schikaneder", "Ludek Marold",
        "Konrad Krzyzanowski", "Eduard Charlemont", "Carl Kronberger", "William Gilbert Gaul",
        "Albert Chevallier Tayler", "Oscar Bjorck", "Juan Jose Garate", "Pierre Jan van der Ouderaa",
        "Andrei Schilder", "George Sherwood Hunter", "John Ottis Adams", "Gaetano Previati",
        "Alfred Wierusz-Kowalski", "Carl Frithjof Smith"]),
    "movements": ("Movements: Pre-Raphaelites, Peredvizhniki, Impressionists", [
        "Pre-Raphaelite painting", "Peredvizhniki painting", "Munich Secession painting",
        "Claude Monet", "Edouard Manet", "Georges Seurat", "Alexej von Jawlensky"]),
    "animals_motion": ("Animals and motion", [
        "Muybridge Animal Locomotion plate", "Muybridge Human Locomotion", "Rosa Bonheur",
        "Auguste Bonheur", "Frederic Remington horse", "Meissonier horse"]),
    "sculpture": ("Sculpture to draw from", [
        "Donatello sculpture", "Laocoon group", "Michelangelo sculpture", "Verrocchio sculpture"]),
}

# Set keys from 1.0.x whose folders may already hold images; still listed as teacher folders.
LEGACY = {"sargent": "John Singer Sargent charcoal portraits", "bouguereau": "Bouguereau drawings",
          "leyendecker": "J. C. Leyendecker", "velazquez": "Diego Velazquez", "goya": "Francisco Goya",
          "muybridge": "Eadweard Muybridge", "william_hogarth": "William Hogarth"}


def root():
    p = os.path.join(Krita.instance().getAppDataLocation(), "arto_sensei", "library")
    os.makedirs(p, exist_ok=True)
    return p


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60] or "artist"


def set_names():
    """Known sets plus any folder that exists (artist searches, legacy sets, teacher folders)."""
    names = list(SETS)
    try:
        for d in sorted(os.listdir(root())):
            if d not in names and not d.startswith(".") and os.path.isdir(os.path.join(root(), d)):
                names.append(d)
    except Exception:
        pass
    return names


def label(key):
    if key in SETS:
        return SETS[key][0]
    if key in LEGACY:
        return LEGACY[key]
    if key.startswith("artist_"):
        return "Artist: " + key[7:].replace("_", " ").title()
    return key.replace("_", " ").title()


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


def credit_line(path):
    """One-line attribution, Photobash CC style, ready for the clipboard."""
    c = credit_for(path)
    if not c:
        return os.path.basename(path)
    return " | ".join(x for x in (c.get("title", "").replace("File:", ""), c.get("artist"),
                                  c.get("license"), c.get("source")) if x)


def thumb_path(path):
    return os.path.join(os.path.dirname(path), ".thumbs", os.path.splitext(os.path.basename(path))[0] + ".png")


def make_thumb(path):
    """Small cached preview. Safe in a worker thread (QImage, not QPixmap)."""
    tp = thumb_path(path)
    if os.path.exists(tp):
        return tp
    img = QtGui.QImage(path)
    if img.isNull():
        return None
    os.makedirs(os.path.dirname(tp), exist_ok=True)
    img.scaled(THUMB_PX, THUMB_PX, E(Qt, "AspectRatioMode", "KeepAspectRatio"),
               E(Qt, "TransformationMode", "SmoothTransformation")).save(tp)
    return tp


# ------------------------------------------------------------------ network

def _get(url, on_wait=None, headers=None, limit=MAX_BYTES):
    """GET with polite retries: on HTTP 429/503 honor Retry-After (or back off) and try again."""
    for attempt in range(MAX_RETRIES + 1):
        h = {"User-Agent": USER_AGENT, "Api-User-Agent": USER_AGENT}
        h.update(headers or {})
        req = urllib.request.Request(url, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                data = r.read(limit + 1)
                if len(data) > limit:
                    raise ValueError("file larger than %d MB, skipped" % (limit // (1024 * 1024)))
                return data
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or attempt == MAX_RETRIES:
                raise
            try:
                wait = int(e.headers.get("Retry-After", "0"))
            except ValueError:
                wait = 0
            wait = max(wait, 15 * (attempt + 1))
            if on_wait:
                on_wait(wait)
            time.sleep(wait)


def openverse_token():
    """Reuse the Openverse login from Photobash CC (same QSettings keys). None if not connected."""
    try:
        s = QtCore.QSettings("PhotobashCC", "openverse")
        token = s.value("access_token", "", type=str)
        if token and time.time() < s.value("token_expiry", 0, type=float):
            return token
        cid, secret = s.value("client_id", "", type=str), s.value("client_secret", "", type=str)
        if not (cid and secret):
            return None
        body = urllib.parse.urlencode({"client_id": cid, "client_secret": secret,
                                       "grant_type": "client_credentials"}).encode("utf-8")
        req = urllib.request.Request(OPENVERSE + "/auth_tokens/token/", data=body, method="POST",
                                     headers={"User-Agent": USER_AGENT,
                                              "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        token = data.get("access_token")
        if token:
            s.setValue("access_token", token)
            s.setValue("token_expiry", time.time() + float(data.get("expires_in", 3600)) - 30)
        return token
    except Exception:
        devlog.log_exc("openverse token")
        return None


def _safe_name(title):
    base = re.sub(r"^File:", "", title or "image")
    base = re.sub(r"[^\w.\- ]+", "_", base).strip()
    return base[:110]


def _strip(html):
    return re.sub(r"<[^>]+>", "", html or "").strip()


class Downloader(QtCore.QThread):
    """Fill one library folder from a themed set or a single artist search."""
    progress = Signal(str)
    finished_set = Signal(str, int)

    def __init__(self, key, queries=None, limit=36, parent=None):
        super().__init__(parent)
        self.key, self.limit = key, limit
        self.queries = queries or SETS[key][1]
        self.folder = os.path.join(root(), key)
        self.credits, self.got = {}, 0

    # -- helpers
    def _wait(self, s):
        self.progress.emit("Commons asked us to slow down. Waiting %d s, then continuing..." % s)

    def _save(self, name, blob, credit):
        dest = os.path.join(self.folder, name)
        if not os.path.exists(dest):
            with open(dest, "wb") as f:
                f.write(blob)
        self.credits[name] = credit
        with open(os.path.join(self.folder, "credits.json"), "w", encoding="utf-8") as f:
            json.dump(self.credits, f, indent=2, ensure_ascii=False)  # save as we go
        try:
            make_thumb(dest)
        except Exception:
            pass
        self.got += 1

    def _commons(self, query, cap):
        q = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": "6",
             "gsrsearch": query + " filetype:bitmap", "gsrlimit": "30", "prop": "imageinfo",
             "iiprop": "url|extmetadata|mime|size", "iiurlwidth": THUMB_WIDTH}
        data = json.loads(_get(COMMONS_API + "?" + urllib.parse.urlencode(q), self._wait).decode("utf-8"))
        pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
        n = 0
        for page in pages:
            if n >= cap or self.got >= self.limit or self.isInterruptionRequested():
                break
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata", {})
            lic = (meta.get("LicenseShortName", {}).get("value") or meta.get("License", {}).get("value") or "")
            if not FREE.search(lic.strip()) or info.get("mime") not in ("image/jpeg", "image/png", "image/tiff"):
                continue
            if (info.get("width") or 0) < 600:
                continue
            name = _safe_name(page.get("title"))
            if not name.lower().endswith((".jpg", ".jpeg", ".png")):
                name += ".jpg"
            credit = {"title": page.get("title"), "artist": _strip(meta.get("Artist", {}).get("value")),
                      "license": lic, "source": info.get("descriptionurl"), "via": "Wikimedia Commons"}
            if not os.path.exists(os.path.join(self.folder, name)):
                self.progress.emit("Commons %d: %s" % (self.got + 1, name[:48]))
                blob = _get(info.get("thumburl") or info.get("url"), self._wait)
                time.sleep(PACE_S)
            else:
                blob = b""
            self._save(name, blob, credit)
            n += 1
        return n

    def _openverse(self, query, cap, token):
        params = {"q": query, "license": "pdm,cc0", "page_size": "20", "mature": "false"}
        data = json.loads(_get(OPENVERSE + "/images/?" + urllib.parse.urlencode(params), self._wait,
                               {"Authorization": "Bearer " + token, "Accept": "application/json"}).decode("utf-8"))
        n = 0
        for r in data.get("results", []):
            if n >= cap or self.got >= self.limit or self.isInterruptionRequested():
                break
            if (r.get("width") or 1000) < 600:
                continue
            ext = ".png" if (r.get("filetype") or "").lower() == "png" else ".jpg"
            name = _safe_name("%s - %s" % (r.get("creator") or "unknown", r.get("title") or r.get("id")))[:100] + ext
            lic = {"pdm": "Public domain (Public Domain Mark)", "cc0": "Public domain (CC0)"}.get(
                (r.get("license") or "").lower(), (r.get("license") or "").upper())
            credit = {"title": r.get("title"), "artist": r.get("creator"), "license": lic,
                      "source": r.get("foreign_landing_url"), "via": "Openverse (%s)" % r.get("source", "")}
            if not os.path.exists(os.path.join(self.folder, name)):
                self.progress.emit("Openverse %d: %s" % (self.got + 1, name[:48]))
                try:
                    blob = _get(r.get("url"), self._wait)
                except Exception as e:
                    devlog.log("openverse skip", r.get("url"), e)
                    continue
                time.sleep(PACE_S)
            else:
                blob = b""
            self._save(name, blob, credit)
            n += 1
        return n

    def run(self):
        try:
            os.makedirs(self.folder, exist_ok=True)
            cred_path = os.path.join(self.folder, "credits.json")
            if os.path.exists(cred_path):
                with open(cred_path, "r", encoding="utf-8") as f:
                    self.credits = json.load(f)
            token = openverse_token()
            per = max(2, -(-self.limit // max(1, len(self.queries))))  # ceil: spread across artists
            for q in self.queries:
                if self.got >= self.limit or self.isInterruptionRequested():
                    break
                self.progress.emit("Searching: %s" % q)
                n = self._commons(q, per)
                if token and n < per and self.got < self.limit:
                    try:
                        self._openverse(q, per - n, token)
                    except Exception as e:
                        devlog.log("openverse search failed", q, e)
            via = " (Commons + Openverse)" if token else " (Commons; connect Openverse in Photobash CC for museum collections)"
            self.progress.emit("%s: %d public-domain images ready%s." % (label(self.key), self.got, via))
        except Exception as e:
            devlog.log_exc("library download %s" % self.key)
            if "429" in str(e):
                self.progress.emit("Commons is busy (too many requests). Kept %d images; click Download again "
                                   "in a few minutes to resume." % self.got)
            else:
                self.progress.emit("Download stopped after %d images: %s" % (self.got, e))
        self.finished_set.emit(self.key, self.got)
