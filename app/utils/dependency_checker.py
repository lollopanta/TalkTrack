"""Dependency checker for TalkTrack system status panel."""
import subprocess
import sys
from pathlib import Path

from app.utils.audio_devices import get_input_devices, get_wasapi_output_devices
from app.utils.ffmpeg import find_ffmpeg
from app.utils.platform_info import is_windows, is_windows_11, get_windows_build


def whisper_cache_dir(model_size):
    """HuggingFace cache directory for a faster-whisper model.

    Not every model is published by Systran — large-v3-turbo lives under
    mobiuslabsgmbh — so the repo id comes from faster-whisper's own table
    rather than a hardcoded org. Falls back to the Systran layout when the
    lookup isn't available. (issue #73)
    """
    repo = f"Systran/faster-whisper-{model_size}"
    try:
        from faster_whisper.utils import _MODELS
        repo = _MODELS.get(model_size, repo)
    except Exception:
        pass
    return Path.home() / ".cache" / "huggingface" / "hub" / f"models--{repo.replace('/', '--')}"


class DependencyChecker:
    """Checks system dependencies and reports their status."""

    def __init__(self, config=None):
        self.config = config

    def run_all_checks(self):
        """Run all dependency checks and return list of results."""
        return [
            self.check_microphone(),
            self.check_wasapi(),
            self.check_gpu_cuda(),
            self.check_ffmpeg(),
            self.check_whisper_model(),
            self.check_hf_token(),
            self.check_pyannote_models(),
            self.check_package_metadata(),
            self.check_windows_version(),
        ]

    def check_package_metadata(self, packages=("numpy", "torch", "faster-whisper")):
        """Detect packages whose installed metadata is damaged or missing.

        An interrupted installer (e.g. a killed uv sync) can gut a package's
        dist-info while leaving it importable: importlib.metadata then reports
        no version and libraries like transformers fail with the cryptic
        "Unable to compare versions ... found=None". Say it plainly instead.
        """
        import importlib
        import importlib.metadata as md
        import importlib.util

        # PyTorch is optional in Compact builds; its absence is expected there.
        if "torch" in packages:
            try:
                if importlib.util.find_spec("torch") is None:
                    packages = tuple(pkg for pkg in packages if pkg != "torch")
            except (ImportError, ModuleNotFoundError, ValueError):
                packages = tuple(pkg for pkg in packages if pkg != "torch")

        damaged = []
        missing = []
        for pkg in packages:
            import_name = pkg.replace("-", "_")
            if getattr(sys, "frozen", False):
                # PyInstaller bundles importable modules, not their dist-info
                # metadata by default. Missing metadata in a frozen app is
                # expected and must not be reported as a broken installation.
                try:
                    available = importlib.util.find_spec(import_name) is not None
                except (ImportError, ModuleNotFoundError, ValueError):
                    available = False
                if not available:
                    missing.append(pkg)
                continue
            try:
                version = md.version(pkg)
            except md.PackageNotFoundError:
                version = None
            except Exception:
                version = None
            if version:
                continue
            try:
                importlib.import_module(import_name)
                damaged.append(pkg)
            except Exception:
                missing.append(pkg)

        if damaged:
            names = ", ".join(damaged)
            venv_python = (Path(".venv") / "Scripts" / "python.exe"
                           if sys.platform == "win32"
                           else Path(".venv") / "bin" / "python")
            return {
                "name": "Package Metadata",
                "passed": False,
                "level": "critical",
                "message": (
                    f"Damaged install metadata for: {names} — the package "
                    "imports but its version is unreadable (usually an "
                    "interrupted install). Transcription/AI features will fail."
                ),
                "action": (
                    "Close TalkTrack and force-reinstall into the venv:\n"
                    f"uv pip install --python {venv_python} "
                    f"--force-reinstall {' '.join(damaged)}"
                ),
            }
        if missing:
            names = ", ".join(missing)
            return {
                "name": "Package Metadata",
                "passed": False,
                "level": "warn",
                "message": f"Not installed: {names}.",
                "action": (
                    "Run start.bat to install dependencies."
                    if sys.platform == "win32"
                    else "Run ./start.command to install dependencies."
                ),
            }
        return {
            "name": "Package Metadata",
            "passed": True,
            "level": "critical",
            "message": "Install metadata intact for " + ", ".join(packages) + ".",
            "action": None,
        }

    def check_microphone(self):
        """Check if any microphone input devices are available."""
        try:
            devices = get_input_devices()
            if devices:
                return {
                    "name": "Microphone",
                    "passed": True,
                    "level": "critical",
                    "message": f"Found {len(devices)} input device(s): {devices[0]['name']}",
                    "action": None,
                }
            else:
                return {
                    "name": "Microphone",
                    "passed": False,
                    "level": "critical",
                    "message": "No microphone input devices found.",
                    "action": "Connect a microphone or headset and restart TalkTrack.",
                }
        except Exception as e:
            return {
                "name": "Microphone",
                "passed": False,
                "level": "critical",
                "message": f"Error checking microphone: {e}",
                "action": "Ensure audio drivers are installed.",
            }

    def check_wasapi(self):
        """Check if the platform's system-audio capture source is available."""
        try:
            devices = get_wasapi_output_devices()
            if not is_windows():
                if devices:
                    if devices[0].get("hostapi") == "Core Audio Tap":
                        return {
                            "name": "System Audio Input",
                            "passed": True,
                            "level": "info",
                            "message": "Native Core Audio capture is available.",
                            "action": None,
                        }
                    return {
                        "name": "System Audio Input",
                        "passed": True,
                        "level": "info",
                        "message": f"Found virtual audio input: {devices[0]['name']}.",
                        "action": None,
                    }
                return {
                    "name": "System Audio Input",
                    "passed": False,
                    "level": "info",
                    "message": "No supported virtual audio input found.",
                    "action": (
                        "Run ./start.command to build native macOS capture. "
                        "On macOS before 14.4, install BlackHole and route system output to it."
                    ),
                }
            if devices:
                return {
                    "name": "WASAPI Loopback",
                    "passed": True,
                    "level": "critical",
                    "message": f"Found {len(devices)} WASAPI output device(s).",
                    "action": None,
                }
            else:
                return {
                    "name": "WASAPI Loopback",
                    "passed": False,
                    "level": "critical",
                    "message": "No WASAPI output devices found.",
                    "action": "WASAPI is required for system audio capture on Windows.",
                }
        except Exception as e:
            return {
                "name": "WASAPI Loopback",
                "passed": False,
                "level": "critical",
                "message": f"Error checking WASAPI: {e}",
                "action": "Ensure Windows audio services are running.",
            }

    @staticmethod
    def detect_gpu_cuda():
        """Detect NVIDIA GPU presence and CUDA PyTorch status.

        Returns dict with keys:
            has_nvidia_gpu (bool): True if NVIDIA GPU detected
            gpu_name (str): GPU name or empty string
            torch_has_cuda (bool): True if PyTorch has CUDA support
            cuda_version (str): CUDA version string or empty
        """
        result = {
            "has_nvidia_gpu": False,
            "gpu_name": "",
            "torch_has_cuda": False,
            "cuda_version": "",
        }
        # Check for NVIDIA GPU via torch first (most reliable if available)
        try:
            import torch
            result["torch_has_cuda"] = torch.cuda.is_available()
            if result["torch_has_cuda"]:
                result["has_nvidia_gpu"] = True
                result["gpu_name"] = torch.cuda.get_device_name(0)
                result["cuda_version"] = torch.version.cuda or ""
                return result
            # torch installed but no CUDA — check if GPU exists via subprocess
        except Exception:
            # Not just ImportError: a broken torch install raises OSError
            # (DLL load) or RuntimeError on import — fall through to nvidia-smi
            # rather than taking down the whole status panel.
            pass

        # Fallback: detect NVIDIA GPU via nvidia-smi
        try:
            output = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            if output.returncode == 0 and output.stdout.strip():
                result["has_nvidia_gpu"] = True
                result["gpu_name"] = output.stdout.strip().split("\n")[0]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return result

    def check_gpu_cuda(self):
        """Check GPU availability and CUDA PyTorch setup."""
        info = self.detect_gpu_cuda()

        # gpu_name from torch/nvidia-smi already includes "NVIDIA" on modern
        # cards; older ones may not. Normalize to exactly one "NVIDIA " prefix
        # so messages don't read "NVIDIA NVIDIA GeForce ...".
        _name = info["gpu_name"] or "GPU"
        gpu = _name if _name.upper().startswith("NVIDIA") else f"NVIDIA {_name}"

        # Check what device the user has configured
        configured_device = "cpu"
        if self.config:
            try:
                configured_device = self.config.get("transcription", "device")
            except (KeyError, TypeError):
                pass

        if info["torch_has_cuda"]:
            return {
                "name": "GPU Acceleration",
                "passed": True,
                "level": "info",
                "message": f"{gpu} detected with CUDA {info['cuda_version']}.",
                "action": None,
            }
        elif info["has_nvidia_gpu"]:
            action = (
                f"{gpu} detected but PyTorch is CPU-only. "
                "To enable GPU acceleration, run:\n"
                "pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126"
            )
            if configured_device == "cuda":
                action += "\nTranscription will fall back to CPU until this is resolved."
            return {
                "name": "GPU Acceleration",
                "passed": False,
                "level": "warn",
                "message": f"{gpu} found but CUDA PyTorch not installed.",
                "action": action,
            }
        else:
            return {
                "name": "GPU Acceleration",
                "passed": True if configured_device == "cpu" else False,
                "level": "info",
                "message": "No NVIDIA GPU detected. Using CPU for transcription.",
                "action": None if configured_device == "cpu" else "Set Compute Device to CPU in Settings.",
            }

    def check_whisper_model(self):
        """Check if the configured Whisper model is cached locally."""
        model_size = "base"
        if self.config:
            try:
                model_size = self.config.get("transcription", "model_size")
            except (KeyError, TypeError):
                pass

        cache_dir = whisper_cache_dir(model_size)
        if cache_dir.exists():
            return {
                "name": "Whisper Model",
                "passed": True,
                "level": "critical",
                "message": f"Model 'faster-whisper-{model_size}' is cached.",
                "action": None,
            }
        else:
            return {
                "name": "Whisper Model",
                "passed": False,
                "level": "critical",
                "message": f"Model 'faster-whisper-{model_size}' not found in cache.",
                "action": "The model will be downloaded automatically on first transcription.",
            }

    def check_hf_token(self):
        """Check if a HuggingFace token is configured for diarization."""
        from app.transcription.diarizer import diarization_runtime_available
        if not diarization_runtime_available():
            return {
                "name": "HuggingFace Token",
                "passed": True,
                "level": "warn",
                "message": "Voice based speaker labels are not included in this build.",
                "action": "Use the Full build to enable pyannote speaker diarization.",
            }
        hf_token = ""
        if self.config:
            try:
                hf_token = self.config.get("diarization", "hf_token")
            except (KeyError, TypeError):
                pass

        if hf_token:
            return {
                "name": "HuggingFace Token",
                "passed": True,
                "level": "warn",
                "message": "HuggingFace token is configured.",
                "action": None,
            }
        else:
            return {
                "name": "HuggingFace Token",
                "passed": False,
                "level": "warn",
                "message": "No HuggingFace token configured.",
                "action": "Set a token in Settings to enable speaker diarization.",
            }

    def check_pyannote_models(self):
        """Check if pyannote speaker diarization models are cached."""
        from app.transcription.diarizer import diarization_runtime_available
        if not diarization_runtime_available():
            return {
                "name": "Pyannote Models",
                "passed": True,
                "level": "warn",
                "message": "Pyannote is not included in this Compact build.",
                "action": "Use the Full build for voice based speaker labels.",
            }
        cache_dir = Path.home() / ".cache" / "huggingface" / "hub" / "models--pyannote--speaker-diarization-community-1"
        if cache_dir.exists():
            return {
                "name": "Pyannote Models",
                "passed": True,
                "level": "warn",
                "message": "Speaker diarization model is cached.",
                "action": None,
            }
        else:
            return {
                "name": "Pyannote Models",
                "passed": False,
                "level": "warn",
                "message": "Speaker diarization model not found in cache.",
                "action": "Models will be downloaded when diarization is first used (requires HF token).",
            }

    def check_ffmpeg(self):
        """Check if ffmpeg is available to the app."""
        ffmpeg_path = find_ffmpeg()
        if ffmpeg_path:
            return {
                "name": "FFmpeg",
                "passed": True,
                "level": "warn",
                "message": f"FFmpeg found at {ffmpeg_path}.",
                "action": None,
            }
        else:
            return {
                "name": "FFmpeg",
                "passed": False,
                "level": "warn",
                "message": "FFmpeg not found on PATH or in common macOS install locations.",
                "action": 'Install FFmpeg for audio format conversion support: <a href="https://github.com/BtbN/FFmpeg-Builds">Download FFmpeg</a>',
            }

    def check_windows_version(self):
        """Check Windows version for compatibility."""
        if not is_windows():
            import platform
            if platform.system() == "Darwin":
                return {
                    "name": "Platform",
                    "passed": True,
                    "level": "info",
                    "message": "macOS supported; per-app capture is unavailable.",
                    "action": None,
                }
            return {
                "name": "Platform",
                "passed": False,
                "level": "info",
                "message": f"{platform.system()} is not a supported platform.",
                "action": "TalkTrack supports Windows and macOS.",
            }
        if is_windows_11():
            build = get_windows_build()
            return {
                "name": "Windows Version",
                "passed": True,
                "level": "info",
                "message": f"Windows 11 (Build {build}) - per-process audio capture supported.",
                "action": None,
            }
        else:
            build = get_windows_build()
            if build > 0:
                return {
                    "name": "Windows Version",
                    "passed": False,
                    "level": "info",
                    "message": f"Windows Build {build} - per-process audio capture requires Windows 11.",
                    "action": "System-wide loopback capture will be used instead.",
                }
            else:
                return {
                    "name": "Windows Version",
                    "passed": False,
                    "level": "info",
                    "message": "Not running on Windows.",
                    "action": "TalkTrack is designed for Windows. Some features may not work.",
                }
