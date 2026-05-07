$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -U pip
    pip install -e .
} else {
    .\.venv\Scripts\Activate.ps1
}

python bot.py
