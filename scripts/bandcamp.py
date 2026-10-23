"""Find each artist's Bandcamp page: scripts/bandcamp.tsv (artist, url) and public/bandcamp.js.

Bandcamp's own search is behind a bot check, so this uses open sources:
1. Wikidata (property P3283, "Bandcamp profile ID"), one query for all artists;
2. MusicBrainz artist URL relationships, for artists not found on Wikidata;
3. the usual address (artistname.bandcamp.com), kept only if the page shows
   the same artist name and a Quebec location.

Rows already in bandcamp.tsv are kept, so hand corrections survive a rerun;
a "-" instead of a URL marks an artist with no usable page.
Usage: python3 -u scripts/bandcamp.py
"""
import json
import pathlib
import re
import time
import unicodedata
import urllib.parse
import urllib.request

from build_catalog import norm

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "bandcamp.tsv"
UA = {"User-Agent": "MusiQuizQC/1.0 (https://musiquizqc.com)"}
QUEBEC = re.compile(r"qu[eé]bec|montr[eé]al|canada|gatineau|sherbrooke|saguenay|laval|longueuil|trois-rivi", re.I)


def get_json(url, data=None):
    req = urllib.request.Request(url, data=data, headers={**UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def catalog_artists():
    songs = json.loads(re.search(r"window\.SONGS = (.*);", (ROOT / "public" / "songs.js").read_text(), re.S)[1])
    return sorted({s["artist"] for s in songs})


def from_wikidata(artists):
    values = " ".join('"%s"@fr "%s"@en' % (a.replace('"', '\\"'), a.replace('"', '\\"')) for a in artists)
    query = f"""SELECT ?label ?bc WHERE {{
      VALUES ?label {{ {values} }}
      ?item rdfs:label ?label ; wdt:P3283 ?bc .
    }}"""
    data = get_json("https://query.wikidata.org/sparql",
                    urllib.parse.urlencode({"query": query, "format": "json"}).encode())
    found = {}
    for b in data["results"]["bindings"]:
        slug = b["bc"]["value"]
        if slug.isdigit():  # numeric IDs point to releases, not artist pages
            continue
        # Prefer the shortest slug when an artist has several (main page over EP pages).
        if b["label"]["value"] not in found or len(slug) < len(found[b["label"]["value"]]):
            found[b["label"]["value"]] = slug
    return {a: f"https://{slug}.bandcamp.com" for a, slug in found.items()}


def from_musicbrainz(artist):
    q = urllib.parse.urlencode({"query": f'artist:"{artist}"', "fmt": "json", "limit": 5})
    res = get_json(f"https://musicbrainz.org/ws/2/artist/?{q}")
    time.sleep(1.1)  # MusicBrainz asks for at most one request per second
    want = norm(artist).replace(" ", "")
    for a in res.get("artists", []):
        if norm(a.get("name", "")).replace(" ", "") != want:
            continue
        where = " ".join(filter(None, [a.get("country"), (a.get("area") or {}).get("name"), (a.get("begin-area") or {}).get("name")]))
        if not QUEBEC.search(where) and a.get("country") != "CA":
            continue
        rels = get_json(f"https://musicbrainz.org/ws/2/artist/{a['id']}?inc=url-rels&fmt=json")
        time.sleep(1.1)
        for r in rels.get("relations", []):
            url = r.get("url", {}).get("resource", "")
            m = re.match(r"https?://([a-z0-9-]+)\.bandcamp\.com/?$", url)
            if m:
                return f"https://{m[1]}.bandcamp.com"
    return None


def slug_variants(artist):
    base = unicodedata.normalize("NFKD", artist.lower()).encode("ascii", "ignore").decode()
    words = re.findall(r"[a-z0-9]+", base)
    bare = words[1:] if words and words[0] in {"les", "le", "la"} and len(words) > 1 else words
    variants = ["".join(words), "-".join(words), "".join(bare)]
    variants += [variants[0] + suffix for suffix in ("music", "musique", "officiel")]
    return list(dict.fromkeys(v for v in variants if v))


def page_artist(url):
    """(band name, location) shown on a Bandcamp page, or None if the address is unused."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        final, html = r.geturl(), r.read().decode("utf-8", "replace")
    if "bandcamp.com/signup" in final:
        return None
    block = re.search(r'id="band-name-location".*?class="title">(.*?)<.*?class="location[^"]*">(.*?)<', html, re.S)
    return (block[1].strip(), block[2].strip()) if block else None


def from_guess(artist):
    want = norm(artist).replace(" ", "")
    for slug in slug_variants(artist):
        url = f"https://{slug}.bandcamp.com"
        try:
            found = page_artist(url)
        except Exception:
            found = None
        time.sleep(0.25)
        if found and norm(found[0]).replace(" ", "") == want and QUEBEC.search(found[1]):
            return url
    return None


def save(found):
    OUT.write_text("# artiste\turl Bandcamp (- = pas de page utilisable)\n" + "\n".join(f"{a}\t{found[a]}" for a in sorted(found)) + "\n")


def write_js():
    """public/bandcamp.js, the artist → Bandcamp page table loaded by the game."""
    rows = [l.split("\t")[:2] for l in OUT.read_text().splitlines() if l.strip() and not l.startswith("#")]
    rows = [(a, url) for a, url in rows if url.startswith("https://")]
    (ROOT / "public" / "bandcamp.js").write_text(
        "// Généré par scripts/bandcamp.py — ne pas éditer à la main.\n"
        "window.BANDCAMP = " + json.dumps(dict(rows), ensure_ascii=False, indent=1) + ";\n")


def main():
    """Look up only artists not yet in bandcamp.tsv (found pages and "-" are both kept)."""
    artists = catalog_artists()
    kept = {}
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                a, url = line.split("\t")[:2]
                kept[a] = url
    todo = [a for a in artists if a not in kept]
    print(f"{len(todo)} artiste(s) sans entrée Bandcamp", flush=True)
    found = dict(kept)
    wikidata = from_wikidata(todo) if todo else {}
    for artist in todo:
        url, searched = wikidata.get(artist), True
        if url:
            # Wikidata can match a namesake (a "Silence" from Slovenia): check the page's location.
            try:
                info = page_artist(url)
            except Exception:
                info = None
            if not (info and QUEBEC.search(info[1])):
                url = None
        if not url:
            try:
                url = from_musicbrainz(artist)
            except Exception as e:
                print(f"  {artist}: MusicBrainz indisponible ({e})", flush=True)
                searched = False  # on réessaiera la prochaine fois
                time.sleep(3)
        url = url or from_guess(artist)
        print(("✓ " if url else "· ") + artist + (f" → {url}" if url else ""), flush=True)
        if url or searched:
            found[artist] = url or "-"  # "-" : cherché sans résultat, on ne recherche plus
            save(found)  # au fur et à mesure : une interruption ne perd rien
    save(found)
    write_js()
    print(f"{sum(1 for v in found.values() if v.startswith('https'))} artistes avec une page Bandcamp → public/bandcamp.js")


if __name__ == "__main__":
    main()
