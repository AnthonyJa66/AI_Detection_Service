from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class DetectionItem:
    class_name: str
    confidence: float
    bbox: list[int]
    source_model: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DetectionResult:
    camera_id: str
    timestamp: str
    frame_width: int
    frame_height: int
    detections: list[DetectionItem] = field(default_factory=list)

    @classmethod
    def empty(cls, camera_id: str, frame_width: int, frame_height: int) -> "DetectionResult":
        return cls(
            camera_id=camera_id,
            timestamp="",
            frame_width=frame_width,
            frame_height=frame_height,
            detections=[],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "timestamp": self.timestamp,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "detections": [item.to_dict() for item in self.detections],
        }
