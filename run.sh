#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

echo "Installing dependencies..."
.venv/bin/pip install -q -r requirements.txt

# Copy .env from example if not present
if [ ! -f ".env" ]; then
    echo "No .env found, copying from .env.example..."
    cp .env.example .env
fi

echo "Starting Tiny Monitor on http://0.0.0.0:${PORT:-8080}"
echo "Debug Chrome will auto-launch if CHROME_DEBUG_AUTO_LAUNCH=true"
exec .venv/bin/python src/main.py
