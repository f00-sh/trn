#!/usr/bin/env bash
# Local Streamlit setup helper for TRN (not a binary installer).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "TRN — local Streamlit setup"
echo "Repo: $ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo
echo "OK. Run:"
echo "  source .venv/bin/activate"
echo "  streamlit run app.py"
echo
echo "Live product: https://trn.f00.sh"
