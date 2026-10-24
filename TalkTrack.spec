# PyInstaller one-folder build. Keep resources and the native CoreAudio helper
# beside the frozen Python modules so existing resource lookup continues to work.
import sys
import os
import subprocess
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all, collect_data_files, collect_submodules,
)


root = Path(SPECPATH)
is_macos = sys.platform == "darwin"
build_profile = os.environ.get("TALKTRACK_BUILD_PROFILE", "full").strip().lower()
if build_profile not in {"compact", "full"}:
    raise SystemExit("TALKTRACK_BUILD_PROFILE must be 'compact' or 'full'.")
if is_macos:
    # Finder reads an ICNS through the app bundle's Info.plist; the source PNG
    # alone does not provide a custom icon for the compiled .app.
    icon_source = root / "resources" / "TT_icon_512x512.png"
    iconset = root / ".build" / "TalkTrack.iconset"
    app_icon = root / ".build" / "talktrack.icns"
    iconset.mkdir(parents=True, exist_ok=True)
    for filename, size in (
        ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
    ):
        subprocess.run(
            ["sips", "-z", str(size), str(size), str(icon_source),
             "--out", str(iconset / filename)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(app_icon)],
        check=True,
    )
else:
    app_icon = root / "resources" / "talktrack.ico"
datas = [(str(root / "resources"), "resources")]
datas.extend(collect_data_files("faster_whisper"))
binaries = []
hiddenimports = (
    collect_submodules("app.ai")
    + collect_submodules("app.transcription")
)

# These libraries load PortAudio/libsndfile through ctypes, which static import
# analysis cannot reliably discover in a frozen application.
for package in ("sounddevice", "soundfile"):
    package_binaries, package_datas, package_hiddenimports = collect_all(package)
    binaries.extend(package_binaries)
    datas.extend(package_datas)
    hiddenimports.extend(package_hiddenimports)

if is_macos:
    helper_app = root / ".build" / "TalkTrackAudioCapture.app"
    if not helper_app.is_dir():
        raise SystemExit("Build the CoreAudio helper before freezing TalkTrack.")
    helper_binary = helper_app / "Contents" / "MacOS" / "TalkTrackAudioCapture"
    helper_info = helper_app / "Contents" / "Info.plist"
    if not helper_binary.is_file() or not helper_info.is_file():
        raise SystemExit("The CoreAudio helper bundle is incomplete.")
    # Keep the executable in PyInstaller's binary collection so its +x mode and
    # Mach-O handling survive the freeze; the privacy usage string lives in its
    # helper Info.plist.
    binaries.append((str(helper_binary), "talktrack_audio_helper/Contents/MacOS"))
    datas.append((str(helper_info), "talktrack_audio_helper/Contents"))

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # The Compact profile keeps Whisper transcription and channel based
    # speaker separation, while leaving the much larger pyannote/PyTorch stack
    # out. Full remains the default for local builds and includes all features.
    excludes=(
        [
            "torch", "torchaudio", "torchvision", "torchcodec",
            "pyannote", "pytorch_lightning", "lightning", "torchmetrics",
            "transformers", "sentence_transformers",
            "librosa", "matplotlib", "pandas", "sympy", "sklearn",
        ]
        if build_profile == "compact"
        else []
    ),
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TalkTrack",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(app_icon),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TalkTrack",
)

if is_macos:
    app = BUNDLE(
        coll,
        name="TalkTrack.app",
        icon=str(app_icon),
        bundle_identifier="com.talktrack.app",
        info_plist={
            "NSAudioCaptureUsageDescription": (
                "TalkTrack captures system audio when you start a recording."
            ),
            "NSMicrophoneUsageDescription": (
                "TalkTrack captures microphone audio when you start a recording."
            ),
        },
    )
