"""Public interface of the PySceneDetect shot detection module."""

from .shot_detector import Shot, ShotDetectionResult, detect_shots

__all__ = [
    "Shot",
    "ShotDetectionResult",
    "detect_shots",
]
