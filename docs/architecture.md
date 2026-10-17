# Current resident runtime

The installed observer now keeps Qwen loaded across requests using the local native helper. Pause releases model resources and chat handoff frees the prior owner before loading another model. See [resident-runtime.md](resident-runtime.md). The older per-analysis CLI behavior described below applies only to fallback mode.

# Live screen video update

The default path is now continuous timestamped frame buffering → temporary MP4 → native Qwen video inference. See [live-video.md](live-video.md) for the current video architecture. The single-frame path described below remains available by disabling Live screen video. Video uses 8,192 context tokens, 256 image tokens per frame, up to two waiting clips, and preserves per-frame provenance in observer_input. Stream mode continues during passive viewing; snapshot/raw modes retain idle suspension.

# Architecture and data contract

## Pipeline

```text
Foreground metadata → exclusion check → bounded UIA read → password/focus check
    → permitted active-window pixels + overlap masking → focus check
    → text redaction → change/dedup selection → SQLite raw evidence
    → bounded priority queue → local Qwen3-VL process → schema validation + redaction
    → SQLite interpretation update, retaining the source observation ID
    → explicit context build → review → clipboard or local ZIP → user shares with website
    → user optionally pastes advice back into the local database
```

The visual observer uses Qwen3-VL-2B-Instruct Q4_K_M and its Q8_0 vision encoder through a pinned official llama.cpp executable. Input/output uses local files and process pipes. It does not require an HTTP server, localhost endpoint, websocket, cloud credentials, or internet after installation. The larger supervisor remains the user's chosen AI website, through manual evidence export.

## Components

| Module | Responsibility |
| --- | --- |
| `windows.py` | Read-only Win32 foreground metadata, visible-window bounds, idle time and DPI context |
| `accessibility.py` | Separate spawned process for bounded read-only UIA inspection; 0.8-second per-read timeout, 5-second startup limit and 10-second retry cooldown |
| `capture.py` | MSS active-window pixels, masks, resize and grayscale frame difference |
| `privacy.py` | Process/title exclusions and best-effort text redaction |
| `engine.py` | One sequential background sampling worker, stop gate, event selection and bounded status queue |
| `vision.py` | Bounded priority queue, real local Qwen inference, schema validation, CPU retry, cancellation and provenance |
| `sample.py` | Owned example image for real inference checks without desktop capture |
| `store.py` | SQLite WAL schema, synchronization, queries, retention, image path validation and deletion |
| `exporting.py` | Frozen, reviewable context packages and atomic ZIP writes |
| `ui.py` | PySide6 dashboard, recording indicator, timeline, handoff and settings |

The recorder samples at 1 Hz by default. A sequential worker prevents capture backlog; it does not queue raw frames. The status queue holds at most 32 messages. UIA is limited to 100 controls, five levels, 40 labels of 400 characters, and a 250 ms traversal budget, excluding time inside an individual COM call. The parent can terminate a provider exceeding the per-read deadline. It never requests edit values, TextPattern document contents, or clipboard contents.

Events are prioritized within each sample: window transition, new literal error text, changed labels, significant visual change (3% of thumbnail pixels changed by more than 20 grayscale levels), then a 60-second still-visible heartbeat. Changed text/images have a two-second storage cooldown. Window transitions can record immediately. Repeated visibility does not become a claim about repeated actions. Idle sampling suspends at 120 seconds since Windows' last input and checks again every three seconds.

Pausing sets a stop event immediately; in-flight samples check it before image and database persistence. The UI waits for the worker to stop before allowing data deletion/settings changes. No new samples are stored after a successful stop returns. Windows-native capture can still block unexpectedly; if the worker has not stopped within three seconds, the UI reports the pending stop and refuses to close the database beneath it.

Qwen has a separate worker with at most two waiting images. Error text receives higher priority than window switches and ordinary visual changes; when full, a lower-priority/older waiting job can be replaced and its event is marked `skipped_busy`. Default model starts are at least 20 seconds apart. Samples without visual evidence are marked explicitly. Screenshot archives are opt-in; local vision can operate without them, using temporary image/prompt files that are removed after inference, failure, or cancellation.

The runtime requests up to 99 text layers on GPU (all layers of this small model), four CPU threads, a 4,096-token context, 512 output tokens, and a 1,024-image-token limit. Vision encoding is accelerated only when the local NVIDIA memory probe reports at least 3 GiB free; otherwise it stays on CPU. The user can disable vision acceleration or choose fewer GPU layers. A GPU runtime failure retries with both text and vision on CPU for the rest of that session. A per-process timeout bounds inference. Model processes exit after each analysis to release their memory; this trades repeated load overhead for bounded resource ownership. Native runtime output is parsed and validated before entering memory. Unvalidated output is not treated as a completed observation. The upstream multimodal CLI is experimental, so its release is pinned and integration checks are necessary when upgrading.

