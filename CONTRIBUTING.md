# Contributing

Thanks for helping make local desktop intelligence more useful. Start with a focused bug report, a reproducible benchmark, or a small improvement. Discuss substantial behavior changes in an issue first.

## Development

Windows 10/11 x64 and Python 3.11+ are required for the desktop application.

```powershell
git clone https://github.com/simdsz1z/observer-ai.git
cd observer-ai
uv sync --locked --extra dev
uv run pytest -q
uv run python scripts/preview_ui.py
uv run python -m observer
```

Unit tests and UI previews use synthetic evidence. Model weights, a GPU, and desktop recording are not needed for unit tests. Optional real inference requires `scripts/setup_observer.py`, FFmpeg/ffprobe, and then `scripts/test_observer.py --video`. Build the native helper with `scripts/build_observer_runtime.py` using MSVC Build Tools; see [runtime details](docs/resident-runtime.md).

## Changes worth reviewing

- Explain the user-visible problem, the resulting behavior, and how you verified it.
- Preserve consent, cancellation, bounded queues, and the distinction between native facts and model interpretations.
- Use synthetic data in fixtures and screenshots. Never commit recorded desktop content, local memory, credentials, weights, or runtime downloads.
- Add focused tests for behavior changes. Include hardware, settings, clip counts, and skips in performance claims.
- Keep contributions respectful and technical. Critique ideas and code, not people.

Application contributions are provided under this project's MIT license. Third-party dependencies retain their licenses.
