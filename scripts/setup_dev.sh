#!/usr/bin/env bash
# Development environment setup script for Linux/macOS
set -e

echo "=== EngDoc Development Setup ==="

# Check Python version
python3 -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ required"'
echo "[OK] Python 3.12+ detected."

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "[!] uv is not installed. Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
echo "[OK] uv is available: $(uv --version)"

# Sync dependencies and create virtual environment
echo "[*] Syncing virtual environment and dependencies..."
uv sync --extra dev

# Run environment diagnostics
echo "[*] Running EngDoc diagnostics..."
uv run python scripts/doctor.py

echo "=== Setup Complete! ==="
echo "Launch dev server with: uv run uvicorn engdoc.api.app:app --reload --port 8000"
