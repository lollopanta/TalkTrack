from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont

from app.recording.recorder import RecordingState


class RecordingControls(QWidget):
    """Recording actions, microphone tools, state, and elapsed time."""

    record_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    mute_clicked = pyqtSignal()
    # Emitted when the user toggles the Test Mic button. True = enable live
    # mic monitor (no recording); False = disable. Off by default every launch.
    test_mic_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._muted = False
        self._blink_state = True
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._toggle_indicator)
        self.set_state(RecordingState.IDLE)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 6)
        layout.setSpacing(8)

        # Primary actions stay together and get enough width for their labels.
        primary_row = QHBoxLayout()
        primary_row.setSpacing(8)

        self.record_btn = QPushButton("Record")
        self.record_btn.setObjectName("recordButton")
        self.record_btn.setAccessibleName("Start recording")
        self.record_btn.setToolTip("Start a new recording from the selected audio sources.")
        self.record_btn.clicked.connect(self.record_clicked.emit)
        primary_row.addWidget(self.record_btn, 2)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setObjectName("pauseButton")
        self.pause_btn.setAccessibleName("Pause or resume recording")
        self.pause_btn.clicked.connect(self.pause_clicked.emit)
        primary_row.addWidget(self.pause_btn, 1)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("stopButton")
        self.stop_btn.setAccessibleName("Stop recording")
        self.stop_btn.setToolTip("Stop and save the current recording.")
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        primary_row.addWidget(self.stop_btn, 1)

        layout.addLayout(primary_row)

        # Microphone tools are secondary to starting and stopping a call.
        utility_row = QHBoxLayout()
        utility_row.setSpacing(8)

        self.mute_btn = QPushButton("Mute mic")
        self.mute_btn.setObjectName("muteButton")
        self.mute_btn.setAccessibleName("Mute microphone")
        self.mute_btn.setToolTip(
            "Mute only the microphone. System and app audio continue recording."
        )
        self.mute_btn.clicked.connect(self.mute_clicked.emit)
        utility_row.addWidget(self.mute_btn)

        self.test_mic_btn = QPushButton("Test microphone")
        self.test_mic_btn.setObjectName("testMicButton")
        self.test_mic_btn.setCheckable(True)
        self.test_mic_btn.setAccessibleName("Test microphone without recording")
        self.test_mic_btn.setToolTip(
            "Check microphone and system audio levels without creating a recording."
        )
        self.test_mic_btn.toggled.connect(self._update_test_mic_style)
        self.test_mic_btn.toggled.connect(self.test_mic_toggled.emit)
        utility_row.addWidget(self.test_mic_btn)
        utility_row.addStretch()
        layout.addLayout(utility_row)

        # Persistent text labels make recording state clear without relying on color.
        status_row = QHBoxLayout()
        status_row.setSpacing(8)

        self.recording_indicator = QLabel("")
        self.recording_indicator.setObjectName("recordingIndicator")
        self.recording_indicator.setFixedWidth(12)
        self.recording_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_row.addWidget(self.recording_indicator)

        self.state_label = QLabel("Ready")
        self.state_label.setObjectName("controlState")
        self.state_label.setAccessibleName("Recording status")
        status_row.addWidget(self.state_label)

        status_row.addStretch()

        self.timer_label = QLabel("00:00:00")
        self.timer_label.setObjectName("timerLabel")
        status_row.addWidget(self.timer_label)

        layout.addLayout(status_row)

    def set_state(self, state):
        self._state = state
        if state == RecordingState.IDLE:
            self.record_btn.setEnabled(True)
            self.record_btn.setText("Record")
            self.pause_btn.setEnabled(False)
            self.pause_btn.setText("Pause")
            self.stop_btn.setEnabled(False)
            self.mute_btn.setEnabled(False)
            self.set_muted(False)
            self.test_mic_btn.setEnabled(True)
            self.recording_indicator.setText("")
            self.state_label.setText("Ready")
            self.state_label.setProperty("state", "idle")
            self._blink_timer.stop()
        elif state == RecordingState.RECORDING:
            self.record_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.pause_btn.setText("Pause")
            self.stop_btn.setEnabled(True)
            self.mute_btn.setEnabled(True)
            self.test_mic_btn.setEnabled(False)
            self.state_label.setText("Recording")
            self.state_label.setProperty("state", "recording")
            self._blink_timer.start(500)
        elif state == RecordingState.PAUSED:
            self.record_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.pause_btn.setText("Resume")
            self.stop_btn.setEnabled(True)
            self.mute_btn.setEnabled(True)
            self.test_mic_btn.setEnabled(False)
            self.recording_indicator.setText("\u25a0")
            self.state_label.setText("Paused")
            self.state_label.setProperty("state", "paused")
            self._blink_timer.stop()
        elif state == RecordingState.STOPPING:
            self.record_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.mute_btn.setEnabled(False)
            self.test_mic_btn.setEnabled(False)
            self.recording_indicator.setText("")
            self.state_label.setText("Saving recording…")
            self.state_label.setProperty("state", "saving")
            self._blink_timer.stop()
        self.state_label.style().unpolish(self.state_label)
        self.state_label.style().polish(self.state_label)

    def update_time(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        self.timer_label.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def _update_test_mic_style(self, checked):
        if checked:
            self.test_mic_btn.setText("Testing mic…")
            self.test_mic_btn.setStyleSheet(
                "QPushButton#testMicButton { "
                "background-color: #a6e3a1; color: #1e1e2e; "
                "border: 1px solid #a6e3a1; font-weight: bold; }"
            )
        else:
            self.test_mic_btn.setText("Test microphone")
            self.test_mic_btn.setStyleSheet("")
        if getattr(self, "_state", RecordingState.IDLE) == RecordingState.IDLE:
            self.state_label.setText("Testing microphone" if checked else "Ready")

    def clear_test_mic(self):
        """Uncheck the Test Mic button without emitting test_mic_toggled.

        Used when MainWindow has already torn down the monitor (e.g. before
        starting a recording) and just needs the visual state to match.
        """
        self.test_mic_btn.blockSignals(True)
        self.test_mic_btn.setChecked(False)
        self.test_mic_btn.blockSignals(False)
        self._update_test_mic_style(False)

    def set_muted(self, muted):
        """Update the mute button visual state."""
        self._muted = bool(muted)
        if self._muted:
            self.mute_btn.setText("Unmute mic")
            self.mute_btn.setAccessibleName("Unmute microphone")
            self.mute_btn.setStyleSheet(
                "QPushButton#muteButton { "
                "background-color: #f38ba8; color: #1e1e2e; "
                "border: 1px solid #f38ba8; font-weight: bold; }"
            )
        else:
            self.mute_btn.setText("Mute mic")
            self.mute_btn.setAccessibleName("Mute microphone")
            self.mute_btn.setStyleSheet("")

    def _toggle_indicator(self):
        self._blink_state = not self._blink_state
        self.recording_indicator.setText("\u25cf" if self._blink_state else "")

    def reset_timer(self):
        self.timer_label.setText("00:00:00")
