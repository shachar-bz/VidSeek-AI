"""Public interface of the shot detection module."""

from .shot_detector import (
    Shot,
    ShotDetectionResult,
    detect_shots,
    load_detection_model,
)
from .video_decoder import decode_video_frames, read_video_fps

__all__ = [
    "Shot",
    "ShotDetectionResult",
    "detect_shots",
    "load_detection_model",
    "decode_video_frames",
    "read_video_fps",
]
