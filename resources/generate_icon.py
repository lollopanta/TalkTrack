"""Rebuild the Windows icon from the checked-in TalkTrack icon PNG variants."""

try:
    from .build_ico import build_ico
except ImportError:  # Running this file directly from the repository.
    from build_ico import build_ico


if __name__ == "__main__":
    build_ico()
