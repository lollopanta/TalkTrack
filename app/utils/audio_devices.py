import sys
import platform
from pathlib import Path

import sounddevice as sd


MACOS_CORE_AUDIO_TAP_DEVICE = "talktrack:core-audio-tap"


def macos_core_audio_helper_path():
    """Locate the native audio helper in a source checkout or frozen app."""
    source_path = (
        Path(__file__).resolve().parents[2] / ".build"
        / "TalkTrackAudioCapture.app" / "Contents" / "MacOS"
        / "TalkTrackAudioCapture"
    )
    if source_path.is_file():
        return source_path

    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return (
            Path(bundle_root) / "talktrack_audio_helper" / "Contents"
            / "MacOS" / "TalkTrackAudioCapture"
        )
    return source_path


def _macos_core_audio_taps_available():
    """Check OS support and whether the native tap helper has been built."""
    version = platform.mac_ver()[0]
    try:
        parts = tuple(int(part) for part in version.split(".")[:2])
    except ValueError:
        return False
    if parts < (14, 4):
        return False
    return macos_core_audio_helper_path().is_file()


def _is_hidden(name, hidden_devices):
    """Check if a device name matches any hidden device pattern (case-insensitive)."""
    if not hidden_devices:
        return False
    name_lower = name.lower()
    for pattern in hidden_devices:
        if pattern.lower() in name_lower:
            return True
    return False


def get_input_devices(hidden_devices=None):
    """Return list of audio input (microphone) devices."""
    devices = sd.query_devices()
    inputs = []
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            if _is_hidden(dev["name"], hidden_devices):
                continue
            inputs.append({
                "index": i,
                "name": dev["name"],
                "channels": dev["max_input_channels"],
                "sample_rate": dev["default_samplerate"],
                "hostapi": sd.query_hostapis(dev["hostapi"])["name"],
            })
    return inputs


def get_loopback_devices():
    """Return list of WASAPI loopback devices for system audio capture."""
    devices = sd.query_devices()
    loopbacks = []
    for i, dev in enumerate(devices):
        hostapi = sd.query_hostapis(dev["hostapi"])
        if hostapi["name"] == "Windows WASAPI" and dev["max_input_channels"] > 0:
            if "loopback" in dev["name"].lower() or dev["max_output_channels"] > 0:
                loopbacks.append({
                    "index": i,
                    "name": dev["name"],
                    "channels": dev["max_input_channels"],
                    "sample_rate": dev["default_samplerate"],
                    "hostapi": "WASAPI",
                })
    return loopbacks


def get_system_audio_devices(hidden_devices=None):
    """Return devices usable as a system-audio capture source.

    Windows uses output devices whose loopback input is provided by
    PyAudioWPatch. macOS 14.4+ uses Apple's native Core Audio process tap;
    older versions can use a virtual input such as BlackHole.
    """
    devices = sd.query_devices()
    outputs = []
    is_macos = platform.system() == "Darwin"
    if is_macos and _macos_core_audio_taps_available():
        native = {
            "index": MACOS_CORE_AUDIO_TAP_DEVICE,
            "name": "macOS System Audio",
            "channels": 1,
            "sample_rate": 48000,
            "hostapi": "Core Audio Tap",
        }
        if not _is_hidden(native["name"], hidden_devices):
            outputs.append(native)
    for i, dev in enumerate(devices):
        hostapi = sd.query_hostapis(dev["hostapi"])
        if is_macos:
            # Only list common virtual loopback devices, not microphones.
            virtual_loopback = any(
                marker in dev["name"].lower()
                for marker in ("blackhole", "loopback", "soundflower")
            )
            usable = virtual_loopback and dev["max_input_channels"] > 0
            label = "Virtual Audio Input"
        else:
            usable = (hostapi["name"] == "Windows WASAPI"
                      and dev["max_output_channels"] > 0)
            label = "WASAPI"
        if usable:
            if _is_hidden(dev["name"], hidden_devices):
                continue
            outputs.append({
                "index": i,
                "name": dev["name"],
                "channels": (dev["max_input_channels"] if is_macos
                             else dev["max_output_channels"]),
                "sample_rate": dev["default_samplerate"],
                "hostapi": label,
            })
    return outputs


# Keep old name as alias
get_wasapi_output_devices = get_system_audio_devices


def get_default_mic():
    """Return the default microphone device index."""
    try:
        return sd.default.device[0]
    except Exception:
        inputs = get_input_devices()
        return inputs[0]["index"] if inputs else None


def get_default_output():
    """Return the system-audio source index.

    On macOS this is the first detected virtual loopback input. On Windows,
    sd.default.device[1] can return a DirectSound/MME index that doesn't match
    WASAPI, so match by device name instead.
    """
    if platform.system() == "Darwin":
        outputs = get_system_audio_devices()
        return outputs[0]["index"] if outputs else None
    try:
        default_idx = sd.default.device[1]
        if default_idx is not None and default_idx >= 0:
            default_info = sd.query_devices(default_idx)
            default_name = default_info["name"]
            # Find the matching WASAPI output device by name
            for dev in get_system_audio_devices():
                if dev["name"] == default_name:
                    return dev["index"]
    except Exception:
        pass
    outputs = get_system_audio_devices()
    return outputs[0]["index"] if outputs else None
