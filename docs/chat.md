# Local Qwen chat and video files

`ChatPanel` supplies a native conversation view, message editor, optional saved-screen context, file picker, video start/end and sampling controls, progress messages, Stop, Clear chat, and Save chat. Model work runs on a background thread; Qt updates and conversation persistence happen on the UI thread. Closing cancels and joins the worker before the shared database is closed. Settings/deletion are blocked during a live request.

Text conversation uses the installed `llama-completion.exe` with the same Qwen GGUF, chat template, and a single turn. Video conversation uses `llama-mtmd-cli.exe --video` without the observer's JSON schema. Native stdout supplies the reply; stderr runtime logs are not shown as assistant text. The last six conversation messages and up to four privacy-filtered completed observations supply bounded context. Chat does not capture new desktop pixels. Model outputs remain fallible and no actions are executed.

File duration is probed with FFprobe. The entire user-selected interval is processed in sections of at most eight sampled frames. FFmpeg seeks and normalizes each section into a bounded temporary H.264 MP4; llama.cpp samples it at the chosen FPS. Default 1 FPS means eight-second sections; 0.125 FPS covers 64 seconds per eight-frame section. First and last partial sections retain original range labels. Audio is omitted. Source files are read without modification; temporary MP4s and prompt files are removed on completion, failure, or cancellation. Long videos can take substantial local processing time. Each section's natural-language answer is kept under its original time interval, preventing an extra summarization pass from conflating distinct states.

The process-wide model lock serializes observer, chat, and sample inference; waiting requests can be cancelled. Screen capture can continue while chat/file analysis runs, with the existing bounded live-video queue and skipped-clip status. GPU failures retry on CPU. The process timeout applies per inference/encoding operation, and Stop also kills owned subprocess children.

`chat_messages` is an additive SQLite table. Messages, attachment basenames, and assistant replies persist locally and follow retention. Chat clearing and Delete local memory remove them. The source video itself is never copied into persistent memory. Successfully analyzed attachments are removed from the next message so follow-ups use saved text unless reattached. Save chat writes an explicit independent UTF-8 copy. Chat history is separate from automatic website evidence packages.

## Verification

50 unit/integration checks pass, including chat persistence/deletion, nested screen-context exclusions, conversation history, full multi-section coverage, range checks, temporary cleanup, cancellable model-slot waits, and a native offscreen UI send/follow-up/cancel flow.

Real installed Qwen returned a conversational text answer and analyzed an eight-second synthetic error-to-success MP4. A second real run sampled it at 2 FPS across two sections: 0–4 seconds described the red TypeError panel, and 4–8 seconds described the green BUILD SUCCEEDED panel. Processing took 10.734 seconds in that run and left zero temporary files. No real desktop pixels or private video files were used in these checks. UI screenshots were rendered from owned synthetic messages.
