"""Public interface of the TransNetV2 shot detection module."""

from .shot_detector import Shot, ShotDetectionResult, detect_shots, load_detection_model

__all__ = [
    "Shot",
    "ShotDetectionResult",
    "detect_shots",
    "load_detection_model",
]
