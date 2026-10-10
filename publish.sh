#!/usr/bin/env bash
# Rebuild from Stock Watcher and push so GitHub Pages stays current.
# Intended to be run after the morning digest (or by the 6:47am HKT Web Builder routine).
set -euo pipefail
cd "$(dirname "$0")"
python3 build.py
git add index.html latest.json
if git diff --cached --quiet; then
  echo "No changes to publish."
  exit 0
fi
git commit -m "Update dashboard $(date +%Y-%m-%d) HKT"
git push origin HEAD
echo "Pushed. Live: https://dustinmlcheng-ui.github.io/stock-dashboard/"
