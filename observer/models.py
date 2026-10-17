from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class Window:
    handle: int
    pid: int
    application: str
    title: str
    rect: tuple[int, int, int, int]


@dataclass
class Accessibility:
    labels: list[str] = field(default_factory=list)
    status: str = "unavailable"
    sensitive: bool = False
    truncated: bool = False


@dataclass
class Observation:
    session_id: str
    application: str
    window_title: str
    event_type: str
    visible_text: list[str] = field(default_factory=list)
    screenshot: str | None = None
    frame_change: float | None = None
    accessibility_status: str = "unavailable"
    accessibility_truncated: bool = False
    note: str | None = None
    id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: str = field(default_factory=now_iso)
    interpretation: dict[str, Any] | None = None
    observer_status: str = "disabled"
    observer_model: str | None = None
    observer_latency_ms: float | None = None
    observer_error: str | None = None
    observer_notes: list[str] = field(default_factory=list)
    observer_input: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

