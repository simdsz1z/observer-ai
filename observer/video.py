"""Bounded, timestamped screen clips. Frames stay in memory until local inference."""
from dataclasses import dataclass
import os
import shutil
from pathlib import Path

from PIL import Image, ImageOps


def video_tools():
    bundled = Path(__file__).resolve().parents[1] / ".runtime" / "ffmpeg" / "bin"
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    candidates = [bundled]
    if winget.is_dir():
        for package in winget.glob("Gyan.FFmpeg_*"):
            candidates.extend(p.parent for p in package.glob("*/bin/ffmpeg.exe"))
    for directory in candidates:
        if (directory / "ffmpeg.exe").is_file() and (directory / "ffprobe.exe").is_file():
            return str(directory / "ffmpeg.exe"), str(directory / "ffprobe.exe")
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe or Path(ffmpeg).parent != Path(ffprobe).parent:
        raise ValueError("Live video needs ffmpeg and ffprobe together on PATH.")
    return ffmpeg, ffprobe


@dataclass
class ScreenFrame:
    image: object
    timestamp: str
    monotonic: float
    application: str
    window_title: str


@dataclass
class ScreenClip:
    frames: tuple

    def copy(self):
        # Images are owned by the buffer and never mutated after construction.
        return ScreenClip(self.frames)

    @property
    def fps(self):
        span = self.frames[-1].monotonic - self.frames[0].monotonic
        return (len(self.frames) - 1) / span if span > 0 else 1.0

    def metadata(self):
        start = self.frames[0].monotonic
        return {"mode": "video", "frame_count": len(self.frames), "fps": round(self.fps, 3),
                "started_at": self.frames[0].timestamp, "ended_at": self.frames[-1].timestamp,
                "span_seconds": round(self.frames[-1].monotonic - start, 3),
                "frames": [{"timestamp": f.timestamp, "offset_seconds": round(f.monotonic - start, 3),
                            "application": f.application, "window_title": f.window_title} for f in self.frames]}

    def rgb_bytes(self):
        return b"".join(f.image.tobytes() for f in self.frames)


class ClipBuffer:
    def __init__(self, frame_count, capture_interval):
        self.frame_count = frame_count
        self.capture_interval = capture_interval
        self.frames = []

    def clear(self):
        self.frames.clear()

    def add(self, image, timestamp, monotonic, application, window_title):
        # Never join across withheld frames, long stalls, or suspended collection.
        if self.frames and monotonic - self.frames[-1].monotonic > max(3, self.capture_interval * 2.5):
            self.clear()
        pixels = ImageOps.pad(image.convert("RGB"), (960, 672), color="#101925", method=Image.Resampling.LANCZOS)
        self.frames.append(ScreenFrame(pixels, timestamp, monotonic, application, window_title))
        if len(self.frames) < self.frame_count:
            return None
        clip = ScreenClip(tuple(self.frames))
        self.clear()
        return clip
