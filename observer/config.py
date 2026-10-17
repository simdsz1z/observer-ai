import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def default_data_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "ObserverAI"


@dataclass
class Settings:
    interval_seconds: float = 1.0
    heartbeat_seconds: float = 60.0
    idle_seconds: int = 120
    screenshots: bool = False
    accessibility: bool = True
    retention_days: int = 7
    screenshot_budget_mb: int = 256
    observer_enabled: bool = True
    observer_interval_seconds: float = 5.0
    observer_video: bool = True
    observer_video_frames: int = 8
    observer_keep_loaded: bool = True
    observer_timeout_seconds: int = 120
    observer_gpu_layers: int = 99
    observer_vision_gpu: bool = True
    observer_threads: int = 4
    observer_executable: str = ""
    observer_model_path: str = ""
    observer_projector_path: str = ""
    observer_prompt: str = ""
    excluded_apps: list[str] = field(default_factory=lambda: [
        "1password", "bitwarden", "keepass", "credentialuibroker", "lockapp",
    ])
    excluded_titles: list[str] = field(default_factory=lambda: [
        "incognito", "inprivate", "private browsing", "password manager", "checkout", "payment",
    ])
    redactions: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not 0.5 <= self.interval_seconds <= 30:
            raise ValueError("Capture interval must be between 0.5 and 30 seconds.")
        if not 10 <= self.heartbeat_seconds <= 600:
            raise ValueError("Heartbeat must be between 10 and 600 seconds.")
        if not 1 <= self.retention_days <= 365:
            raise ValueError("Retention must be between 1 and 365 days.")
        if not 16 <= self.screenshot_budget_mb <= 4096:
            raise ValueError("Screenshot budget must be between 16 and 4096 MB.")
        if not 30 <= self.idle_seconds <= 3600:
            raise ValueError("Idle threshold must be between 30 and 3600 seconds.")
        if not isinstance(self.observer_enabled, bool) or not isinstance(self.observer_vision_gpu, bool) or type(self.observer_keep_loaded) is not bool:
            raise ValueError("Local observer enabled must be true or false.")
        if not 1 <= self.observer_interval_seconds <= 300:
            raise ValueError("Local observation interval must be between 1 and 300 seconds.")
        if type(self.observer_video) is not bool or type(self.observer_video_frames) is not int or not 2 <= self.observer_video_frames <= 16:
            raise ValueError("Use 2–16 frames per live video clip.")
        if not 15 <= self.observer_timeout_seconds <= 300:
            raise ValueError("Local model timeout must be between 15 and 300 seconds.")
        if not 0 <= self.observer_gpu_layers <= 99 or not 1 <= self.observer_threads <= 32:
            raise ValueError("Use 0–99 GPU layers and 1–32 CPU threads.")
        for value in (self.observer_executable, self.observer_model_path, self.observer_projector_path, self.observer_prompt):
            if not isinstance(value, str):
                raise ValueError("Local model paths and prompt must be text.")
        for items in (self.excluded_apps, self.excluded_titles, self.redactions):
            if not isinstance(items, list) or any(not isinstance(x, str) for x in items):
                raise ValueError("Privacy rules must be lists of text.")

    @classmethod
    def load(cls, directory: Path) -> "Settings":
        path = directory / "settings.json"
        if not path.exists():
            return cls()
        values = json.loads(path.read_text(encoding="utf-8"))
        # Upgrade the old snapshot default while preserving customized intervals.
        if "observer_video" not in values and values.get("observer_interval_seconds") == 20:
            values["observer_interval_seconds"] = 5.0
        obj = cls(**values)
        obj.validate()
        return obj

    def save(self, directory: Path) -> None:
        self.validate()
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / "settings.json.tmp"
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(directory / "settings.json")

