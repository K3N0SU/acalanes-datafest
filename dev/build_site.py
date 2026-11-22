"""Assemble the deployable site in dist/ without Node: index.html + src/ + everything in public/ at the root.
This is the same layout Vite produces, so GitHub Pages (or any static host) can serve dist/ as is.

  /usr/local/bin/python3 dev/build_site.py
  (then publish dist/, e.g. with the GitHub Pages "upload artifact" action)

"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
SKIP = set()


def main():
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    shutil.copy2(ROOT / "index.html", DIST / "index.html")
    shutil.copytree(ROOT / "src", DIST / "src", ignore=lambda d, names: [n for n in names if n in SKIP])
    for item in (ROOT / "public").iterdir():
        target = DIST / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns(".*", "*.tmp"))
        elif not item.name.startswith("."):
            shutil.copy2(item, target)
    (DIST / ".nojekyll").touch()  # GitHub Pages: serve files as they are
    size = sum(p.stat().st_size for p in DIST.rglob("*") if p.is_file())
    print(f"dist/ ready: {sum(1 for p in DIST.rglob('*') if p.is_file())} files, {size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
