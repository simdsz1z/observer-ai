# Current performance verification

54 automated checks pass. Resident native Qwen measured 1.330 sec per one-second real-video clip and 1.279 sec per live-desktop clip on average. Live busy skips decreased from 80.9% to 17.2%, with 46/58 clips completed in 60.78 seconds. Actual device and same-worker PID are recorded per observation. See [resident-runtime.md](resident-runtime.md). The measurements below describe earlier implementations and remain historical.

# Live video update

44 tests passed after adding continuous frame buffering and native video inference. Real eight-frame Qwen video inference recognized the red-error to green-success transition in 14,438 ms processing time. Video capture/analysis is delayed and sampled; queued clips can be replaced. See [live-video.md](live-video.md) for scope, verification, and limits. Prior snapshot-only measurements below are historical.

# Validation results

## Current local-Qwen version (0.2)

Validated on 2026-10-17. `python -X faulthandler -m pytest -q`: **37 passed in 1.41 seconds**, exit code 0.

In addition to the earlier baseline below, checks cover strict local-model output validation, score limits, preserving raw evidence during asynchronous updates, preventing a missing model from silently becoming raw-only recording, bounded priority queues, active subprocess cancellation/reaping, temporary-file cleanup after failure, interpretation redaction and export provenance, single-frame evidence limits, and the recorder → inference → memory → export path. Local-Qwen privacy checks also confirm that excluded, password-protected, and idle frames never reach inference. These automated recorder tests use deterministic evidence sources.

### Real model test

The official **Qwen3-VL-2B-Instruct Q4_K_M** model and **Q8_0 vision encoder** were downloaded and SHA-256 verified. The installed local runtime is **llama.cpp b11669, Windows x64 Vulkan**. No AI API or cloud inference was used.

`python scripts/test_observer.py` ran actual inference on the generated error screen. The latest run:

- Classified the visible activity as `debugging`.
- Read the exact visible message: `TypeError: Cannot read properties of undefined (reading 'id')` and its visible stack location.
- Returned schema-valid structured output, with unknown task context kept null and unsupported single-frame changes removed by the evidence guard.
- Measured **5,172.0 ms** for local analysis including runtime startup. The earlier successful accelerated run took **12,516.0 ms**; caches and other machine activity affect timing.
- Saved the interpretation with its observation ID/model/latency and included it in a context ZIP.
- Left **zero temporary image files** after completion.
- Captured **zero desktop pixels**; the test image contains only generated sample content.

The image, actual result and exported context are in `qa/local-observer/sample-screen.png`, `result.json`, and `sample-context.zip`. They are synthetic diagnostic artifacts, not the user's activity history.

An earlier real run exposed an out-of-range importance score; this was rejected rather than persisted as a valid result. The generation schema now constrains the numeric values directly. The small model can still overstate causal actions in descriptions; interpretations remain explicitly fallible. A successful error-screen test does not establish accuracy across arbitrary applications.

Default model settings now request all text layers on GPU and enable vision acceleration only with at least 3 GiB free NVIDIA memory. Otherwise vision uses CPU; runtime GPU failures retry fully on CPU. The ordinary synthetic storage benchmark does not measure this model path. No GPU-memory peak, sustained model resource use, or ten-hour stability claim is made.

### Remaining validation

Live desktop capture with local Qwen, application-specific accessibility coverage, multi-monitor/DPI changes, long-session stability, sustained CPU/RAM/VRAM consumption, event accuracy, and handoff of real user evidence still need the manual plan. The app remains paused until the user explicitly enables the updated capture consent.

## Earlier raw-only baseline (0.1)

Validated on 2026-10-17 on the Windows development machine using Python 3.12.11, PySide6 Essentials 6.12.0, MSS 10.2.0, Pillow 12.3.0, psutil 7.2.2, UIAutomation 2.0.29, and pytest 9.1.1. Dependency versions and hashes are recorded in `uv.lock`.

## Automated checks

`python -X faulthandler -m pytest -q`: **22 passed in 1.10 seconds**, exit code 0.

Checks cover default paused behavior, consent UI state, foreground changes, duplicate suppression, stop behavior, password exclusion, app/title exclusion, idle suspension, failed accessibility withholding images, edit-value avoidance, bounded label traversal, text redaction, SQL search escaping, chronology, export limits, current privacy rules applied to historical exports, safe evidence paths, frozen image exports, retention/deletion, saved-response traceability, and an offscreen UI handoff flow.

The core recorder tests use deterministic evidence sources. They do not record the user's desktop.

`python scripts/check_integrations.py`: **passed**. Real Win32 bindings and UI Automation read the check's own hidden standard control; its name and password flag matched expectations. MSS enumerated three displays. **Zero desktop pixels were captured.**

`python scripts/preview_ui.py`: **passed**. Overview, timeline, handoff, and settings screenshots were generated from the application's own widgets with synthetic data. Visual review identified and corrected missing offscreen fonts and the settings palette. Previews are in the ignored `qa/` directory. This does not validate live desktop screenshots.

`python -m compileall -q observer scripts`: **passed**. The CLI help command also exited successfully.

The native Windows application was launched successfully with its monitoring paused. Its window was responsive and the local database contained zero sessions and zero observations at launch verification.

## Measured synthetic pipeline

`python scripts/benchmark.py`, latest validation run:

| Measurement | Result |
| --- | ---: |
| Synthetic observations persisted | 1,000 |
| SQLite writes | 0.6241 s |
| Write throughput | 1,602.2 observations/s |
| Thumbnail conversion and frame comparison, mean of 300 iterations | 2.052 ms |
| Context assembly and ZIP export | 8.523 ms |
| Events included from latest 100, under the text budget | 64 |
| Process resident memory at measurement | 35.0 MB |
| Total benchmark duration | 1.264 s |

These numbers measure a short synthetic workload. They are not live capture throughput, UIA latency, normal GUI memory, idle CPU, VRAM use, accuracy, or stability claims. Timing varies with workload and the machine's other activity.

## Remaining validation

Live screen capture, real application accessibility coverage, password detection across providers, multi-monitor/DPI changes, overlap masking on actual desktop pixels, sleep/lock recovery, sustained resource usage, event accuracy, and website handoff with real evidence still require the manual plan. No live benchmark or website upload was performed. This earlier raw-only baseline did not call a model; current real local-Qwen results are documented above.
