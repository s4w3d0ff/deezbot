#!/usr/bin/env bash
set -e  # exit on error

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Activating virtual environment..."
source "$SCRIPT_DIR/deez_venv/bin/activate"

echo "Loading environment variables from .env..."
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
else
    echo "ERROR: .env file not found. Create it with DEEZ_CLIENT_ID and DEEZ_CLIENT_SECRET."
    exit 1
fi

echo "Running Python app..."
"$SCRIPT_DIR/deez_venv/bin/python" "$SCRIPT_DIR/src/bot.py"

echo "Deactivating virtual environment..."
deactivate
