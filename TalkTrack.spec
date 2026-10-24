# PyInstaller one-folder build. Keep resources and the native CoreAudio helper
# beside the frozen Python modules so existing resource lookup continues to work.
import sys
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


root = Path(SPECPATH)
is_macos = sys.platform == "darwin"
build_profile = os.environ.get("TALKTRACK_BUILD_PROFILE", "full").strip().lower()
if build_profile not in {"compact", "full"}:
    raise SystemExit("TALKTRACK_BUILD_PROFILE must be 'compact' or 'full'.")
app_icon = root / "resources" / (
    "talktrack.icns" if is_macos else "talktrack.ico"
)
datas = [(str(root / "resources"), "resources")]
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
    icon=str(app_icon) if app_icon.is_file() else None,
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
        icon=str(app_icon) if app_icon.is_file() else None,
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
