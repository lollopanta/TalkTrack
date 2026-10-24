import logging
import platform
import shutil
import struct
import threading
import time
import numpy as np
import sounddevice as sd
import soundfile as sf
from pathlib import Path

from app.recording.chunk_writer import ChunkWriter
from app.audio.resampler import Resampler as _Resampler
from app.utils.audio_devices import MACOS_CORE_AUDIO_TAP_DEVICE
if platform.system() == "Windows":
    from app.recording.process_audio_capture import ProcessAudioCapture
else:
    ProcessAudioCapture = None

logger = logging.getLogger(__name__)


class AudioStream:
    """Captures audio from a single input device (mic) using sounddevice."""

    def __init__(self, device_index, sample_rate=16000, channels=1,
                 level_callback=None, sink=None):
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.channels = channels
        self._level_callback = level_callback
        self._sink = sink
        self._stream = None
        self._recording = False
        self._paused = False
        self._muted = False
        self._gain = 1.0

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.debug("Audio stream status: %s", status)
        if self._recording and not self._paused:
            chunk = indata.copy()
            if self._gain != 1.0:
                chunk *= self._gain
                np.clip(chunk, -1.0, 1.0, out=chunk)
            if self._muted:
                chunk.fill(0.0)
            if self._sink is not None:
                self._sink.put(chunk)
            if self._level_callback is not None:
                self._level_callback(chunk)

    def start(self):
        self._recording = True
        self._paused = False

        try:
            self._stream = sd.InputStream(
                device=self.device_index,
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=self._audio_callback,
                dtype="float32",
            )
            self._stream.start()
        except Exception as e:
            self._recording = False
            raise RuntimeError(f"Failed to start audio stream on device {self.device_index}: {e}")

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def set_muted(self, muted):
        """Mute or unmute the mic. Muted streams keep recording but write silence."""
        self._muted = bool(muted)

    def set_gain(self, gain):
        """Set the mic gain multiplier. Values outside [-1, 1] after multiplication are hard-clipped."""
        self._gain = float(gain)

    def stop(self):
        self._recording = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                logger.exception("Error closing audio stream on device %s",
                                 self.device_index)
            finally:
                self._stream = None

    @property
    def is_active(self):
        return self._recording and self._stream is not None


