#!/usr/bin/env bash
# Lance harvest : démarre Docker + slskd si besoin, puis exécute la commande.
#   ./run.sh                 -> pipeline complet (fetch + search + download + organize)
#   ./run.sh status          -> état des morceaux
#   ./run.sh retry           -> remet les échecs en file
#   ./run.sh report          -> rapport CSV
#   ./run.sh fetch|search|download|organize
set -e
cd "$(dirname "$0")"

./start.sh

if [ $# -eq 0 ]; then
    set -- run
fi
exec .venv/bin/python -u -m harvest "$@"
