"""FFmpeg discovery for shells and GUI-launched macOS applications."""

import os
import shutil
import sys
from pathlib import Path


def find_ffmpeg():
    """Return the FFmpeg executable path, including common macOS install paths.

    Apps opened from Finder do not inherit Homebrew's shell PATH, so
    ``shutil.which`` alone can miss a working installation.
    """
    executable = shutil.which("ffmpeg")
    if executable:
        return executable

    if sys.platform == "darwin":
        candidates = (
            Path("/opt/homebrew/bin/ffmpeg"),
            Path("/usr/local/bin/ffmpeg"),
            Path("/opt/local/bin/ffmpeg"),
        )
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None
