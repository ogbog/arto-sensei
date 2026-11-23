"""Build dist/arto-sensei-<version>.zip for Krita's Tools > Scripts > Import Python Plugin from File.

The zip holds arto_sensei.desktop and arto_sensei/ at its root, exactly as pykrita expects.
"""
import os
import re
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    src = open(os.path.join(ROOT, "arto_sensei", "docker.py"), encoding="utf-8").read()
    version = re.search(r'VERSION = "([^"]+)"', src).group(1)
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    out = os.path.join(ROOT, "dist", "arto-sensei-%s.zip" % version)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(ROOT, "arto_sensei.desktop"), "arto_sensei.desktop")
        for base, dirs, files in os.walk(os.path.join(ROOT, "arto_sensei")):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "_dev")]
            for f in files:
                if f.endswith(".pyc"):
                    continue
                full = os.path.join(base, f)
                z.write(full, os.path.relpath(full, ROOT))
        for f in ("LICENSE", "CONTENT-LICENSE.md", "ATTRIBUTION.md"):
            z.write(os.path.join(ROOT, f), "arto_sensei/" + f)
    print(out)


if __name__ == "__main__":
    main()
