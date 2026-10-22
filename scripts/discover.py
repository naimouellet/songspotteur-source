"""List candidate tracks for Quebec artists from Deezer's top tracks.

Writes scripts/candidates.tsv (title, artist, year, rank) for hand-curation
into catalog.tsv. Usage: python3 -u scripts/discover.py
"""
import json
import pathlib
import time
import urllib.parse
import urllib.request

from build_catalog import BAD, norm

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "scripts" / ".deezer-discover-cache.json"
OUT = ROOT / "scripts" / "candidates.tsv"

ARTISTS = """
Loud|Loud Lary Ajust|Koriass|Alaclair Ensemble|Dead Obies|FouKi|Souldia|Rymz|Lost|Enima|Connaisseur Ticaso|KNLO|Robert Nelson|Manu Militari|Sans Pression|Muzion|Yes McCan|Imposs|Tizzo|Shreez|Zach Zoya|Lary Kidd|Sarahmée|Marie-Gold|White-B|5sang14|Rowjay|Jay Scøtt|Naya Ali|Calamine|Obia le Chef|Kirouac & Kodakludo|Random Recipe|
Charlotte Cardin|Roxane Bruneau|2Frères|Les Louanges|Hubert Lenoir|Lou-Adriane Cassidy|Ariane Roy|Klô Pelgag|Les sœurs Boulay|Louis-Jean Cormier|Alex Nevsky|Marie-Mai|Cœur de pirate|Bleu Jeans Bleu|Patrice Michaud|Vincent Vallières|Matt Holubowski|Jérôme 50|Mon Doux Saigneur|Émile Bilodeau|Fred Fortin|Pierre Lapointe|Safia Nolin|Laurence Nerbonne|Milk & Bone|Men I Trust|Corridor|Marc Dupré|Ludovick Bourgeois|Kevin Bazinet|Salebarbes|Valaire|Clay and Friends|Kroy|Elisapie|Bon Enfant|Choses Sauvages|Andréanne A. Malette|Marie-Pierre Arthur|Ingrid St-Pierre|Karim Ouellet|Les Trois Accords|Dumas|Half Moon Run|Patrick Watson|Arcade Fire|Simple Plan|Les Cowboys Fringants|Mes Aïeux|Ariane Moffatt|Daniel Bélanger|Jean Leloup|Les Colocs|Éric Lapointe|Kevin Parent|Daniel Boucher|Isabelle Boulay|Garou|Céline Dion|Kaïn|Les Respectables|Okoumé|France D'Amour|Sylvain Cossette|Bruno Pelletier|Marie-Élaine Thibert|Annie Villeneuve|Les Vulgaires Machins|Grimskunk|Karkwa|Malajube|Plume Latraverse|Offenbach|Michel Pagliaro|Robert Charlebois|Claude Dubois|Diane Dufresne|Ginette Reno|Marjo|Beau Dommage|Harmonium|Les Séguin|La Bottine Souriante|Jean-Pierre Ferland|Gilles Vigneault|Félix Leclerc|Les BB|Mitsou|Corey Hart|Men Without Hats|Leonard Cohen|Bran Van 3000|Les Charbonniers de l'enfer|Dan Bigras|Lynda Lemay|Richard Desjardins|Kathleen|Laurence Jalbert|Corneille|Jonathan Painchaud|Mario Pelchat|Martine St. Clair|Nanette Workman|Patrick Norman|Renée Martel|Daniel Lavoie|Diane Tell|Gerry Boulet|Paul Piché|Michel Rivard|Jean-François Breau|Stéphanie Lapointe|Andrée Watters|Wilfred LeBouthillier|Les Frères à ch'val|Brigitte Boisjoli|Annie Blanchard|Matt Lang|Laurence-Anne|P'tit Belliveau|
Thierry Larose|Marco Ema|Alphonse Bisaillon|Rau_Ze|Valence|Comment Debord|Gab Bouchard|Étienne Dufresne|Bombe
"""
# Not from Quebec: filtered out below even if someone re-adds them.
NOT_QC = {"wilfred lebouthillier", "p tit belliveau", "annie blanchard", "jean francois breau"}


def get(url, cache):
    if url in cache:
        return cache[url]
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                data = json.load(r)
            if "error" in data:
                raise RuntimeError(data["error"])
            cache[url] = data
            time.sleep(0.12)
            return data
        except Exception as e:
            print(f"  retry {attempt + 1} ({e})", flush=True)
            time.sleep(6)
    return {}


def main():
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    names = [a.strip() for a in ARTISTS.replace("\n", "|").split("|") if a.strip()]
    rows = []
    try:
        for name in names:
            if norm(name) in NOT_QC:
                continue
            res = get("https://api.deezer.com/search/artist?" + urllib.parse.urlencode({"q": name, "limit": 10}), cache)
            want = norm(name).replace(" ", "")
            hits = [a for a in res.get("data", []) if norm(a["name"]).replace(" ", "") == want]
            if not hits:
                print(f"✗ artiste introuvable: {name}", flush=True)
                continue
            artist = max(hits, key=lambda a: a.get("nb_fan", 0))
            top = get(f"https://api.deezer.com/artist/{artist['id']}/top?limit=25", cache).get("data", [])
            seen = set()
            kept = 0
            for t in top:
                key = norm(t["title"])
                if key in seen or BAD.search(key) or not t.get("preview") or kept >= 15:
                    continue
                seen.add(key)
                album = get(f"https://api.deezer.com/album/{t['album']['id']}", cache)
                year = (album.get("release_date") or "0000")[:4]
                rows.append((t["title"], artist["name"], year, str(t.get("rank", 0)), str(artist.get("nb_fan", 0)), album.get("title", "")))
                kept += 1
            print(f"✓ {artist['name']} ({artist.get('nb_fan', 0)} fans): {kept} titres", flush=True)
    finally:
        CACHE.write_text(json.dumps(cache))
    OUT.write_text("title\tartist\tyear\trank\tfans\talbum\n" + "\n".join("\t".join(r) for r in rows) + "\n")
    print(f"{len(rows)} candidats → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
