# Using Observer AI

## Install without uv

From the cloned repository, with Python 3.11+ installed:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe scripts\setup_observer.py
.venv\Scripts\python.exe -m observer
```

FFmpeg and ffprobe must also be available for video. After installation, `run.cmd` launches the application. See the main README for the recommended uv installation.

## Chat directly with Qwen or analyze a video file

Open **Chat with Qwen** to send normal text messages and follow-up questions. Recent conversation is included in each request. **Include recent saved screen observations** adds up to four completed observations with their source timestamps; chat does not take a new screenshot. Chat history is saved locally, restored on launch, and covered by the configured retention period and **Delete local memory**. **Clear chat** starts fresh; **Save chat…** writes a separate text copy.

Select **Attach video…**, choose a file, type a question, and press **Send**. End **Whole remaining video** analyzes from the selected Start through the end of the file. A custom End selects a smaller range. Default sampling is 1 frame/sec; lower sampling covers longer intervals with fewer frames, while missing shorter actions. The entire chosen range is processed in bounded sections with visible progress and original-video time labels. Section descriptions stay chronological rather than being merged into one potentially misleading summary. Video analysis uses visual frames only, without audio transcription. After a successful analysis, the attachment is removed from the next message; follow-ups use the saved text conversation unless you reattach the video.

**Stop** cancels the active/waiting chat request and deletes temporary files. Screen capture can continue during chat, but Qwen inference is serialized across chat, live observation, and sample tests to avoid loading two copies on the GPU. Live observation clips may be skipped while video-file analysis is busy. Source video files stay at their original location; bounded temporary MP4s are deleted after processing. Chat replies are local model advice and can be mistaken. They are not automatically inserted into website evidence exports or executed.

Launch directly into chat with `.venv\Scripts\python.exe -m observer --chat`.

## Use it with an AI website

1. Open **Local Qwen** and check installation. Use **Test screen video** to run real inference on a generated error-to-success sequence, without capturing the desktop. Save model-setting changes while paused.
2. On **Overview**, enter an optional goal, check the consent box for local capture and Qwen analysis, and select **Start recording**. Monitoring starts paused on every launch. A small topmost recording indicator provides a Pause button when the main window is minimized.
3. Work normally. Continuous permitted active-window frames are grouped into video clips, including unchanged frames. Raw change events are deduplicated separately. Qwen watches clips sequentially with at most two waiting; skipped clips are marked. Observer windows, excluded applications, and detected password controls suspend collection. Live video continues without mouse/keyboard activity; raw-only and single-frame modes retain idle suspension.
4. Select **Pause recording**. Inspect **Activity timeline**, including **Qwen activity / state** and the selected event's full JSON. Raw window titles and labels remain separate from fallible model interpretations. Pause cancels current inference and releases model resources; queued events can become cancelled.
5. On **AI handoff**, choose a session, time window, event limit, and question. The time window for a completed session ends at that session's end. Select **Build / refresh context**.
6. Review **Prompt**, **Raw JSON**, and **Images**. Completed local interpretations are included with source observation IDs, model name, and inference latency. Images are omitted unless explicitly included. Prompt edits affect only the copied prompt and Markdown file. Rebuild to apply different selection or privacy settings.
7. **Copy prompt** and paste it into your AI website. Or **Export reviewed package**, extract it, and share the reviewed files as supported by that website. Optionally paste the website AI's response back using **Paste / save AI response**; it remains unverified advice and is never executed.

Qwen can read visible text even when an editor exposes little accessibility text, provided accessibility responds to the privacy check. Screenshot archiving is separate from local analysis. Video frames stay in a bounded RAM buffer; temporary MP4 and prompt files are removed after inference, failure, or cancellation and stale files are removed on startup. No video archive is retained or exported. Optional single-frame mode uses temporary JPEGs. Enable image archiving if you want reviewed screenshots in website exports.

See [the video implementation and verification notes](live-video.md) for details.

## Collected data

- UTC timestamps, session IDs, a user-stated goal, application process name, and foreground-window title.
- A bounded sample of visible accessibility labels, where the application exposes them. Edit/combo-box values and their contents are not requested. This can mean that code and document body text are unavailable.
- Local Qwen interpretations: activity, description, visible errors, changes, possible task context, event type, uncertainty, and a flag that a supervisor review may help. Unsupported evidence is null or empty. Confidence and importance are model estimates, not calibrated probabilities.

Scores are restricted to 0–1 in increments of 0.1, or null. Single-frame change claims are removed when no prior interpretation exists; multi-frame clips can establish visible transitions; task context is limited to your stated goal or null. `observer_notes` records these evidence limits. Other model descriptions remain fallible; a plausible explanation is not proof of an action.
- Optional downscaled active-window JPEGs, taken only when accessibility responds and no password control is detected. The active window can be on any monitor or span monitors. This is not a full-desktop or per-monitor recorder.
- Change events, occasional still-visible observations, user bookmarks, and manually pasted AI advice.

No raw keyboard events, clipboard history, microphone, automatic computer actions, or hidden startup tasks are used. Clipboard writing happens only when you select **Copy prompt**. Recognized password controls pause capture, but an unrecognized secret visible in pixels could still reach the local model; exclusion and detection remain best effort.

## Privacy and local memory

The default folder is `%LOCALAPPDATA%\ObserverAI`. Override it with:

```powershell
.venv\Scripts\python.exe -m observer --data-dir D:\ObserverData
```

The folder contains `settings.json`, `memory.sqlite3` and its SQLite sidecars, `screenshots/`, and the temporary `inference-temp/` folder. One UI instance can use a given data folder at a time. Model weights and runtime files are in the project's ignored `.models/` and `.runtime/` directories.

Settings include case-insensitive substring exclusions for applications and titles, literal text fragments to redact, retention (7 days by default), a screenshot budget (256 MB), and sample interval (1 second). Email addresses, common credential-token patterns, secret assignments, and long numbers are masked in text. These are best-effort checks, not a guarantee that all sensitive information is removed.

Exclusions run before UIA inspection or screenshot capture. Detected password controls suppress the whole automatic sample. Recognized excluded windows and Observer windows are masked where they overlap captured pixels. Accessibility inspection has depth, item, time, and text limits; a hung provider is terminated in a separate process. Screenshots are withheld if accessibility is disabled or unavailable. Changes to foreground title, handle, process, or geometry during sampling discard the sample.

**Images can still contain sensitive data, notifications, or fields that accessibility did not expose. Text redaction does not redact pixels.** Leave screenshots off when working with sensitive material. An excluded title cannot hide a private browser tab whose title does not identify it; exclude that entire browser if needed.

Data is not encrypted by this application. Use Windows account protections and disk encryption. Retention is applied at startup and approximately every minute during active collection; the screenshot disk budget is a periodic soft limit. Old screenshot references can remain in events after their files are pruned; exports mark missing evidence explicitly. New redaction settings apply to future records and rebuilt exports, not historical database contents. Rebuilt exports also omit historical events matching current app/title exclusions and report the omission count.

**Delete local memory** removes sessions, recorded events, stored AI responses, and saved images. Exports are independent copies. Clipboard contents, website conversations, OS caches, backups, and filesystem recovery are outside this deletion operation.

## Exports

Each ZIP contains:

- `PASTE_INTO_AI.md`: instructions plus selected evidence, editable before export.
- `context.json`: structured selected context, source observation IDs, limitations, and selection information.
- `observations.jsonl`: the same selected events, one JSON object per line.
- `images/`: up to 12 explicitly included JPEGs.
- `READ_ME.txt`: sharing and review instructions.

The latest 50 events are selected by default, up to 200. A 40,000-character evidence budget can omit older events; the package reports size omissions. Instructions, JSON indentation, the question, and up to three previous responses add further text, so the full prompt can be larger. There is no provider-specific token estimator. Exported images are frozen when you build the context, so the files match the reviewed preview. Avoid leaving prepared image packages in memory longer than needed.