Numeric scores use a constrained enumeration in increments of 0.1 between 0 and 1, or null. This is a formatting constraint, not calibration. The wrapper removes change claims when there is no earlier interpreted observation and restricts task context to the user-stated goal or null. `observer_notes` records these evidence limits. Remaining descriptions and classifications are still fallible inferences; source observations and the original pixels should be checked when the distinction matters.

## SQLite schema

`sessions(id, started_at, ended_at, goal)` stores goals stated by the user. Interrupted sessions are marked ended at the next startup, so that end time is a recovery boundary rather than proof of activity until that instant.

`observations(sequence, id, session_id, timestamp, application, window_title, event_type, payload)` stores a JSON observation plus indexed timestamp/session columns. Search uses parameterized, escaped substring matching. Observation order follows the insertion sequence; timestamps are UTC.

`recommendations(id, session_id, timestamp, provider, response, evidence_ids)` stores user-pasted advice. It is not verified or executed. Only the three most recent responses (up to 4,000 characters each) enter an export.

Every database call is guarded by an in-process lock and writes use transactions. There is no schema migration beyond initial version 1; future incompatible changes require a migration. The application uses a Qt lock file to keep two normal UI launches from sharing the same data folder concurrently.

## Observation JSON

```json
{
  "id": "unique observation id",
  "session_id": "session id",
  "timestamp": "2026-10-17T12:00:00.000+00:00",
  "application": "Code.exe",
  "window_title": "example.ts",
  "event_type": "window_change",
  "visible_text": ["Build failed"],
  "screenshot": null,
  "frame_change": null,
  "accessibility_status": "available",
  "accessibility_truncated": true,
  "note": null,
  "interpretation": null,
  "observer_status": "queued",
  "observer_model": null,
  "observer_latency_ms": null,
  "observer_error": null
}
```

Raw event types are `window_change`, `error_text_visible`, `ui_text_change`, `visual_change`, `still_visible`, and `user_bookmark`. `frame_change` is the fraction of changed thumbnail pixels, not a probability. A completed `interpretation` separately contains `activity`, `description`, `visible_errors`, `changes`, `task_context`, `event_type`, `importance`, `confidence`, `requires_supervisor_review`, and `uncertainty`. Unknown fields are null or empty. Numeric estimates are not calibrated probabilities. The model makes no final strategic decision.

Observer states are `disabled`, `queued`, `analyzing`, `complete`, `complete_cpu`, `skipped_busy`, `no_visual_evidence`, `cancelled`, or `failed`. An error code identifies local failures without persisting raw runtime logs. Native window title, application, timestamp and labels remain untouched by model updates. Existing version-1 database rows remain readable and are not falsely marked analyzed; the additional fields live in JSON, so no destructive SQLite migration is required. Export schema version is now 2.

An exported event adds `image_status` and replaces the local screenshot path with an export-relative path, or null. `image_status` is `not_recorded`, `not_included`, `attached_in_export`, or `missing_or_image_limit`.

The context object includes `schema_version`, creation time, mode, selected session, question, selection boundaries/counts, limitations, chronological `observations`, and `previous_unverified_ai_responses`. Observation IDs provide evidence traceability. A session goal is user-supplied; it is never inferred from app usage.

## Extension points

`Recorder` accepts desktop, accessibility, capture and vision-worker factories with small interfaces. Tests supply deterministic evidence without accessing the desktop, while `scripts/test_observer.py` runs the actual model on a known synthetic image. Interpretations stay separate from original evidence and retain observation IDs. A store revision counter refreshes the timeline when inference finishes without adding a new raw event.

An optional future supervisor adapter can consume the same context contract. It must add explicit sharing controls and provider-specific configuration; it must not silently change the manual-sharing behavior implemented here.

## Integration references

- [Qt thread guidance](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html): the Qt UI stays on its main thread; a timer polls bounded background status.
- [MSS examples](https://python-mss.readthedocs.io/stable/examples.html): monitor coordinates and region capture.
- [Python UIAutomation implementation](https://github.com/yinkaisheng/Python-UIAutomation-for-Windows): ControlFromHandle, IsPassword, label properties, COM thread initialization and traversal.

