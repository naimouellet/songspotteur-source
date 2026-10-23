#!/usr/bin/env bash
# Build dist/ and publish it to GitHub Pages (naimouellet/songspotteur).
# That repo holds only the built game; this one holds the source.
# Usage: scripts/deploy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="naimouellet/songspotteur"
DOMAIN="musiquizqc.com"
WORK="$ROOT/.deploy"

python3 "$ROOT/scripts/build_dist.py"

if [ ! -d "$WORK/.git" ]; then
  rm -rf "$WORK"
  if gh repo view "$REPO" >/dev/null 2>&1; then
    gh repo clone "$REPO" "$WORK"
  else
    gh repo create "$REPO" --public --description "Devine la chanson québécoise à partir d'un extrait d'une demi-seconde."
    git init -q -b main "$WORK"
    git -C "$WORK" remote add origin "https://github.com/$REPO.git"
  fi
fi

# Mirror dist/ into the Pages checkout, with a short README pointing to the source.
find "$WORK" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -R "$ROOT/dist/." "$WORK/"
cat > "$WORK/README.md" <<'MD'
# Musiquiz QC (version publiée)

Reconnais une chanson québécoise à partir d'un extrait d'une demi-seconde.

**Jouer : https://musiquizqc.com**

Ce dépôt contient seulement les fichiers publiés sur GitHub Pages.
Le code source, le catalogue et les scripts sont dans
[naimouellet/songspotteur-source](https://github.com/naimouellet/songspotteur-source).
MD
touch "$WORK/.nojekyll"

# Custom domain: only once its DNS points to GitHub Pages. Publishing the CNAME
# earlier would redirect the github.io address to a domain that doesn't work yet.
if dig +short A "$DOMAIN" | grep -Eq '^185\.199\.(108|109|110|111)\.153$'; then
  echo "$DOMAIN" > "$WORK/CNAME"
else
  echo "DNS de $DOMAIN pas encore vers GitHub Pages : publication à l'adresse github.io pour l'instant."
fi

cd "$WORK"
git add -A
if git diff --cached --quiet; then
  echo "Rien de nouveau à publier."
else
  git commit -q -m "Publier Musiquiz QC ($(date +%Y-%m-%d\ %H:%M))

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  git push -q -u origin main
fi

# Turn on Pages the first time (serves the main branch root).
if ! gh api "repos/$REPO/pages" >/dev/null 2>&1; then
  gh api -X POST "repos/$REPO/pages" -f "source[branch]=main" -f "source[path]=/" >/dev/null
fi

echo "En ligne sous peu : https://naimouellet.github.io/songspotteur/"
