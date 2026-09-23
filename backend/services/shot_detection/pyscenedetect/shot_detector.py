"""Detects shot boundaries in a video and reports each shot's frame range and timecode.

Wraps PySceneDetect (https://github.com/Breakthrough/PySceneDetect), which finds hard
cuts by thresholding the frame-to-frame change in hue, saturation and luma. It runs on
the CPU through OpenCV, so it needs no GPU, no model weights and no ffmpeg binary.

This package is deliberately standalone: it shares no code with the other detectors in
`backend/services/shot_detection` (`omni`, `transnetv2`), so any one of the three can be
deleted without touching the others.
"""

import os
from dataclasses import dataclass, field

from scenedetect import ContentDetector, SceneManager, open_video

# How much the picture must change between two frames, on PySceneDetect's 0-255 scale,
# to count as a cut. This is PySceneDetect's own default; lowering it finds more cuts.
DEFAULT_CONTENT_THRESHOLD = 27.0

# Shots shorter than this are not reported: PySceneDetect suppresses a cut that would
# open a shot this short. Its own default is 15 frames, which this expresses in seconds
# so that the behaviour does not change with the video's frame rate.
DEFAULT_MIN_SHOT_DURATION_SECONDS = 0.5

# Width every frame is shrunk towards before it is compared with the previous one. Cuts
# are whole-frame changes, so detail above roughly 256-480 px only adds decode cost and
# sensor noise. PySceneDetect can only downscale by a whole-number factor, so the width it
# actually works at is the source width divided by the factor nearest to reaching this.
TARGET_PROCESS_WIDTH = 320


@dataclass(frozen=True)
class Shot:
    """A single shot: a half-open frame range [start_frame, end_frame) and its timecode."""

    index: int
    start_frame: int
    end_frame: int
    start_seconds: float
    end_seconds: float

    @property
    def frame_count(self) -> int:
        return self.end_frame - self.start_frame

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True)
class ShotDetectionResult:
    """All shots found in one video, plus the metadata needed to interpret their frames."""

    video_path: str
    fps: float
    frame_count: int
    process_width: int
    process_height: int
    shots: list[Shot] = field(default_factory=list)

    @property
    def shot_count(self) -> int:
        return len(self.shots)

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.fps if self.fps else 0.0


def detect_shots(
    video_path: str,
    *,
    content_threshold: float = DEFAULT_CONTENT_THRESHOLD,
    min_shot_duration_seconds: float = DEFAULT_MIN_SHOT_DURATION_SECONDS,
) -> ShotDetectionResult:
    """Detect every shot in `video_path`.

    The returned shots tile the whole video back to back, so `shot_count` is the number
    of shots it contains and each shot carries both its frame range and its timecode.

    Note that every shot is reported as a plain cut: PySceneDetect's content detector
    cannot tell a dissolve, wipe or fade from a hard cut, so there is nothing to label.
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    video = open_video(video_path)
    fps = float(video.frame_rate)
    source_width, source_height = video.frame_size

    scene_manager = SceneManager()
    scene_manager.auto_downscale = False
    scene_manager.downscale = max(1, round(source_width / TARGET_PROCESS_WIDTH))
    scene_manager.add_detector(
        ContentDetector(
            threshold=content_threshold,
            # PySceneDetect counts this in frames, and rejects 0, so a caller asking for
            # no minimum still gets the smallest one the library allows.
            min_scene_len=max(1, round(min_shot_duration_seconds * fps)),
        )
    )
    scene_manager.detect_scenes(video, show_progress=False)

    # `start_in_scene` is what keeps the shots tiling the whole video: without it a video
    # containing no cut at all comes back as zero shots instead of as one shot covering
    # everything, and a video whose first cut is late loses the footage before it.
    scenes = scene_manager.get_scene_list(start_in_scene=True)

    shots = [
        Shot(
            index=index,
            start_frame=start.frame_num,
            end_frame=end.frame_num,
            start_seconds=start.seconds,
            end_seconds=end.seconds,
        )
        for index, (start, end) in enumerate(scenes)
    ]

    return ShotDetectionResult(
        video_path=video_path,
        fps=fps,
        frame_count=video.duration.frame_num,
        process_width=source_width // scene_manager.downscale,
        process_height=source_height // scene_manager.downscale,
        shots=shots,
    )
