"""Background download of faster-whisper model files."""

from PyQt6.QtCore import QThread, pyqtSignal


class WhisperModelDownloadWorker(QThread):
    completed = pyqtSignal(str, str)  # model size, local path
    failed = pyqtSignal(str, str)  # model size, error message

    def __init__(self, model_size, parent=None):
        super().__init__(parent)
        self.model_size = model_size

    def run(self):
        try:
            from faster_whisper.utils import download_model

            path = download_model(self.model_size)
            self.completed.emit(self.model_size, str(path))
        except Exception as exc:
            self.failed.emit(self.model_size, str(exc))
