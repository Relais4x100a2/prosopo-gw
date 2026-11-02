#!/bin/sh
# Usage : run.sh <base.gw> <dossier_sortie>
# Filtre la base, la passe dans gwc puis gwu (conteneur jetable) et écrit dans le dossier :
# in.gw, filter.log, gwc.log, gwu.log, rt.gw. Le dossier doit être hors du dépôt.
set -eu
if [ "$#" -ne 2 ]; then
  echo "usage : $0 <base.gw> <dossier_sortie>" >&2
  exit 2
fi
BASE="$1"
OUT="$2"
IMAGE="${ORACLE_IMAGE:-geneweb-oracle:7.1.0-beta2}"
HERE="$(cd "$(dirname "$0")" && pwd)"

# Refus avant toute écriture si le dossier (ou son plus proche parent existant) est dans un dépôt git.
PROBE="$OUT"
while [ ! -d "$PROBE" ]; do PROBE="$(dirname "$PROBE")"; done
if git -C "$PROBE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "refus : dossier de sortie dans le dépôt" >&2
  exit 3
fi

mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
python3 "$HERE/filter.py" "$BASE" "$OUT/in.gw" > "$OUT/filter.log"
docker run --rm --user "$(id -u):$(id -g)" -v "$OUT:/out" "$IMAGE" sh -c '
  mkdir -p /tmp/w && cp /out/in.gw /tmp/w/src.gw && cd /tmp/w
  gwc -f -o b src.gw > /out/gwc.log 2>&1; echo gwc=$?
  gwu b -o /out/rt.gw > /out/gwu.log 2>&1; echo gwu=$?'
test -s "$OUT/rt.gw"
echo "familles : source=$(grep -c '^fam ' "$OUT/in.gw") gwu=$(grep -c '^fam ' "$OUT/rt.gw")"
