#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

echo "Installing dependencies..."
.venv/bin/pip install -q -r requirements.txt

echo "Starting Tiny Monitor on http://0.0.0.0:${PORT:-8080}"
exec .venv/bin/python src/main.py
