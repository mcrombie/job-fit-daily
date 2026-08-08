#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m unittest discover -s tests -v
python -m jobfit demo
python -m http.server 8000 --directory site
