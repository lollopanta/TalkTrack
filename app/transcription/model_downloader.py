"""Background download of faster-whisper model files."""

import threading
import time

from PyQt6.QtCore import QThread, pyqtSignal


class WhisperModelDownloadWorker(QThread):
    completed = pyqtSignal(str, str)  # model size, local path
    failed = pyqtSignal(str, str)  # model size, error message
    progress = pyqtSignal(str, int, int)  # model size, bytes downloaded, total bytes

    def __init__(self, model_size, parent=None):
        super().__init__(parent)
        self.model_size = model_size
        self._progress_lock = threading.Lock()
        self._last_progress_time = 0.0
        self._last_progress_percent = -1

    def _emit_progress(self, downloaded, total):
        if total <= 0:
            return
        downloaded = max(0, min(int(downloaded), int(total)))
        percent = int(downloaded * 100 / total)
        now = time.monotonic()
        with self._progress_lock:
            if (
                percent == self._last_progress_percent
                and now - self._last_progress_time < 0.25
            ):
                return
            self._last_progress_time = now
            self._last_progress_percent = percent
        self.progress.emit(self.model_size, downloaded, int(total))

    def run(self):
        try:
            from faster_whisper.utils import _MODELS
            from huggingface_hub import snapshot_download
            from huggingface_hub.utils.tqdm import tqdm as HfTqdm

            repo_id = _MODELS.get(self.model_size)
            if not repo_id:
                raise ValueError(f"Unknown faster-whisper model: {self.model_size}")

            allow_patterns = [
                "config.json",
                "preprocessor_config.json",
                "model.bin",
                "tokenizer.json",
                "vocabulary.*",
            ]
            files = snapshot_download(
                repo_id,
                allow_patterns=allow_patterns,
                dry_run=True,
            )
            total_bytes = sum(
                item.file_size for item in files if item.will_download
            )
            self.progress.emit(self.model_size, 0, total_bytes)

            worker = self

            class _ProgressTqdm(HfTqdm):
                def __init__(self, *args, **kwargs):
                    self._reports_bytes = (
                        kwargs.get("name") == "huggingface_hub.snapshot_download"
                    )
                    self._downloaded_bytes = kwargs.get("initial", 0)
                    self._counter_lock = threading.Lock()
                    kwargs["disable"] = True
                    super().__init__(*args, **kwargs)

                def update(self, n=1):
                    result = super().update(n)
                    if self._reports_bytes:
                        with self._counter_lock:
                            self._downloaded_bytes += n
                            downloaded = self._downloaded_bytes
                        worker._emit_progress(downloaded, total_bytes)
                    return result

            path = snapshot_download(
                repo_id,
                allow_patterns=allow_patterns,
                tqdm_class=_ProgressTqdm,
            )
            if total_bytes:
                self._emit_progress(total_bytes, total_bytes)
            self.completed.emit(self.model_size, str(path))
        except Exception as exc:
            self.failed.emit(self.model_size, str(exc))
