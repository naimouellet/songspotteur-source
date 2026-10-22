"""Propose new catalog rows from Deezer top tracks of Quebec artists.

Keeps French-titled tracks whose main artist is the Quebec artist, skips live,
remix and compilation releases, and writes scripts/expand.tsv in catalog
format (with the Deezer id as a 7th column) for review before appending.

Usage: python3 -u scripts/expand.py
"""
import json
import os
import pathlib
import re
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from build_catalog import BAD, norm
from discover import ARTISTS

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "scripts" / ".deezer-discover-cache.json"
OUT = ROOT / "scripts" / os.environ.get("EXPAND_OUT", "expand.tsv")
PER_ARTIST = int(os.environ.get("PER_ARTIST", 8))
MIN_YEAR = int(os.environ.get("MIN_YEAR", 0))

NEW_ARTISTS = """
LaF|Joe Rocca|Snail Kid|Izzy-S|Kaycyy|Lost|Mike Clay|
Fredz|Sara Dufour|Lydia Képinski|Philippe Brach|Saratoga|Rosie Valland|Marie-Annick Lépine|Antoine Corriveau|Philémon Cimon|Galaxie|
Hôtel Morphée|Pierre Kwenders|Félix Dyotte|Julien Sagot|Les Deuxluxes|Avec pas d'casque|Tire le coyote|Dany Placard|Bernard Adamus|
Keith Kouna|Philippe B|Pierre Flynn|Alexandre Désilets|Marc Déry|Zébulon|Les Denis Drolet|Gabrielle Destroismaisons|Maude Audet|
Arielle Soucy|Beau Nectar|Cachemire|Gab Paquet|Marilyne Léonard|Robert Robert|Hippie Hourrah|Les Shirley|Ponctuation|
Population II|VioleTT Pi|Alex Burger|Le Couleur|Qualité Motel|Mehdi Cayenne|Chloé Lacasse|Mara Tremblay|Michel Louvain|
Les Classels|Les Baronets|César et les Romains|Joël Denis|Michèle Richard|Pierre Lalonde|Donald Lautrec|Nicole Martin|
Johanne Blouin|Marie Carmen|Sylvain Lelièvre|Claude Léveillée|Pauline Julien|Monique Leyrac|Claude Gauthier|Jacques Michel|
Pierre Létourneau|Fabienne Thibeault|Luce Dufault|Marie Denise Pelletier|Nathalie Simard|René Simard|Jano Bergeron|Paul Daraîche|
La Chicane|Noir Silence|Vilain Pingouin|Groovy Aardvark|Rock et Belles Oreilles|Les Colocs|Daniel Bélanger|Jean Leloup|
Louis-Jean Cormier|Les Sœurs Boulay|2Frères|Roxane Bruneau|Émile Bilodeau|Jérôme 50|Bleu Jeans Bleu|Salebarbes|
Les Trois Accords|Kaïn|Les Cowboys Fringants|Mes Aïeux|Marc Dupré|Isabelle Boulay|Ginette Reno|Éric Lapointe|
Koriass|FouKi|Loud|Souldia|Rymz|Enima|Manu Militari|Alaclair Ensemble|White-B|Rowjay|Jay Scøtt|Sarahmée|
Lou-Adriane Cassidy|Ariane Roy|Les Louanges|Hubert Lenoir|Klô Pelgag|Pierre Lapointe|Patrice Michaud|Vincent Vallières|
Ariane Moffatt|Cœur de pirate|Marie-Mai|Charlotte Cardin|Corneille|Garou|Céline Dion|Diane Tell|Richard Desjardins|
Paul Piché|Michel Rivard|Beau Dommage|Harmonium|Robert Charlebois|Félix Leclerc|Gilles Vigneault|Jean-Pierre Ferland|
Claude Dubois|Diane Dufresne|Offenbach|Plume Latraverse|Marjo|Gerry Boulet|Les BB|Mitsou|Martine St. Clair|
Kevin Parent|Daniel Boucher|Dan Bigras|Lynda Lemay|Laurence Jalbert|France D'Amour|Sylvain Cossette|Bruno Pelletier|
Marie-Élaine Thibert|Annie Villeneuve|Les Vulgaires Machins|Karkwa|Malajube|Les Respectables|Okoumé|Jonathan Painchaud|
Thierry Larose|Marco Ema|Alphonse Bisaillon|Rau_Ze|Valence|Comment Debord|Bon Enfant|Clay and Friends|Gab Bouchard|
Etienne Dufresne|Choses Sauvages|Alex Nevsky|Safia Nolin|Fred Fortin|Mon Doux Saigneur|Laurence Nerbonne|Corridor|
Karim Ouellet|Ingrid St-Pierre|Marie-Pierre Arthur|Andréanne A. Malette|Valaire|Les frères à ch'val|Brigitte Boisjoli|
Daniel Lavoie|Patrick Norman|Renée Martel|Nanette Workman|Mario Pelchat|Les Charbonniers de l'enfer|La Bottine Souriante|
Dumas|Tizzo|Shreez|KNLO|5sang14|Imposs|Calamine|Lary Kidd|Loud Lary Ajust|Dead Obies|Sans Pression|Muzion|Obia le Chef|
Matiu|Zen Bamboo|Mélissa Bédard|Alicia Moffet|Soleil Launière|La Zarra|Fanny Bloom|Fredz|Cachemire|Lydia Képinski|Sara Dufour
"""

