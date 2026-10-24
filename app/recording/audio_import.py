"""Prepare user-supplied audio as a normal TalkTrack recording session."""

import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.utils.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)


class _ImportCancelled(Exception):
    pass


class AudioImportWorker(QThread):
    """Copy and normalize an audio file off the GUI thread."""

    imported = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, source_path, recordings_dir, parent=None):
        super().__init__(parent)
        self.source_path = Path(source_path).expanduser().resolve()
        self.recordings_dir = Path(recordings_dir).expanduser()
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def _check_cancelled(self):
        if self._cancel_requested:
            raise _ImportCancelled()

    def run(self):
        session_dir = None
        try:
            if not self.source_path.is_file():
                raise FileNotFoundError(f"Audio file not found: {self.source_path}")
            self._check_cancelled()

            self.recordings_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now()
            session_dir = self.recordings_dir / (
                f"imported_{timestamp:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"
            )
            session_dir.mkdir()

            audio_path, duration = self._prepare_audio(session_dir)
            metadata = {
                "id": session_dir.name,
                "directory": str(session_dir.resolve()),
                "name": self.source_path.stem,
                "started_at": timestamp.isoformat(),
                "stopped_at": timestamp.isoformat(),
                "duration": duration,
                "audio_files": {"combined": str(audio_path.resolve())},
                "imported": True,
                "source_name": self.source_path.name,
            }
            atomic_write_json(session_dir / "metadata.json", metadata, indent=2)
            self.imported.emit(metadata)
        except _ImportCancelled:
            if session_dir is not None:
                shutil.rmtree(session_dir, ignore_errors=True)
        except Exception as exc:
            logger.exception("Failed to import audio file %s", self.source_path)
            if session_dir is not None:
                shutil.rmtree(session_dir, ignore_errors=True)
            self.error.emit(str(exc))

    def _prepare_audio(self, session_dir):
        """Preserve formats libsndfile can read; decode others to PCM WAV."""
        import soundfile as sf

        try:
            info = sf.info(str(self.source_path))
            if info.frames <= 0 or info.samplerate <= 0:
                raise ValueError("The selected file contains no readable audio.")
            if info.channels == 1:
                destination = session_dir / self.source_path.name
                self._copy_source(destination)
                return destination, float(info.duration)
        except (RuntimeError, ValueError, OSError):
            pass
        return self._decode_to_wav(session_dir)

    def _copy_source(self, destination):
        with self.source_path.open("rb") as source, destination.open("wb") as target:
            while True:
                self._check_cancelled()
                block = source.read(1024 * 1024)
                if not block:
                    break
                target.write(block)
        shutil.copystat(self.source_path, destination)

    def _decode_to_wav(self, session_dir):
        """Use faster-whisper's bundled PyAV decoder for compressed formats."""
        import av
        import soundfile as sf

        destination = session_dir / "audio.wav"
        sample_rate = 16000
        total_frames = 0
        container = av.open(str(self.source_path))
        try:
            audio_streams = [stream for stream in container.streams if stream.type == "audio"]
            if not audio_streams:
                raise ValueError("The selected file does not contain an audio track.")

            resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)
            with sf.SoundFile(
                str(destination), mode="w", samplerate=sample_rate,
                channels=1, subtype="PCM_16",
            ) as output:
                for frame in container.decode(audio_streams[0]):
                    self._check_cancelled()
                    for converted in resampler.resample(frame):
                        samples = converted.to_ndarray().reshape(-1)
                        output.write(samples)
                        total_frames += len(samples)
                for converted in resampler.resample(None):
                    samples = converted.to_ndarray().reshape(-1)
                    output.write(samples)
                    total_frames += len(samples)
        finally:
            container.close()

        if total_frames <= 0:
            raise ValueError("No audio samples could be decoded from the selected file.")
        return destination, total_frames / sample_rate
