"""Match each song in catalog.tsv to a Deezer track and write public/songs.js.

Deezer preview links expire, so only the track id is stored; the game fetches
a fresh preview link at play time.

Usage: python3 scripts/build_catalog.py
"""
import json
import pathlib
import re
import time
import unicodedata
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "catalog.tsv"
OUT = ROOT / "public" / "songs.js"
CACHE = ROOT / "scripts" / ".deezer-cache.json"

BAD = re.compile(r"\b(live|remix|version|karaoke|instrumental|acoustique|acoustic|edit|reprise|en direct|osm|symphonique|demo)\b")


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("œ", "oe").replace("’", "'")
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"^(les|le|la|the) ", "", s.strip())


def search(term, cache):
    if term in cache:
        return cache[term]
    q = urllib.parse.urlencode({"q": term, "limit": 50})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(f"https://api.deezer.com/search?{q}", timeout=20) as r:
                data = json.load(r)
                if "error" in data:
                    raise RuntimeError(data["error"])
                cache[term] = data["data"]
                CACHE.write_text(json.dumps(cache))
                time.sleep(0.15)
                return cache[term]
        except Exception as e:  # rate limiting: back off and retry
            print(f"  retry {attempt + 1} ({e})")
            time.sleep(6)
    return []


def pick(results, title, artist):
    # Artist names differ in punctuation on Deezer ("Les BB", "Martine St. Clair").
    nt, na = norm(title), norm(artist).replace(" ", "")
    best, best_score = None, -1
    for r in results:
        if not r.get("preview") or not r.get("readable", True):
            continue
        rt, ra = norm(r.get("title", "")), norm(r["artist"]["name"]).replace(" ", "")
        if na not in ra:
            continue
        if rt != nt and not rt.startswith(nt + " "):
            continue
        raw = (r.get("title", "") + " " + r["album"]["title"]).lower()
        score = 10 if rt == nt else 5
        if BAD.search(norm(raw)):
            score -= 8
        if "feat" in r.get("title", "").lower():
            score -= 2
        if "best of" in raw or "greatest" in raw or "compil" in raw:
            score -= 1
        if score > best_score:
            best, best_score = r, score
    return best


def top_tracks():
    """Tracks from discover.py's artist top lists, keyed by normalized artist.

    Deezer search misses some collabs and new releases that still show up in
    an artist's top tracks, so those are a fallback.
    """
    path = ROOT / "scripts" / ".deezer-discover-cache.json"
    if not path.exists():
        return {}
    by_artist = {}
    for url, data in json.loads(path.read_text()).items():
        if "/search/artist?" in url:
            for a in data.get("data", []):
                by_artist.setdefault(a["id"], norm(a["name"]).replace(" ", ""))
    tops = {}
    for url, data in json.loads(path.read_text()).items():
        if "/top?limit=" in url:
            artist_id = int(url.split("/artist/")[1].split("/")[0])
            name = by_artist.get(artist_id)
            if name:
                tops.setdefault(name, []).extend(data.get("data", []))
    return tops


def main():
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    tops = top_tracks()
    by_id = {t["id"]: t for tracks in tops.values() for t in tracks}
    from discover import ARTISTS
    quebec = {norm(a).replace(" ", "") for a in ARTISTS.replace("\n", "|").split("|") if a.strip()}
    quebec |= {norm(l.split("\t")[1]).replace(" ", "") for l in SRC.read_text().splitlines()
               if l.strip() and not l.startswith("#")}
    songs, misses = [], []
    for line in SRC.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        # Optional 6th column: the title as Deezer spells it, used only for matching.
        title, artist, year, genre, tier, *alias = line.split("\t")
        match = alias[0] if alias and alias[0] else title
        # Optional 7th column: a Deezer track id already vetted by expand.py.
        r = by_id.get(int(alias[1])) if len(alias) > 1 and alias[1] else None
        r = r or pick(search(f"{artist} {match}", cache), match, artist)
        if not r:
            nt = norm(match)
            na = norm(artist).replace(" ", "")
            # The track's main artist must be a Quebec artist: top lists also hold
            # songs where ours is only featured, sometimes by a French act.
            r = next((t for t in tops.get(na, [])
                      if t.get("preview") and norm(t["title"]) == nt
                      and norm(t["artist"]["name"]).replace(" ", "") in quebec), None)
        print(("✓ " if r else "✗ ") + f"{title} — {artist}", flush=True)
        if not r:
            misses.append(f"{title} — {artist}")
            continue
        songs.append({
            "id": r["id"],
            "title": title,
            "artist": artist,
            "year": int(year),
            "genre": genre,
            "tier": int(tier),
            "art": r["album"].get("cover_medium", ""),
            "link": r.get("link", ""),
        })
    CACHE.write_text(json.dumps(cache))
    OUT.write_text("// Généré par scripts/build_catalog.py — ne pas éditer à la main.\n"
                   "window.SONGS = " + json.dumps(songs, ensure_ascii=False, indent=1) + ";\n")
    print(f"{len(songs)} chansons écrites dans {OUT.relative_to(ROOT)}")
    if misses:
        print(f"{len(misses)} introuvables:\n  " + "\n  ".join(misses))


if __name__ == "__main__":
    main()
