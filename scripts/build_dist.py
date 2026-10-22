"""Copy public/ to dist/ for static hosting, with cache-busted asset links.

Locally, server.py stamps each CSS/JS link with the file's modification time.
A static host can't do that, so this stamps them with a content hash instead:
visitors always get the latest files after a deploy.

Usage: python3 scripts/build_dist.py
"""
import hashlib
import pathlib
import re
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "public"
OUT = ROOT / "dist"


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    shutil.copytree(SRC, OUT, ignore=shutil.ignore_patterns("_*", ".*"))

    def stamp(m):
        digest = hashlib.sha256((OUT / m[2]).read_bytes()).hexdigest()[:10]
        return f'{m[1]}="{m[2]}?v={digest}"'

    index = OUT / "index.html"
    index.write_text(re.sub(r'(href|src)="([\w.-]+\.(?:css|js))(?:\?v=\w+)?"', stamp, index.read_text()))
    print(f"dist/ prêt : {sum(1 for _ in OUT.iterdir())} fichiers")


if __name__ == "__main__":
    main()
