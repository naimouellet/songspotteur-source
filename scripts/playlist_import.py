"""Add every song of an Apple Music playlist that the game doesn't have yet.

Default source: TOP QUEB (Samuel Belley). For each new song, the row added to
catalog.tsv carries its Apple song id (8th column) and, when Deezer has the
same recording (same ISRC), its Deezer id as a fallback (7th column). Then run
build_catalog.py, which fetches Apple's clip and cover for those rows.

Prints a report, including songs that clash with blocklist.txt or
artist_limits.tsv: they are added anyway (the playlist is the source of truth)
so they can be reviewed by hand.

Usage: python3 -u scripts/playlist_import.py [playlist_id] [--dry-run]
"""
import json
import pathlib
import re
import sys
import time
import urllib.request

import apple_music
from build_catalog import norm

ROOT = pathlib.Path(__file__).resolve().parent.parent
CATALOG = ROOT / "scripts" / "catalog.tsv"
SONGS = ROOT / "public" / "songs.js"
PLAYLIST = "pl.u-11zBvGYC8MG8vqP"  # TOP QUEB
FEAT = re.compile(r"\s*[\(\[](feat\.?|featuring|avec|with)\b[^\)\]]*[\)\]]", re.I)
GENRES = [("hip-hop", "Rap"), ("rap", "Rap"), ("rock", "Rock"), ("alternative", "Rock"), ("metal", "Rock"),
          ("punk", "Rock"), ("singer/songwriter", "Chanson"), ("chanson", "Chanson"), ("folk", "Folk & trad"),
          ("country", "Folk & trad")]


def squash(s):
    return norm(s).replace(" ", "")


def playlist_tracks(pid):
    tracks, path, params = [], f"/catalog/{apple_music.STOREFRONT}/playlists/{pid}/tracks", {"limit": 100}
    while path:
        data = apple_music.get(path, **params)
        tracks += [t for t in data["data"] if t["type"] == "songs"]
        nxt = data.get("next")
        path, params = (nxt.replace("/v1", "", 1), {}) if nxt else (None, {})
    return tracks


def main_artists(ids):
    """{apple song id: main artist name}, from Apple's artist relationships."""
    out = {}
    for i in range(0, len(ids), 100):
        data = apple_music.get(f"/catalog/{apple_music.STOREFRONT}/songs", ids=",".join(ids[i:i + 100]), include="artists")
        for song in data["data"]:
            artists = song.get("relationships", {}).get("artists", {}).get("data", [])
            name = artists[0].get("attributes", {}).get("name") if artists else None
            out[song["id"]] = name or song["attributes"]["artistName"]
    return out


def deezer_by_isrc(isrc):
    try:
        with urllib.request.urlopen(f"https://api.deezer.com/track/isrc:{isrc}", timeout=20) as r:
            data = json.load(r)
        time.sleep(0.12)
        return data.get("id") if "error" not in data and data.get("readable", True) else None
    except Exception:
        return None


def genre_of(names):
    joined = " ".join(names).lower()
    return next((label for key, label in GENRES if key in joined), "Pop")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    pid = args[0] if args else PLAYLIST

    songs = json.loads(re.search(r"window\.SONGS = (.*);", SONGS.read_text(), re.S)[1])
    rows = [l.split("\t") for l in CATALOG.read_text().splitlines() if l.strip() and not l.startswith("#")]
    known_isrc = {s["isrc"] for s in songs if s.get("isrc")}
    known_key = {norm(r[0]) + "|" + squash(r[1]) for r in rows}
    known_artist = {squash(r[1]): r[1] for r in rows}  # keep the catalog's spelling of an artist
    blocked = {norm(l) for l in (ROOT / "scripts" / "blocklist.txt").read_text().splitlines() if l.strip() and not l.startswith("#")}
    limits = {squash(l.split("\t")[0]): int(l.split("\t")[1]) for l in (ROOT / "scripts" / "artist_limits.tsv").read_text().splitlines()
              if l.strip() and not l.startswith("#")}

    tracks = playlist_tracks(pid)
    print(f"Playlist : {len(tracks)} pistes", flush=True)
    seen, fresh = set(), []
    for t in tracks:
        a = t["attributes"]
        if a.get("isrc") in known_isrc or a.get("isrc") in seen or not a.get("previews"):
            continue
        seen.add(a.get("isrc"))
        fresh.append(t)

    artists = main_artists([t["id"] for t in fresh])
    new_rows, clashes, skipped_dupes = [], [], 0
    for t in fresh:
        a = t["attributes"]
        title = FEAT.sub("", a["name"]).strip()
        artist = artists.get(t["id"], a["artistName"])
        artist = known_artist.get(squash(artist), artist)
        k = norm(title) + "|" + squash(artist)
        if k in known_key:
            skipped_dupes += 1  # same song already in the game, under another release
            continue
        known_key.add(k)
        if norm(title) in blocked:
            clashes.append(f"{title} — {artist} (titre dans blocklist.txt)")
        elif limits.get(squash(artist)) is not None:
            clashes.append(f"{title} — {artist} (artiste limité à {limits[squash(artist)]} dans artist_limits.tsv)")
        deezer = deezer_by_isrc(a["isrc"])
        year = (a.get("releaseDate") or "0000")[:4]
        new_rows.append([title, artist, year, genre_of(a.get("genreNames", [])), "3", "", str(deezer or ""), t["id"]])

    print(f"Déjà dans le jeu : {len(tracks) - len(fresh) + skipped_dupes} (dont {skipped_dupes} sous une autre version)")
    print(f"Nouvelles chansons : {len(new_rows)}")
    new_artists = sorted({r[1] for r in new_rows if squash(r[1]) not in known_artist})
    print(f"Nouveaux artistes ({len(new_artists)}) : {', '.join(new_artists)}")
    if clashes:
        print(f"À revoir ({len(clashes)}) :\n  " + "\n  ".join(clashes))
    if not dry and new_rows:
        with CATALOG.open("a") as f:
            f.write("\n".join("\t".join(r) for r in new_rows) + "\n")
        print(f"{len(new_rows)} lignes ajoutées à {CATALOG.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
