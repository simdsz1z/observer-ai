# Persistent local observer runtime

The observer now keeps its model and vision encoder in one owned native worker between clips. `native/observer_runtime.cpp` uses the exact b11669 llama/mtmd DLLs already installed. Python communicates through bounded JSON lines over stdin/stdout, with a separately drained, bounded stderr tail. There is no HTTP listener, localhost inference endpoint, cloud service, or key. Media remains temporary local MP4/JPEG input.

The worker explicitly selects the NVIDIA device when GPU layers are enabled and reports its exact device description in the startup handshake. GPU inference uses Flash Attention. Each request clears the KV memory, allocates independent media chunks and grammar state, evaluates the new video/image, generates a constrained reply, and frees all per-request media/sampler resources. Model weights, encoder, context buffers, and compiled kernels remain resident. The worker reports input/output token counts, actual decoded video frame count, prefill/generation timings, process ID, and request number in `observer_input.runtime`.

The native grammar uses compact internal field names and no formatting whitespace to reduce output tokens. The helper expands them into the same canonical observation fields before returning a result. Task context is attached from the stated goal by the existing Python evidence guard. Python still validates all canonical fields, lengths, arrays, numeric enums, and types before persistence. The greedy sampler checks the highest-scoring token against the grammar first and only masks the full vocabulary on rejection; this preserves constraints without a full-vocabulary grammar scan on every token.

The process-wide model slot releases a previous owner's resident worker before chat or a different observer needs the GPU. Chat itself retains its existing single-request backend. Pause, application close, cancellation, and timeout terminate the resident worker and its child media processes. Cancellation can interrupt requests waiting for the model slot or worker startup. Timed-out/failed workers are discarded before retry. Initial GPU runtime failures retain the prior CPU fallback behavior. CLI fallback remains available if the helper is absent or Keep Qwen loaded is disabled; installation status makes that mode explicit.

## Build

This workspace's helper was built using the existing Visual Studio 2022 MSVC Build Tools. Run:

    .venv/Scripts/python.exe scripts/build_observer_runtime.py

The script downloads headers from the pinned ggml-org/llama.cpp b11669 tag and nlohmann JSON v3.12.0, derives import libraries from the installed DLL exports, and compiles `.runtime/llama-b11669-vulkan/observer-runtime.exe`. No system libraries or model weights are replaced. The helper is specific to this pinned runtime and must be rebuilt/reverified when changing that runtime. The standard setup downloads the hash-verified prebuilt v0.3.0 helper from GitHub Releases, so MSVC is only needed to rebuild it. Without the helper, the app can continue in CLI fallback mode.

## Verification and limits

Repeated real requests reused one process, with a cleared context and independent validated replies each time. A full 45-second real-footage test reused the same worker for all 33 completed video analyses, and its native decoder reported two frames for each clip. Mean total processing was 1.330 seconds, median 1.265, versus the original 7.753-second mean. Busy skips fell from 37/45 (82.2%) to 10/45 (22.2%); two unfinished clips were cancelled when stopping. First-load overhead is included. This improves throughput but does not establish one completed analysis per second or long-duration stability.

The implementation was tested with real local model inference, real public footage, synthetic visible-error video, native desktop monitoring, and automated transport/lifecycle checks. The experimental interactive mtmd CLI was investigated but not used: it failed on its second visual request in this installed release. The helper avoids that persistent-CLI state path by managing request resources directly.

The subsequent 60.78-second native desktop run captured 118 frames and generated 58 one-second video observations. It completed 46, skipped 10 while busy (17.2%), and cancelled two when stopping. Mean processing was 1.279 seconds, median 1.203, versus the original live mean of 8.695. Every completed request reported the same RTX worker PID and two decoded video frames. Accessibility responded throughout this run. Peak sampled device VRAM was 3,305 MB and temperature 76 C; whole-device metrics include other apps. Neither this run nor the real-file run left temporary inference files.

A real lifecycle test reused a worker across an error scene and a different success scene, released it before a chat reply, loaded a new worker for the next observation, and confirmed termination on pause with zero remaining temporary files. Automated transport checks also cover invalid handshakes, timeouts, cancellation races, thread cleanup, and model-owner handoff. All 54 automated checks pass. These are short checks; multi-hour stability remains unproven.
