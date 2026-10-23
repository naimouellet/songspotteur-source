"""Upcoming shows of each artist in the next six months: public/shows.js.

Two sources, merged per artist:
1. Bandcamp: the artist's page lists upcoming shows (from Songkick) with venue,
   city and a link. Good for small venues. Dates carry no year ("Nov 14"):
   since only upcoming shows are listed, each one is the next time that day
   comes around.
2. Ticketmaster (Discovery API), for the big venues. Needs a free key, read from
   the TICKETMASTER_KEY environment variable or ~/.songspotteur/ticketmaster.key;
   without one, this source is skipped. Only events where the artist is listed
   as a performer are kept (not parking passes or namesakes).
The same artist on the same day in the same city is one show; Ticketmaster's
link wins, since it leads straight to tickets. This runs once a week, so the
game also hides shows that have passed since.
Usage: python3 -u scripts/shows.py
"""
import datetime
import html
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from build_catalog import norm

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "public" / "shows.js"
HORIZON = datetime.timedelta(days=183)  # six months
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
TM_KEY_FILE = pathlib.Path.home() / ".songspotteur" / "ticketmaster.key"
TM_API = "https://app.ticketmaster.com/discovery/v2/events.json"


def load(path, name):
    """The table a generated .js file assigns to window.<name>, or {} if missing."""
    if not path.exists():
        return {}
    return json.loads(re.search(rf"window\.{name} = (.*);", path.read_text(), re.S)[1])


def text(fragment):
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def city_name(city):
    """The usual English spellings of Quebec cities, in French."""
    return {"Montreal": "Montréal", "Quebec": "Québec", "Quebec City": "Québec",
            "Trois-Rivieres": "Trois-Rivières"}.get(city, city)


def fetch(url, headers=None):
    """A page or API response; when the server asks to slow down (429), wait and try again."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 3:
                raise
            time.sleep(int(e.headers.get("Retry-After") or 0) or 30 * (attempt + 1))


# Bandcamp

def show_date(label, today):
    """Date of a Bandcamp label such as "Nov 14" or "Feb 27, 2027", or None."""
    m = re.match(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?", label)
    if not m or m[1].lower() not in MONTHS:
        return None
    month, day = MONTHS[m[1].lower()], int(m[2])
    try:
        if m[3]:
            return datetime.date(int(m[3]), month, day)
        d = datetime.date(today.year, month, day)
        return d if d >= today else datetime.date(today.year + 1, month, day)
    except ValueError:  # Feb 29 outside a leap year
        return None


def bandcamp_shows(url, today):
    block = re.search(r'id="showography".*?</ul>', fetch(url), re.S)
    found = []
    for li in re.findall(r"<li>(.*?)</li>", block[0] if block else "", re.S):
        label = re.search(r'class="showDate[^"]*">(.*?)</div>', li, re.S)
        venue = re.search(r'class="showVenue[^"]*">(.*?)</div>', li, re.S)
        where = re.search(r'class="showLoc[^"]*">(.*?)</div>', li, re.S)
        d = show_date(text(label[1]), today) if label else None
        if not d:
            continue
        city, _, region = text(where[1]).partition(",") if where else ("", "", "")
        link = re.search(r'href="([^"]+)"', venue[1]) if venue else None
        found.append({
            "date": d.isoformat(),
            "venue": text(venue[1]) if venue else "",
            "city": city_name(city.strip()),
            "region": region.strip(),  # "QC", "ON", "France"…
            # Songkick's page for the show; its tracking parameters are dropped.
            "url": html.unescape(link[1]).split("?")[0] if link else url,
            "source": "bandcamp",
        })
    return found


# Ticketmaster

def ticketmaster_key():
    key = os.environ.get("TICKETMASTER_KEY")
    if not key and TM_KEY_FILE.exists():
        key = TM_KEY_FILE.read_text().strip()
    return key or None


def ticketmaster_shows(artist, key, today):
    params = {
        "apikey": key, "keyword": artist, "classificationName": "music", "size": 100, "sort": "date,asc",
        "startDateTime": f"{today.isoformat()}T00:00:00Z",
        "endDateTime": f"{(today + HORIZON).isoformat()}T23:59:59Z",
    }
    data = json.loads(fetch(f"{TM_API}?{urllib.parse.urlencode(params)}"))
    want = norm(artist).replace(" ", "")
    found = []
    for e in data.get("_embedded", {}).get("events", []):
        performers = [norm(a.get("name", "")).replace(" ", "") for a in e.get("_embedded", {}).get("attractions", [])]
        start = e.get("dates", {}).get("start", {})
        if want not in performers or not start.get("localDate"):
            continue
        if e.get("dates", {}).get("status", {}).get("code") in ("cancelled", "postponed"):
            continue
        venue = (e.get("_embedded", {}).get("venues") or [{}])[0]
        found.append({
            "date": start["localDate"],
            "venue": venue.get("name", ""),
            "city": city_name(venue.get("city", {}).get("name", "")),
            "region": venue.get("state", {}).get("stateCode") or venue.get("country", {}).get("name", ""),
            "url": e.get("url", ""),
            "source": "ticketmaster",
        })
    return found


def merge(*lists):
    """One entry per day and city, Ticketmaster first; sorted by date."""
    rank = {"ticketmaster": 0, "bandcamp": 1}
    shows = {}
    for s in sorted((s for l in lists for s in l), key=lambda s: rank[s["source"]]):
        shows.setdefault((s["date"], norm(s["city"])), s)
    return sorted(shows.values(), key=lambda s: s["date"])


def main():
    today = datetime.date.today()
    last = (today + HORIZON).isoformat()
    previous = load(OUT, "SHOWS")
    pages = load(ROOT / "public" / "bandcamp.js", "BANDCAMP")
    artists = sorted({s["artist"] for s in load(ROOT / "public" / "songs.js", "SONGS")})
    key = ticketmaster_key()
    if not key:
        print(f"Pas de clé Ticketmaster ({TM_KEY_FILE}) : Bandcamp seulement.", flush=True)

    def kept(artist, source):
        """Last week's still-upcoming dates from a source that failed this time."""
        return [s for s in previous.get(artist, []) if s.get("source") == source and today.isoformat() <= s["date"]]

    result = {}
    for artist in artists:
        lists = []
        for source, get in (("bandcamp", pages.get(artist) and (lambda: bandcamp_shows(pages[artist], today))),
                            ("ticketmaster", key and (lambda: ticketmaster_shows(artist, key, today)))):
            if not get:
                continue
            try:
                lists.append(get())
            except Exception as e:
                lists.append(kept(artist, source))
                print(f"  {artist} : {source} indisponible ({e}), dates précédentes gardées", flush=True)
            time.sleep(1.5 if source == "bandcamp" else 0.25)  # Bandcamp refuses quick series of requests
        shows = [s for s in merge(*lists) if today.isoformat() <= s["date"] <= last]
        if shows:
            result[artist] = shows
            print(f"✓ {artist} : {len(shows)} spectacle(s)", flush=True)
    OUT.write_text(
        "// Généré par scripts/shows.py — ne pas éditer à la main.\n"
        "window.SHOWS = " + json.dumps(result, ensure_ascii=False, indent=1) + ";\n")
    print(f"{len(result)} artistes avec des spectacles à venir → public/shows.js")


if __name__ == "__main__":
    main()