# Mostly sing in English or another language, or aren't from Quebec.
SKIP = {norm(a).replace(" ", "") for a in [
    "Arcade Fire", "Simple Plan", "Half Moon Run", "Patrick Watson", "Men I Trust", "Leonard Cohen", "Corey Hart",
    "Men Without Hats", "Bran Van 3000", "Random Recipe", "Matt Lang", "Kathleen", "Milk & Bone", "Zach Zoya",
    "NAYA ALI", "KROY", "Matt Holubowski", "Elisapie", "Kaycyy", "Mike Clay", "Wilfred LeBouthillier",
    "P'tit Belliveau", "Annie Blanchard", "Jean-François Breau", "Stéphanie Lapointe", "Andrée Watters",
    "Laurence-Anne", "Les Séguin", "GrimSkunk",
]}

ENGLISH = re.compile(r"\b(the|you|your|my|love|baby|i'?m|it'?s|don'?t|and|is|be|with|we|feel|like|what|this|that|for|just|know|i|it|in|of|all|so|oh|yeah|tonight|girl|boy|go|get|got|way|night|day|time|one)\b", re.I)
COMPILE = re.compile(r"best of|greatest|essentiel|collection|anthologie|grands succ|compil|hits|remaster|live|en concert|en spectacle|karaok|coffret|integrale|intégrale|volume|vol\.|vs\b", re.I)

lock = threading.Lock()
last = [0.0]


def get(url, cache):
    if url in cache:
        return cache[url]
    for attempt in range(4):
        with lock:  # Deezer allows ~50 requests / 5 s
            wait = last[0] + 0.12 - time.time()
            if wait > 0:
                time.sleep(wait)
            last[0] = time.time()
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                data = json.load(r)
            if "error" in data:
                raise RuntimeError(data["error"])
            cache[url] = data
            return data
        except Exception as e:
            print(f"  retry {attempt + 1} ({e})", flush=True)
            time.sleep(5)
    return {}


def catalog_keys():
    keys = {norm(l) for l in (ROOT / "scripts" / "blocklist.txt").read_text().splitlines()
            if l.strip() and not l.startswith("#")}
    for line in (ROOT / "scripts" / "catalog.tsv").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            keys.add(norm(line.split("\t")[0]))
    return keys


GENRES = {"rap": "Rap", "hip hop": "Rap", "rock": "Rock", "alternative": "Rock", "metal": "Rock", "punk": "Rock",
          "chanson": "Chanson", "folk": "Folk & trad", "country": "Folk & trad", "traditionnel": "Folk & trad"}


def genre_of(album):
    names = " ".join(g["name"].lower() for g in album.get("genres", {}).get("data", []))
    for key, label in GENRES.items():
        if key in names:
            return label
    return "Pop"


def artist_rows(name, cache, taken):
    want = norm(name).replace(" ", "")
    res = get("https://api.deezer.com/search/artist?" + urllib.parse.urlencode({"q": name, "limit": 10}), cache)
    hits = [a for a in res.get("data", []) if norm(a["name"]).replace(" ", "") == want]
    if not hits:
        return name, None, []
    artist = max(hits, key=lambda a: a.get("nb_fan", 0))
    top = get(f"https://api.deezer.com/artist/{artist['id']}/top?limit=25", cache).get("data", [])
    rows, seen = [], set()
    for t in top:
        title = t["title"]
        key = norm(title)
        if (len(rows) >= PER_ARTIST or key in seen or key in taken or not t.get("preview")
                or norm(t["artist"]["name"]).replace(" ", "") != want
                or BAD.search(key) or ENGLISH.search(title) or "feat" in title.lower()
                or COMPILE.search(t["album"]["title"])):
            continue
        album = get(f"https://api.deezer.com/album/{t['album']['id']}", cache)
        if (album.get("record_type") == "compile" or not album.get("release_date")
                or int(album["release_date"][:4]) < MIN_YEAR):
            continue
        seen.add(key)
        clean = re.sub(r"\s*[\(\[].*?[\)\]]\s*", " ", title).strip()
        rows.append([clean, name, album["release_date"][:4], genre_of(album), "3", title, str(t["id"])])
    return name, artist, rows


def main():
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    # Artists capped in artist_limits.tsv are already at their limit: don't add more of them.
    capped = {norm(l.split("\t")[0]).replace(" ", "") for l in (ROOT / "scripts" / "artist_limits.tsv").read_text().splitlines()
              if l.strip() and not l.startswith("#")}
    names = []
    for a in (ARTISTS + "|" + NEW_ARTISTS).replace("\n", "|").split("|"):
        a = a.strip()
        if a and norm(a).replace(" ", "") not in SKIP | capped and a not in names:
            names.append(a)
    taken = catalog_keys()
    out, missing = [], []
    try:
        with ThreadPoolExecutor(6) as pool:
            for name, artist, rows in pool.map(lambda n: artist_rows(n, cache, taken), names):
                if artist is None:
                    missing.append(name)
                    continue
                out.extend(rows)
                print(f"✓ {name}: +{len(rows)}", flush=True)
    finally:
        CACHE.write_text(json.dumps(cache))
    # Same title by two artists: keep the first one only, so guesses stay unambiguous.
    seen, final = set(), []
    for r in out:
        if norm(r[0]) not in seen:
            seen.add(norm(r[0]))
            final.append(r)
    OUT.write_text("\n".join("\t".join(r) for r in final) + "\n")
    print(f"{len(final)} nouvelles chansons → {OUT.relative_to(ROOT)}")
    if missing:
        print("artistes introuvables:", ", ".join(missing))


if __name__ == "__main__":
    main()
