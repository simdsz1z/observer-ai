# Continuous sampled screen video

The user requested continuous live-screen observation. The original single-screenshot observer did not implement temporal video input. Live video is now the default; it is not an external webcam, a remote stream, or a full desktop broadcast.

`Recorder` continuously captures privacy-checked active-window frames at the configured capture interval (default one second). `ClipBuffer` normalizes pixels to 960×672, retains at most eight frames by default, and creates a chronological `ScreenClip`. Raw UI change deduplication does not discard video frames. Protected windows, password detection, inaccessible visual evidence, focus races, capture failures, and long timing gaps clear partial clips. Passive viewing continues without input; other capture modes retain idle suspension.

Each completed clip creates a `screen_video` observation containing the original capture timestamps, application/window metadata, measured average FPS, and source span in `observer_input`. Each frame has already passed capture exclusions and text metadata redaction. Rebuilding an export applies current exclusions to every frame's metadata, not only the final window, and redacts nested video metadata.

`VisionWorker` keeps at most two waiting clips plus its current inference; it replaces older waiting clips on overflow and marks their observations `skipped_busy`. Its normal result storage/export path is shared with single-image analysis. The UI displays captured frames, partial-clip occupancy, completed/skipped/queued analyses, and age of the latest interpreted frame. Busy machines do not have guaranteed complete temporal coverage.

`LocalQwenObserver` encodes a temporary H.264 MP4 with FFmpeg using owned RGB bytes, then invokes the pinned llama.cpp executable with `--video`, `--video-fps`, `--video-timestamp-interval 1000`, and the discovered FFmpeg directory. This exercises the runtime's native video loader, rather than sending independent screenshots or a contact sheet. Original inter-frame capture times are supplied as metadata; video playback uses average FPS. The video context is 8,192 tokens with 256 vision tokens per frame. Numeric schema validation and user-goal restrictions still apply. Multi-frame evidence permits change descriptions without requiring a prior interpretation. Generated explanations can still invent causes; a visible transition does not prove a fix or a click.

Temporary MP4/prompt files are removed in `finally`; owned stale MP4s are cleaned on startup. Pause cancels active inference and discards partial/waiting clips. No persistent video archive or video export is added. Model weights, decoded frames, encoding buffers, and inference consume local CPU/GPU/RAM. No HTTP inference service or cloud AI API is used.

## Verification

`python scripts/test_observer.py --video --output-dir qa/local-video` exercised real Qwen on eight generated frames: first a red TypeError panel, then a green BUILD SUCCEEDED panel. The model reported both states and the transition, with `observer_input.mode=video`, eight frames, and 1 FPS. Processing took 14,438 ms in this run, excluding live collection time. The result was persisted and included in a website context export; temporary inference files were removed. The model also inferred execution, which the clip did not prove: output remains fallible.

The unit/integration suite checks continuous unchanged-frame delivery, bounded buffers and queues, gap resets, native video arguments, failure cleanup, temporal evidence guards, nested export privacy, settings migration, cancellation, and the existing raw evidence behavior. It does not establish ten-hour stability or real-world accuracy.

Compatibility evidence: the installed b11669 CLI advertises `--video`, video FPS/timestamp controls, and FFmpeg discovery. [The pinned runtime source](https://github.com/ggml-org/llama.cpp/blob/b11669/tools/mtmd/mtmd-cli.cpp) loads video through libmtmd's native media loader. [FFmpeg's official download page](https://ffmpeg.org/download.html) links Windows builds; modern Gyan FFmpeg 8.0.1 was already installed here.
