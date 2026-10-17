# Performance measurements

Measured on Windows with an NVIDIA RTX 4070 Laptop GPU (8 GB VRAM) and 32 GB system RAM. These short development runs establish throughput and lifecycle behavior, not model accuracy or multi-hour stability.

## Configuration

Qwen3-VL-2B-Instruct Q4_K_M, Q8_0 projector, pinned llama.cpp b11669 Vulkan runtime. One-second preset: two captured frames/sec, two frames per clip, one-second minimum analysis interval. The resident helper keeps weights and encoder loaded and resets request context. First-load cost is included.

| Metric | Original file | Resident file | Original live | Resident live |
|:--|--:|--:|--:|--:|
| Duration (sec) | 45.28 | 45.41 | 60.91 | 60.78 |
| Clips created | 45 | 45 | 47 | 58 |
| Analyses completed | 5 | 33 | 6 | 46 |
| Busy skips | 37 | 10 | 38 | 10 |
| Cancelled at stop | 3 | 2 | 3 | 2 |
| Mean processing (sec/clip) | 7.753 | 1.330 | 8.695 | 1.279 |
| Median processing (sec/clip) | 7.438 | 1.265 | 8.922 | 1.203 |
| Busy skip rate | 82.2% | 22.2% | 80.9% | 17.2% |

File tests used [OpenCV's public vtest.avi sample](https://github.com/opencv/opencv/blob/4.x/samples/data/vtest.avi). It is not bundled in this repository. Live tests used actual desktop activity rather than identical replayed content. The original live run also encountered an accessibility-provider timeout and cooldown, reducing capture throughput. Completed clip totals therefore reflect both capture and inference behavior.

All completed resident requests reported the same worker within each run and two decoded video frames per clip. The resident live run captured 118 frames (~1.94 frames/sec). Peak sampled whole-device VRAM was 3,305 MB; GPU temperature reached 76°C. Peak worker process-tree RSS was about 1,477 MB. Device metrics include other applications and are not isolated application usage.

The resident file and live runs left zero temporary inference files. A separate real-model lifecycle check confirmed worker reuse across different scenes, release before chat, a new worker after chat, and termination on pause.

## Reproduce

Install dependencies, FFmpeg, models, and the resident helper first. Inspect available benchmark arguments:

```powershell
uv run python scripts/benchmark_monitor.py --help
uv run python scripts/test_observer.py --video
```

`benchmark_monitor.py` supports file playback and an explicitly opted-in live desktop mode. Live tests can collect sensitive desktop evidence; use a safe test workspace. Generated reports belong in ignored `qa/`, not a public issue attachment without review.

These results do not establish uninterrupted one-analysis-per-second coverage, real-world interpretation accuracy, or ten-hour operation. Skipped clips leave gaps. Faster hardware, different content, power modes, and inference settings can substantially change results.
