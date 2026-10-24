# TalkTrack — Codex Instructions

TalkTrack is a Windows desktop application for recording, transcribing, diarizing, and searching call audio. It uses PyQt6, sounddevice/WASAPI, faster-whisper, pyannote.audio, and optional cloud/local AI providers.

## Project map

- `main.py`: application entry point and startup configuration.
- `app/recording/`: audio capture, streaming writers, and recording lifecycle.
- `app/transcription/`: transcription and speaker diarization workers.
- `app/ai/`: AI providers, summarization, transcript chat, and embeddings.
- `app/ui/`: PyQt6 interface.
- `app/utils/`: configuration, dependency checks, device/platform helpers.
- `tests/`: unittest-based tests run with pytest.

## Working in this repository

- Follow the applicable project skill before editing a subsystem. Skills live in `.agents/skills/` and Codex can load them on demand.
- Preserve existing architecture and the documented invariants; consult the subsystem skill before changing its behavior.
- For non-UI logic, use the repository's test-first convention. For PyQt UI changes, use an import smoke test or a focused test that does not construct real widgets unless the task calls for it.
- Run tests with the global `python -m pytest tests/ -v`; do not use bare `uv run` because it may sync and replace the configured PyTorch build. If uv is needed, use `--no-sync`.
- Keep `requirements.txt`, `pyproject.toml`, and `uv.lock` aligned when dependencies change.
- The app targets Windows. Hardware- and Windows-specific behavior may require mocks or Windows smoke testing; do not assume it can be exercised on other platforms.

## Project skills

- `talktrack-ways-of-working`: GitHub, testing, repository workflow, and development gotchas.
- `talktrack-audio-pipeline`: capture callback order, mute/gain, disk streaming, mixing, and recording lifecycle.
- `talktrack-per-app-audio-capture`: Windows 11 process-loopback and COM invariants.
- `talktrack-transcription-pipeline`: worker lifecycle, session binding, job queue, diarization, and model caches.
- `talktrack-ai-providers`: provider configuration, context limits, SDK timeouts, embeddings, and error handling.
- `talktrack-ui-patterns`: PyQt layout, widgets, meters, tray, and QSS conventions.
- `talktrack-packaging-and-launch`: uv/pip setup, CPU/CUDA dependencies, Windows launch, and CI.