class LoopbackStream:
    """Capture system audio via WASAPI or a macOS virtual input device."""

    def __init__(self, device_name=None, sample_rate=16000, level_callback=None,
                 sink=None):
        self._device_name = device_name
        self._target_rate = sample_rate
        self._level_callback = level_callback
        self._sink = sink
        self._stream = None
        self._pa = None
        self._recording = False
        self._paused = False
        self._native_rate = None
        self._native_channels = None
        # Polyphase resampler built on start() once native_rate is known.
        # Stateful across callback invocations — the previous FFT-based
        # scipy.signal.resample call resampled each chunk in isolation,
        # producing discontinuities at chunk boundaries that sounded like
        # faint crackle during remote speech.
        self._resampler = None
        self._process = None
        self._reader_thread = None

    def _find_loopback_device(self):
        """Find the WASAPI loopback device matching the selected output."""
        import pyaudiowpatch as pyaudio
        self._pa = pyaudio.PyAudio()

        # Find WASAPI host API
        wasapi_idx = None
        for i in range(self._pa.get_host_api_count()):
            api = self._pa.get_host_api_info_by_index(i)
            if "WASAPI" in api["name"]:
                wasapi_idx = i
                break

        if wasapi_idx is None:
            raise RuntimeError("WASAPI host API not found")

        # Find loopback device
        target_name = self._device_name
        for loopback in self._pa.get_loopback_device_info_generator():
            if target_name and target_name in loopback["name"]:
                return loopback

        # If no match, use default output's loopback
        wasapi_info = self._pa.get_host_api_info_by_index(wasapi_idx)
        default_output = self._pa.get_device_info_by_index(
            wasapi_info["defaultOutputDevice"]
        )
        for loopback in self._pa.get_loopback_device_info_generator():
            if default_output["name"] in loopback["name"]:
                return loopback

        # Last resort: first available loopback device
        for loopback in self._pa.get_loopback_device_info_generator():
            return loopback

        raise RuntimeError("No WASAPI loopback device found")

    def start(self):
        self._recording = True
        self._paused = False

        try:
            if platform.system() == "Darwin":
                self._start_macos_input()
                return

            import pyaudiowpatch as pyaudio
            loopback_dev = self._find_loopback_device()
            self._native_rate = int(loopback_dev["defaultSampleRate"])
            self._native_channels = loopback_dev["maxInputChannels"]

            logger.info(
                "WASAPI loopback: %s (index=%d, rate=%d, ch=%d)",
                loopback_dev["name"], loopback_dev["index"],
                self._native_rate, self._native_channels,
            )

            self._resampler = _Resampler(self._native_rate, self._target_rate)

            self._stream = self._pa.open(
                format=pyaudio.paFloat32,
                channels=self._native_channels,
                rate=self._native_rate,
                input=True,
                input_device_index=loopback_dev["index"],
                frames_per_buffer=1024,
                stream_callback=self._callback,
            )
            self._stream.start_stream()
        except Exception:
            # _find_loopback_device creates self._pa before it can fail —
            # don't leak the PyAudio instance on any startup error.
            self._recording = False
            self.stop()
            raise

    def _start_macos_input(self):
        """Capture native system audio or a virtual input on macOS."""
        if self._device_name == MACOS_CORE_AUDIO_TAP_DEVICE:
            self._start_macos_core_audio_tap()
            return

        devices = sd.query_devices()
        matches = [
            (index, dev) for index, dev in enumerate(devices)
            if dev.get("name") == self._device_name
            and dev.get("max_input_channels", 0) > 0
        ]
        if not matches:
            raise RuntimeError(
                f"Virtual system-audio input '{self._device_name}' is unavailable. "
                "Install BlackHole and route system audio to it."
            )
        index, device = matches[0]
        self._native_rate = int(device["default_samplerate"])
        self._native_channels = min(2, int(device["max_input_channels"]))
        self._resampler = _Resampler(self._native_rate, self._target_rate)
        self._stream = sd.InputStream(
            device=index,
            samplerate=self._native_rate,
            channels=self._native_channels,
            callback=self._macos_callback,
            dtype="float32",
        )
        self._stream.start()
        logger.info("System audio input: %s (rate=%d, ch=%d)",
                    device["name"], self._native_rate, self._native_channels)

    @staticmethod
    def _read_exact(stream, length):
        chunks = []
        remaining = length
        while remaining:
            chunk = stream.read(remaining)
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _start_macos_core_audio_tap(self):
        """Start the bundled Core Audio tap helper and read its PCM stream."""
        helper = (Path(__file__).resolve().parents[2] / ".build"
                  / "TalkTrackAudioCapture.app" / "Contents" / "MacOS"
                  / "TalkTrackAudioCapture")
        if not helper.is_file():
            raise RuntimeError(
                "The native macOS audio helper is not built. Run ./start.command "
                "from the TalkTrack folder, then restart the app."
            )

        import subprocess
        self._process = subprocess.Popen(
            [str(helper)], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
        )
        process = self._process

        def _drain_stderr():
            for line in process.stderr:
                logger.info("Core Audio tap: %s", line.decode(errors="replace").rstrip())

        threading.Thread(target=_drain_stderr, daemon=True,
                         name="CoreAudioTapLog").start()
        header = self._read_exact(process.stdout, 12)
        if header is None:
            self._stop_macos_helper()
            raise RuntimeError(
                "macOS did not start system-audio capture. Check the macOS "
                "System Audio Recording permission and try again."
            )
        magic, sample_rate, channels, bits = struct.unpack("<4sIHH", header)
        if magic != b"TTCA" or channels < 1 or bits != 32:
            self._stop_macos_helper()
            raise RuntimeError("The native macOS audio helper returned an unsupported format.")
        self._native_rate = sample_rate
        self._native_channels = channels
        self._resampler = _Resampler(sample_rate, self._target_rate)
        logger.info("Native Core Audio tap started (rate=%d, channels=%d)",
                    sample_rate, channels)
        self._reader_thread = threading.Thread(
            target=self._read_macos_tap_audio, daemon=True,
            name="CoreAudioTapReader",
        )
        self._reader_thread.start()

    def _read_macos_tap_audio(self):
        pending = b""
        try:
            while self._recording and self._process and self._process.stdout:
                block = self._process.stdout.read(8192)
                if not block:
                    break
                payload = pending + block
                usable = len(payload) - (len(payload) % 4)
                pending = payload[usable:]
                if not usable:
                    continue
                samples = np.frombuffer(payload[:usable], dtype="<f4")
                if self._native_channels > 1:
                    samples = samples[:len(samples) - len(samples) % self._native_channels]
                    if samples.size == 0:
                        continue
                    samples = samples.reshape(-1, self._native_channels).mean(axis=1)
                samples = samples.astype(np.float32, copy=False)
                if self._resampler is not None:
                    samples = self._resampler.push(samples)
                if samples.size:
                    if self._sink is not None:
                        self._sink.put(samples)
                    if self._level_callback is not None:
                        self._level_callback(samples)
        except Exception:
            logger.exception("Error reading native Core Audio tap stream")
        finally:
            if self._recording:
                logger.warning("Native Core Audio tap stream ended unexpectedly")
                self._recording = False

    def _stop_macos_helper(self):
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
                process.wait(timeout=2)
            except Exception:
                logger.exception("Could not stop native macOS audio helper")
        if self._reader_thread is not None and self._reader_thread is not threading.current_thread():
            self._reader_thread.join(timeout=2)
        self._reader_thread = None
        for stream in (process.stdout, process.stderr):
            if stream:
                try:
                    stream.close()
                except OSError:
                    pass

    def _macos_callback(self, indata, frames, time_info, status):
        if status:
            logger.debug("System audio input status: %s", status)
        if not self._recording or self._paused:
            return
        chunk = indata.copy()
        if chunk.ndim > 1:
            chunk = chunk.mean(axis=1).astype(np.float32)
        if self._resampler is not None:
            chunk = self._resampler.push(chunk)
        if chunk.size == 0:
            return
        if self._sink is not None:
            self._sink.put(chunk)
        if self._level_callback is not None:
            self._level_callback(chunk)

    def _callback(self, in_data, frame_count, time_info, status):
        import pyaudiowpatch as pyaudio

        if self._recording and not self._paused:
            # Convert bytes to float32 numpy array
            chunk = np.frombuffer(in_data, dtype=np.float32).copy()
            chunk = chunk.reshape(-1, self._native_channels)

            # Downmix to mono
            if self._native_channels > 1:
                mono = chunk.mean(axis=1).astype(np.float32)
            else:
                mono = chunk.flatten()

            # Stateful polyphase resample. _Resampler carries odd-length
            # remainders across callbacks so there's no discontinuity at
            # chunk boundaries.
            if self._resampler is not None:
                mono = self._resampler.push(mono)

            if mono.size == 0:
                return (None, pyaudio.paContinue)

            if self._sink is not None:
                self._sink.put(mono)
            if self._level_callback is not None:
                self._level_callback(mono)

        return (None, pyaudio.paContinue)

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def stop(self):
        self._recording = False
        if self._process is not None:
            self._stop_macos_helper()
            self._stream = None
            return
        if self._stream:
            try:
                if platform.system() == "Darwin":
                    self._stream.stop()
                else:
                    self._stream.stop_stream()
                self._stream.close()
            except Exception:
                logger.exception("Error closing loopback stream")
            finally:
                self._stream = None
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                logger.exception("Error terminating PyAudio")
            finally:
                self._pa = None

    @property
    def is_active(self):
        return self._recording and self._stream is not None


