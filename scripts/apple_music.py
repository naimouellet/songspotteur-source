"""Apple Music API helpers: developer token and catalog requests.

The private key (AuthKey_<KEY_ID>.p8) never lives in the repo. It is read from
the APPLE_MUSIC_KEY environment variable (the key's contents, for a remote
routine) or from ~/.songspotteur/AuthKey_<KEY_ID>.p8. The token is signed with
the openssl command line tool, so nothing needs to be installed.
"""
import base64
import json
import os
import pathlib
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

TEAM_ID = "98S29ZV6N8"
KEY_ID = "34W4P232TT"
STOREFRONT = "ca"
KEY_FILE = pathlib.Path.home() / ".songspotteur" / f"AuthKey_{KEY_ID}.p8"
API = "https://api.music.apple.com/v1"

_token = None


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _der_to_raw(der):
    """openssl gives an ASN.1 DER ECDSA signature; JWT wants r || s (32 bytes each)."""
    def read_int(buf, i):
        assert buf[i] == 0x02
        n = buf[i + 1]
        return buf[i + 2:i + 2 + n], i + 2 + n
    i = 2 if der[1] < 0x80 else 3
    r, i = read_int(der, i)
    s, _ = read_int(der, i)
    return r.lstrip(b"\0").rjust(32, b"\0") + s.lstrip(b"\0").rjust(32, b"\0")


def token(days=150):
    """A developer token valid for `days` (Apple allows up to about 6 months)."""
    global _token
    if _token:
        return _token
    key = os.environ.get("APPLE_MUSIC_KEY")
    key_path = None
    if key:
        f = tempfile.NamedTemporaryFile("w", suffix=".p8", delete=False)
        f.write(key)
        f.close()
        key_path = f.name
    else:
        key_path = str(KEY_FILE)
    now = int(time.time())
    header = _b64(json.dumps({"alg": "ES256", "kid": KEY_ID}).encode())
    payload = _b64(json.dumps({"iss": TEAM_ID, "iat": now, "exp": now + days * 86400}).encode())
    signing_input = f"{header}.{payload}".encode()
    try:
        der = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key_path],
                             input=signing_input, capture_output=True, check=True).stdout
    finally:
        if key:
            os.unlink(key_path)
    _token = f"{header}.{payload}.{_b64(_der_to_raw(der))}"
    return _token


def get(path, **params):
    """GET an Apple Music API path (e.g. "/catalog/ca/songs"), retrying on rate limits."""
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for attempt in range(5):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token()}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    raise RuntimeError(f"Apple Music API indisponible : {url}")


def songs_by_isrc(isrcs):
    """{isrc: [song resources]} for up to 25 ISRCs per request."""
    found = {}
    for i in range(0, len(isrcs), 25):
        batch = isrcs[i:i + 25]
        data = get(f"/catalog/{STOREFRONT}/songs", **{"filter[isrc]": ",".join(batch)})
        for song in data.get("data", []):
            found.setdefault(song["attributes"].get("isrc"), []).append(song)
    return found
