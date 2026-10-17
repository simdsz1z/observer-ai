# Manual acceptance plan

Use a test Windows account or harmless sample documents. No real passwords or payment details are necessary. This plan is not a claim that these checks have all been performed.

For the local-Qwen version, first run `scripts/setup_observer.py`, then use **Local Qwen → Test with sample screen**. Confirm the result comes from actual local inference, identifies the synthetic visible error, and displays a model name and measured latency. The test must not capture the desktop. Test cancellation by closing the app during this local sample test; its process and temporary files should be released.

During recording, verify that a permitted changed frame progresses from queued to analyzing to complete. Inspect the model interpretation separately from raw metadata. Keep screenshot archives off and confirm local interpretations still work without files accumulating in `screenshots/`. Pause during an analysis and verify it is cancelled without a fabricated result. Force CPU mode with zero GPU layers and check real inference again. A missing model must prevent enabled-Qwen recording from starting, rather than silently claiming to analyze raw data. Old raw-only sessions cannot be retroactively interpreted if their images were not retained.

1. **Consent and lifecycle:** Launch with a fresh `--data-dir`. Confirm the status is paused, screenshots are off, and consent is unchecked. Attempt Start without consent; no session should be created. Enable consent and start; confirm the floating indicator remains visible when minimizing the main window. Pause from that indicator. Verify no new observations appear. Close and reopen; recording must remain paused. A second launch for the same folder should report that Observer is already open.

2. **Programming:** Open an editor with a harmless visible build error. Record a short session with local Qwen enabled. Inspect the native labels and the separate visual interpretation; incomplete labels must not be fabricated as raw text. Confirm Qwen can identify the visible error where legible, or reports uncertainty. Opt into screenshot archives if desired. Build an export, inspect the model result and any images, then manually give it to your chosen website AI. Check that guidance cites real observation IDs.

3. **Switching:** Switch between an editor, browser and PDF reader. Verify process names, titles and timestamps represent the sampled transitions. Fast transitions between samples may be missed. Confirm an app switch creates a new event without waiting for the heartbeat.

4. **Duplicate suppression:** Leave a static test window open for 15 seconds. Expect an initial event and skipped duplicate samples. Over 60 seconds, expect an occasional still-visible event. Keeping the same error visible should not create claims about repeated failed attempts.

5. **Privacy:** Add an app process name and a title fragment to the exclusions, save while paused, then record. Opening either excluded target should suspend capture and storage without displaying its title in the status. With screenshots enabled, overlap an excluded window with a permitted one; verify recognized excluded rectangles are masked. Open a harmless password-entry control without entering a secret and verify suspension when UIA exposes IsPassword. Also test a window without accessibility; images should be withheld. Exclude an entire browser where private tabs cannot be recognized by title.

6. **Text redaction:** Display a fake email address, fake long number and custom literal redaction fragment in accessible text. Verify masking in the database and export. Add another rule later and rebuild; historical database records are not rewritten, but rebuilt exports use current redactions. Inspect screenshots separately: pixel text is not redacted.

7. **UIA timeout:** Try an application without accessibility and one with a large tree. The UI should remain responsive, label limitations should be visible, and the reader should recover after a timeout. Record new events after switching to an accessible app. Startup may take up to five seconds before a failed reader enters its cooldown.

8. **Memory and retention:** Search for a recorded event by application/text. Close and reopen and verify persistence. Test short retention with deliberately aged sample data in a disposable folder. Confirm expired image files are deleted. On a large image collection, verify the periodic disk budget removes older files and exports identify missing evidence. Deleting memory must clear sessions/events/images/responses; independent exports must remain.

9. **Manual website handoff:** Build a text-only package; no images should enter the ZIP. Enable images and rebuild; verify the image list matches exported files. Change session/question/range and confirm the old package is invalidated. Edit the prompt and export; only the Markdown prompt should reflect the edit. Paste an AI response back into the selected session and verify its provider and supporting IDs persist. No response should trigger a computer action.

10. **Display and idle behavior:** Move the target window between monitors, including a monitor left of the primary with negative coordinates, and test different DPI scales. Test a window spanning monitors, display disconnects, minimized windows, screen locking, and sleep/resume. Screenshots should stay within display bounds; errors should recover without blocking the main UI. After 120 seconds of no input, collection should suspend; it should resume after input.

11. **Measured performance:** Run the opt-in live benchmark while doing ordinary work. Note actual process CPU, memory including the UIA child, sampling latency, event counts and failures. Run the real UI for an extended session to evaluate stability. Report false positives/missed events separately; a synthetic benchmark does not establish those rates.

12. **No runtime cloud integration:** After installing dependencies, disconnect the network. Verify local capture, search, export, and manual-response storage still work. Only the separate website AI requires its usual connection.
