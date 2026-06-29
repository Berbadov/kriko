#!/bin/bash
# add_car.sh — add a new car model to the Kriko knowledge base
#
# Usage:
#   ./add_car.sh <make> <model>
#   ./add_car.sh volkswagen golf_7
#   ./add_car.sh renault megane_4
#
# What this does:
#   1. Discovers engine/transmission codes from Wikipedia → creates variants + fitment YAMLs
#   2. Runs the full pipeline for every part type (engine, transmission, electrical)
#   3. Syncs all claims to the Postgres DB

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <make> <model>"
  echo "  e.g. $0 volkswagen golf_7"
  exit 1
fi

MAKE="$1"
MODEL="$2"

echo "══════════════════════════════════════════════"
echo " Kriko — adding ${MAKE} ${MODEL}"
echo "══════════════════════════════════════════════"

echo ""
echo "[1/3] Discovering parts from Wikipedia..."
python3 -m knowledge.catalog.discover --make "$MAKE" --model "$MODEL" --write-fitment

echo ""
echo "[2/3] Running knowledge pipeline for all parts..."
python3 -m knowledge.auto --make "$MAKE" --model "$MODEL" --all-parts

echo ""
echo "[3/3] Syncing claims to database..."
docker exec deploy-api-1 python -m backend.sync

echo ""
echo "Done. Review pending claims in backend/data/parts/ then re-run step 3 to publish."
