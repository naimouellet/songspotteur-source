"""Give every song in public/songs.js its Apple Music clip.

For each song: Deezer track → ISRC (the recording's unique code) → the same
recording on Apple Music. Adds `isrc`, `apple` (Apple song id) and `preview`
(Apple's 30 s AAC clip, a stable link). Songs Apple doesn't have keep playing
from Deezer. Safe to rerun: songs that already have an Apple clip are skipped.

Usage: python3 -u scripts/apple_migrate.py
"""
import json
import pathlib
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import apple_music

ROOT = pathlib.Path(__file__).resolve().parent.parent
SONGS = ROOT / "public" / "songs.js"
COMPILATION = re.compile(r"compil|best of|greatest|hits|anthologie|essentiel|collection|nova tunes|vol\.|volume|karaok", re.I)

lock = threading.Lock()
last = [0.0]


def deezer_isrc(deezer_id):
    for attempt in range(4):
        with lock:  # Deezer allows ~50 requests / 5 s
            wait = last[0] + 0.12 - time.time()
            if wait > 0:
                time.sleep(wait)
            last[0] = time.time()
        try:
            with urllib.request.urlopen(f"https://api.deezer.com/track/{deezer_id}", timeout=20) as r:
                data = json.load(r)
            if "error" in data:
                raise RuntimeError(data["error"])
            return data.get("isrc")
        except Exception:
            time.sleep(3 * (attempt + 1))
    return None


def best_release(candidates):
    """Same recording on several releases: prefer the original over compilations, then the earliest."""
    def rank(song):
        a = song["attributes"]
        return (bool(COMPILATION.search(a.get("albumName", ""))), a.get("releaseDate", "9999"))
    usable = [s for s in candidates if s["attributes"].get("previews")]
    return min(usable, key=rank) if usable else None


def load():
    return json.loads(re.search(r"window\.SONGS = (.*);", SONGS.read_text(), re.S)[1])


def save(songs):
    SONGS.write_text("// Généré par scripts/build_catalog.py — ne pas éditer à la main.\n"
                     "window.SONGS = " + json.dumps(songs, ensure_ascii=False, indent=1) + ";\n")


def main():
    songs = load()
    todo = [s for s in songs if not s.get("preview")]
    print(f"{len(songs)} chansons, {len(todo)} sans extrait Apple", flush=True)

    need_isrc = [s for s in todo if not s.get("isrc") and s.get("deezer", s["id"])]
    with ThreadPoolExecutor(6) as pool:
        for song, isrc in zip(need_isrc, pool.map(lambda s: deezer_isrc(s.get("deezer", s["id"])), need_isrc)):
            if isrc:
                song["isrc"] = isrc
    print(f"ISRC trouvés : {sum(1 for s in todo if s.get('isrc'))}/{len(todo)}", flush=True)

    isrcs = sorted({s["isrc"] for s in todo if s.get("isrc")})
    found = apple_music.songs_by_isrc(isrcs)
    matched = 0
    for song in todo:
        best = best_release(found.get(song.get("isrc"), []))
        if best:
            song["apple"] = best["id"]
            song["preview"] = best["attributes"]["previews"][0]["url"]
            matched += 1
    save(songs)
    print(f"Extraits Apple ajoutés : {matched}/{len(todo)} ; les autres restent sur Deezer.")


if __name__ == "__main__":
    main()
