#!/usr/bin/env bash
# Weekly update: add the new songs of the TOP QUEB playlist, refresh show dates, then publish.
#   1. playlist_import.py   new playlist songs → catalog.tsv
#   2. build_catalog.py     Apple clip, cover and Deezer fallback for them
#   3. bandcamp.py          Bandcamp pages for new artists only
#   4. shows.py             upcoming shows from the Bandcamp pages, every week
#   5. commit + push the source, deploy.sh to GitHub Pages (only if something changed)
#   6. if GitHub's Pages deployment fails (it happens on their side), ask for a rebuild
# Needs: the MusicKit key in ~/.songspotteur/ and `gh` signed in.
# Usage: scripts/weekly_update.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
REPORT="$(mktemp)"

git pull -q --ff-only

python3 -u scripts/playlist_import.py | tee "$REPORT"
ADDED=$(sed -n 's/^\([0-9]*\) lignes ajoutées.*/\1/p' "$REPORT")
if [ -n "$ADDED" ]; then
  python3 -u scripts/build_catalog.py | grep -v "^✓" || true
  python3 -u scripts/bandcamp.py
  SUMMARY="+$ADDED chanson(s) de TOP QUEB, spectacles à jour"
else
  echo "Aucune nouvelle chanson dans la playlist."
  SUMMARY="spectacles à jour"
fi

# Les dates de spectacles changent chaque semaine, même sans nouvelle chanson.
python3 -u scripts/shows.py

if [ -z "$(git status --porcelain)" ]; then
  echo "Rien de nouveau : rien à publier."
  exit 0
fi

git add -A
git commit -q -m "Mise à jour hebdomadaire : $SUMMARY

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push -q

scripts/deploy.sh

# GitHub's Pages deployment occasionally fails server-side: wait for it, rebuild once if needed.
REPO="naimouellet/songspotteur"
for i in $(seq 1 30); do
  sleep 10
  STATE=$(gh run list -R "$REPO" -L 1 --json status,conclusion --jq '.[0].status + " " + (.[0].conclusion // "")')
  case "$STATE" in
    "completed success") echo "Publication GitHub Pages : réussie."; exit 0 ;;
    "completed "*) echo "Publication GitHub Pages : échec côté GitHub, nouvelle tentative."
                   gh api -X POST "repos/$REPO/pages/builds" >/dev/null; sleep 30 ;;
  esac
done
echo "Publication GitHub Pages : toujours en attente, à vérifier."