def mix_wav_files(src_paths, out_path, weights, sample_rate,
                  normalize="always", block_frames=262144, target_peak=0.95):
    """Mix WAV files block-wise into out_path without loading them whole.

    Shorter sources are zero-padded to the longest. Two passes: the first
    finds the mix peak, the second writes the scaled mix — same result as
    the old whole-array math, bounded memory.

    normalize: "always" scales the peak to target_peak (when peak > 0),
    "if_clipping" scales only when the raw mix exceeds 1.0 (dual-mic
    convention), "never" writes the raw mix.
    """
    handles = [sf.SoundFile(str(p), mode="r") for p in src_paths]
    try:
        total = max(len(h) for h in handles)
        if total == 0:
            return None

        def mixed_blocks():
            for h in handles:
                h.seek(0)
            pos = 0
            while pos < total:
                n = min(block_frames, total - pos)
                mix = np.zeros(n, dtype=np.float32)
                for h, w in zip(handles, weights):
                    data = h.read(frames=n, dtype="float32", always_2d=False)
                    if data.ndim > 1:
                        data = data.mean(axis=1).astype(np.float32)
                    if len(data) < n:
                        data = np.pad(data, (0, n - len(data)))
                    mix += w * data
                pos += n
                yield mix

        peak = 0.0
        for mix in mixed_blocks():
            peak = max(peak, float(np.abs(mix).max()))
        scale = 1.0
        if normalize == "always" and peak > 0:
            scale = target_peak / peak
        elif normalize == "if_clipping" and peak > 1.0:
            scale = target_peak / peak

        with sf.SoundFile(str(out_path), mode="w", samplerate=sample_rate,
                          channels=1, subtype="PCM_16") as out:
            for mix in mixed_blocks():
                out.write(mix * scale if scale != 1.0 else mix)
    finally:
        for h in handles:
            try:
                h.close()
            except Exception:
                logger.exception("Error closing mix source")
    return str(out_path)


