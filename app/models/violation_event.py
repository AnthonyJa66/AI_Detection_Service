from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ViolationEvent:
    event_id: str
    camera_id: str
    violation_type: str
    timestamp: str
    confidence: float
    snapshot_path: str | None = None
    snapshot_bbox: list[int] | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
