@echo off
REM Windows Development Setup Script for EngDoc
echo === EngDoc Development Setup (Windows) ===

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.12+ is not found in PATH. Please install Python.
    exit /b 1
)

where uv >nul 2>&1
if errorlevel 1 (
    echo [*] Installing uv package manager...
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
)

echo [*] Syncing dependencies...
uv sync --extra dev

echo [*] Running diagnostics...
uv run python scripts\doctor.py

echo === Setup Complete ===
echo Launch dev server with: uv run uvicorn engdoc.api.app:app --reload --port 8000

