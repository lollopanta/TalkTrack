#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ "$(uname -s)" = "Darwin" ]; then
    mac_version="$(sw_vers -productVersion)"
    mac_major="${mac_version%%.*}"
    mac_minor="${mac_version#*.}"
    mac_minor="${mac_minor%%.*}"
    if (( mac_major > 14 || (mac_major == 14 && mac_minor >= 4) )); then
        if command -v swift >/dev/null 2>&1; then
            ./scripts/build_macos_audio_helper.sh || \
                echo "Native audio helper unavailable; BlackHole remains available as a fallback."
        else
            echo "Swift/Xcode Command Line Tools are required to build native audio capture."
            echo "Install them with: xcode-select --install"
            echo "You can continue with BlackHole as a fallback."
        fi
    fi
fi

if command -v uv >/dev/null 2>&1; then
    uv sync --extra cpu
    exec uv run --no-sync python main.py
fi

if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
exec .venv/bin/python main.py