class DualAudioCapture:
    """Captures both microphone and system audio simultaneously."""

    def __init__(self, mic_device=None, loopback_device=None, sample_rate=16000,
                 capture_mode="legacy", app_pids=None, mic_device_2=None):
        self.sample_rate = sample_rate
        self.mic_device = mic_device
        self.mic_device_2 = mic_device_2
        self.loopback_device = loopback_device
        self.mic_stream = None
        self.mic_stream_2 = None
        self.system_stream = None
        self._recording = False
        self._start_time = None
        self._elapsed = 0
        self.capture_mode = capture_mode
        self.app_pids = app_pids or []
        self._mic_level_callback = None
        self._system_level_callback = None
        # Silence detection on system audio — guarded by mic activity.
        # If the user is talking (mic RMS > threshold) anywhere inside the
        # silence window, the silence timer resets. Prevents auto-stop
        # during a monologue when the remote is muted or on dead air.
        self._silence_threshold = 0.005  # RMS below this = silence
        self._silence_duration = 30  # seconds of silence before firing
        self._silence_callback = None
        self._silent_since = None  # timestamp when silence started
        self._silence_fired = False  # only fire once per silence stretch
        self._last_mic_active_time = None  # updated from mic callbacks
        self._muted = False
        self.mic_gain = 1.0
        self._pid_lost_callback = None
        self._capture_lost_callback = None
        self._capture_status = None
        # Wall-clock capture start per stream (time.monotonic). The system
        # side can start ~1s before the mic (per-app COM activation); the
        # mic writers get a leading-silence prepad at release so t=0 matches
        # wall-clock across files.
        self._mic_start_ts = None
        self._system_start_ts = None
        # ChunkWriters per track, keyed "mic"/"mic2"/"system". Owned here,
        # not by the streams — streams only put() into their sink.
        self._writers = {}

    def set_capture_event_callbacks(self, pid_lost=None, capture_lost=None):
        """Register callbacks for ProcessAudioCapture events (per-app mode only)."""
        self._pid_lost_callback = pid_lost
        self._capture_lost_callback = capture_lost

    def set_level_callbacks(self, mic_callback, system_callback):
        """Set callbacks to receive audio level data from each channel."""
        self._mic_level_callback = mic_callback
        self._system_level_callback = system_callback

    def set_muted(self, muted):
        """Mute or unmute all microphone streams in this capture session."""
        self._muted = bool(muted)
        if self.mic_stream is not None:
            self.mic_stream.set_muted(self._muted)
        if self.mic_stream_2 is not None:
            self.mic_stream_2.set_muted(self._muted)

    def set_gain(self, gain):
        """Set the mic gain multiplier for all microphone streams in this capture session."""
        self.mic_gain = float(gain)
        if self.mic_stream is not None:
            self.mic_stream.set_gain(self.mic_gain)
        if self.mic_stream_2 is not None:
            self.mic_stream_2.set_gain(self.mic_gain)

    @property
    def is_muted(self):
        return self._muted

    def set_silence_detection(self, threshold, duration, callback):
        """Configure silence detection on the system audio stream.

        Args:
            threshold: RMS level below which audio counts as silence.
            duration: Seconds of continuous silence before callback fires.
            callback: Called (with silence duration) when silence threshold met.
        """
        self._silence_threshold = threshold
        self._silence_duration = duration
        self._silence_callback = callback
        self._silent_since = None
        self._silence_fired = False

    def start(self, output_dir):
        """Start recording both mic and system audio."""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "DualAudioCapture.start: mic_device=%s, loopback_device=%s, "
            "capture_mode=%s",
            self.mic_device, self.loopback_device, self.capture_mode,
        )

        # System audio capture. In per-app mode with PIDs, use ProcessAudioCapture.
        # Otherwise use WASAPI loopback if a device is set.
        # Note: system capture activates BEFORE mic capture so a total per-app
        # failure raises before the mic stream is opened.
        self.system_stream = None
        self._capture_status = None
        self._mic_start_ts = None
        self._system_start_ts = None
        self._writers = {}

        def _system_cb(chunk):
            if self._system_level_callback is not None:
                self._system_level_callback(chunk)
            self._check_silence(chunk)

        if self.capture_mode == "per_app" and self.app_pids:
            writer = ChunkWriter(self.output_dir / "system_audio.wav",
                                 self.sample_rate)
            self.system_stream = ProcessAudioCapture(
                pids=self.app_pids,
                sample_rate=self.sample_rate,
                level_callback=_system_cb,
                pid_lost_callback=self._pid_lost_callback,
                capture_lost_callback=self._capture_lost_callback,
                sink=writer,
            )
            status = self.system_stream.start()
            self._capture_status = status
            if status["active"] == 0:
                self.system_stream = None
                writer.abort()
                raise RuntimeError(
                    f"Per-app capture failed for all selected apps: {status['failures']}"
                )
            self._writers["system"] = writer
            writer.release(prepad_frames=0)
            self._system_start_ts = time.monotonic()
        elif self.loopback_device is not None:
            writer = None
            try:
                if (platform.system() == "Darwin"
                        and self.loopback_device == MACOS_CORE_AUDIO_TAP_DEVICE):
                    device_name = MACOS_CORE_AUDIO_TAP_DEVICE
                else:
                    dev_info = sd.query_devices(self.loopback_device)
                    device_name = dev_info.get("name", "")
                logger.info("System audio: looking for loopback of '%s'", device_name)

                writer = ChunkWriter(self.output_dir / "system_audio.wav",
                                     self.sample_rate)
                self.system_stream = LoopbackStream(
                    device_name=device_name,
                    sample_rate=self.sample_rate,
                    level_callback=_system_cb,
                    sink=writer,
                )
                self.system_stream.start()
                self._writers["system"] = writer
                writer.release(prepad_frames=0)
                self._system_start_ts = time.monotonic()
            except Exception as e:
                logger.error("Failed to start system audio capture: %s", e)
                self.system_stream = None
                if writer is not None:
                    writer.abort()
        else:
            logger.warning("No system audio device selected")

        # Wrap the outer mic level callback so every chunk also updates
        # _last_mic_active_time for the silence-guard check.
        def _mic_cb(chunk):
            self._note_mic_activity(chunk)
            if self._mic_level_callback is not None:
                self._mic_level_callback(chunk)

        # Microphone capture (sounddevice). A mic failure must not orphan the
        # already-running system capture (COM clients / PyAudio / mixer thread).
        # Single mic streams straight to mic_audio.wav; dual mics stream to
        # per-mic temps that stop() mixes and removes.
        dual_mic = self.mic_device is not None and self.mic_device_2 is not None
        try:
            if self.mic_device is not None:
                mic1_name = "mic1_raw.wav" if dual_mic else "mic_audio.wav"
                writer = ChunkWriter(self.output_dir / mic1_name,
                                     self.sample_rate)
                self._writers["mic"] = writer
                self.mic_stream = AudioStream(
                    device_index=self.mic_device,
                    sample_rate=self.sample_rate,
                    channels=1,
                    level_callback=_mic_cb,
                    sink=writer,
                )
                self.mic_stream.start()
                self._mic_start_ts = time.monotonic()
                writer.release(self._alignment_prepad_frames(self._mic_start_ts))
                if self._muted:
                    self.mic_stream.set_muted(True)
                if self.mic_gain != 1.0:
                    self.mic_stream.set_gain(self.mic_gain)
                logger.info("Mic stream started on device %s", self.mic_device)
            else:
                logger.warning("No mic device selected")

            # Second microphone capture (optional)
            if self.mic_device_2 is not None:
                mic2_name = "mic2_raw.wav" if dual_mic else "mic_audio.wav"
                writer2 = ChunkWriter(self.output_dir / mic2_name,
                                      self.sample_rate)
                self._writers["mic2"] = writer2
                self.mic_stream_2 = AudioStream(
                    device_index=self.mic_device_2,
                    sample_rate=self.sample_rate,
                    channels=1,
                    level_callback=_mic_cb,
                    sink=writer2,
                )
                self.mic_stream_2.start()
                writer2.release(self._alignment_prepad_frames(time.monotonic()))
                if self._muted:
                    self.mic_stream_2.set_muted(True)
                if self.mic_gain != 1.0:
                    self.mic_stream_2.set_gain(self.mic_gain)
                logger.info("Mic stream 2 started on device %s", self.mic_device_2)
        except Exception:
            self._stop_streams_quietly()
            raise

        self._recording = True
        self._start_time = time.time()

    def _stop_streams_quietly(self):
        """Best-effort stop of every started stream and writer; never raises.

        Only used on start() failure — writers are aborted (files deleted),
        matching the old design where nothing was saved before stop().
        """
        for stream in (self.mic_stream, self.mic_stream_2, self.system_stream):
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    logger.exception("Error stopping stream during cleanup")
        self.mic_stream = None
        self.mic_stream_2 = None
        self.system_stream = None
        for writer in self._writers.values():
            try:
                writer.abort()
            except Exception:
                logger.exception("Error aborting writer during cleanup")
        self._writers = {}

    def pause(self):
        if self.mic_stream:
            self.mic_stream.pause()
        if self.mic_stream_2:
            self.mic_stream_2.pause()
        if self.system_stream:
            self.system_stream.pause()
        if self._start_time:
            self._elapsed += time.time() - self._start_time
            self._start_time = None
        self._silent_since = None  # don't count paused time as silence

    def resume(self):
        if self.mic_stream:
            self.mic_stream.resume()
        if self.mic_stream_2:
            self.mic_stream_2.resume()
        if self.system_stream:
            self.system_stream.resume()
        self._start_time = time.time()
        self._silent_since = None
        self._silence_fired = False  # allow re-detection after resume

    def stop(self):
        """Stop recording and return paths to saved audio files.

        Tracks were streamed to disk during capture; this closes the writers
        and assembles mic_audio/combined block-wise. Every step is
        individually guarded: a failing device (e.g. mic unplugged mid-call)
        or file write must not prevent stopping the other streams or saving
        the other tracks.
        """
        self._recording = False
        if self._start_time:
            self._elapsed += time.time() - self._start_time
            self._start_time = None

        results = {"mic": None, "system": None, "combined": None}

        # Stop all streams first so nothing keeps capturing while we finish.
        for label, stream in (("mic", self.mic_stream),
                              ("mic 2", self.mic_stream_2),
                              ("system", self.system_stream)):
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    logger.exception("Failed to stop %s stream", label)

        # Close writers — drains queues, deletes zero-frame files.
        for key, writer in self._writers.items():
            try:
                writer.stop()
            except Exception:
                logger.exception("Failed to close %s writer", key)
        self._writers = {}

        mic_path = self.output_dir / "mic_audio.wav"
        sys_path = self.output_dir / "system_audio.wav"

        # Dual-mic: mix the per-mic temps into mic_audio.wav, drop the temps.
        try:
            temps = [p for p in (self.output_dir / "mic1_raw.wav",
                                 self.output_dir / "mic2_raw.wav")
                     if p.exists()]
            if temps:
                mix_wav_files(temps, mic_path, weights=[1.0] * len(temps),
                              sample_rate=self.sample_rate,
                              normalize="if_clipping")
                for p in temps:
                    p.unlink(missing_ok=True)
        except Exception:
            logger.exception("Failed to mix mic tracks")

        if mic_path.exists():
            results["mic"] = str(mic_path)
        if sys_path.exists():
            results["system"] = str(sys_path)

        # Combined track for transcription: equal-weight mix normalized to
        # 0.95 peak; a lone track is copied verbatim (old behavior).
        try:
            combined_path = self.output_dir / "combined_audio.wav"
            if results["mic"] and results["system"]:
                mix_wav_files([mic_path, sys_path], combined_path,
                              weights=[0.5, 0.5],
                              sample_rate=self.sample_rate,
                              normalize="always")
                results["combined"] = str(combined_path)
            elif results["mic"] or results["system"]:
                shutil.copyfile(results["mic"] or results["system"],
                                str(combined_path))
                results["combined"] = str(combined_path)
        except Exception:
            logger.exception("Failed to create combined audio")

        return results

    # Offsets beyond this are clock anomalies, not real startup skew.
    _MAX_ALIGNMENT_SECONDS = 30.0

    def _alignment_prepad_frames(self, stream_start_ts):
        """Leading-silence frames for a mic track starting after the system.

        The system side activates first (per-app COM activation can cost
        ~1s); prepadding the mic keeps t=0 wall-clock-aligned across files.
        """
        if self._system_start_ts is None or stream_start_ts is None:
            return 0
        delta = stream_start_ts - self._system_start_ts
        if delta <= 0:
            return 0
        if delta > self._MAX_ALIGNMENT_SECONDS:
            logger.warning("Implausible stream start offset %.1fs — skipping alignment", delta)
            return 0
        return int(round(delta * self.sample_rate))

    def _note_mic_activity(self, chunk):
        """Called from wrapped mic callbacks. Stamps mic activity.

        Only chunks whose RMS exceeds the silence threshold count as
        activity — ambient noise floor under the threshold is ignored.
        """
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        if rms >= self._silence_threshold:
            self._last_mic_active_time = time.time()

    def _check_silence(self, chunk):
        """Check system audio chunk for silence, fire callback if sustained.

        Mic-aware: if the mic was active within the silence window, reset
        the silence anchor. The callback never fires while the user is
        talking, even if the remote side is dead air.
        """
        if not self._silence_callback or self._silence_fired:
            return
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        now = time.time()
        mic_recent = (
            self._last_mic_active_time is not None
            and (now - self._last_mic_active_time) < self._silence_duration
        )
        if rms < self._silence_threshold and not mic_recent:
            if self._silent_since is None:
                self._silent_since = now
            elif now - self._silent_since >= self._silence_duration:
                self._silence_fired = True
                self._silence_callback(now - self._silent_since)
        else:
            self._silent_since = None

    def system_audio_received(self):
        """True once the system stream has produced any non-silent audio.

        Only meaningful for per-app capture (streams exposing
        has_received_audio). Legacy loopback and no-system configurations
        return True so callers never warn.
        """
        stream = self.system_stream
        if stream is None or not hasattr(stream, "has_received_audio"):
            return True
        return bool(stream.has_received_audio)

    def get_elapsed_time(self):
        """Return elapsed recording time in seconds."""
        if self._start_time:
            return self._elapsed + (time.time() - self._start_time)
        return self._elapsed

    @property
    def is_recording(self):
        return self._recording
