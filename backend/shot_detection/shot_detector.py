"""Detects shot boundaries in a video and reports each shot's frame range and timecode.

Wraps the OmniShotCut model (https://github.com/UVA-Computer-Vision-Lab/OmniShotCut),
which requires a CUDA GPU and the ffmpeg binary on PATH.
"""

import functools
import os
from dataclasses import dataclass, field

import omnishotcut

from .video_decoder import decode_video_frames, read_video_fps

DEFAULT_CHECKPOINT_REPO = "uva-cv-lab/OmniShotCut_v1.5"
DEFAULT_CHECKPOINT_FILENAME = "OmniShotCut_ckpt.pth"

# Frames shared between adjacent inference windows, so a cut near a window edge is
# still seen with context on both sides. This is the value OmniShotCut's own CLI uses.
DEFAULT_OVERLAP_FRAMES = 10

# Resolution the model works at. Only used when it cannot be read off the loaded
# checkpoint: OmniShotCut rescales whatever it is given, so a stale default here costs
# one extra resize but never changes the result.
FALLBACK_PROCESS_WIDTH = 128
FALLBACK_PROCESS_HEIGHT = 96

# OmniShotCut's label for a shot that begins with a plain hard cut rather than with a
# gradual transition such as a dissolve, wipe or fade.
HARD_CUT_TRANSITION_LABEL = "General"


@dataclass(frozen=True)
class Shot:
    """A single shot: a half-open frame range [start_frame, end_frame) and its timecode."""

    index: int
    start_frame: int
    end_frame: int
    start_seconds: float
    end_seconds: float
    transition_type: str
    boundary_type: str

    @property
    def frame_count(self) -> int:
        return self.end_frame - self.start_frame

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds

    @property
    def begins_with_gradual_transition(self) -> bool:
        """True when this shot fades/dissolves/wipes in rather than starting on a hard cut."""
        return self.transition_type != HARD_CUT_TRANSITION_LABEL


@dataclass(frozen=True)
class ShotDetectionResult:
    """All shots found in one video, plus the metadata needed to interpret their frames."""

    video_path: str
    fps: float
    frame_count: int
    shots: list[Shot] = field(default_factory=list)

    @property
    def shot_count(self) -> int:
        return len(self.shots)

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.fps if self.fps else 0.0


@functools.lru_cache(maxsize=1)
def _load_detection_model_cached(checkpoint: str, checkpoint_filename: str):
    return omnishotcut.load(checkpoint, filename=checkpoint_filename)


def load_detection_model(
    checkpoint: str = DEFAULT_CHECKPOINT_REPO,
    checkpoint_filename: str = DEFAULT_CHECKPOINT_FILENAME,
):
    """Load OmniShotCut onto the GPU, caching it so repeated detections reuse one model.

    `checkpoint` is either a local .pth path or a HuggingFace repo ID, in which case the
    weights are downloaded to the HuggingFace cache on first use.

    The defaults are resolved before the cache is consulted, because an lru_cache keys on
    how a function was called: caching this function directly would treat a call that
    omits the arguments and one that passes those same defaults as two separate models,
    and each would evict the other from the single-entry cache.
    """
    return _load_detection_model_cached(checkpoint, checkpoint_filename)


def _read_process_resolution(model) -> tuple[int, int]:
    """Read the resolution the model runs at, falling back to its published default."""
    model_args = getattr(model, "_model_args", None)
    width = getattr(model_args, "process_width", None)
    height = getattr(model_args, "process_height", None)
    if width and height:
        return int(width), int(height)
    return FALLBACK_PROCESS_WIDTH, FALLBACK_PROCESS_HEIGHT


def detect_shots(
    video_path: str,
    *,
    hard_cuts_only: bool = False,
    overlap_frames: int = DEFAULT_OVERLAP_FRAMES,
    checkpoint: str = DEFAULT_CHECKPOINT_REPO,
    checkpoint_filename: str = DEFAULT_CHECKPOINT_FILENAME,
) -> ShotDetectionResult:
    """Detect every shot in `video_path`.

    By default the returned shots tile the whole video back to back, so `shot_count` is
    the number of shots it contains and each shot carries both its frame range and its
    timecode. Setting `hard_cuts_only` keeps just the shots that begin on a plain cut,
    dropping those that fade or dissolve in — the result then no longer covers the whole
    video, so use it only when gradual transitions are noise for your purpose.
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    fps = read_video_fps(video_path)
    model = load_detection_model(checkpoint, checkpoint_filename)

    # Decode here rather than passing the path to OmniShotCut, whose own decoder calls
    # ffmpeg with the `-vsync` flag that ffmpeg 9 removed.
    process_width, process_height = _read_process_resolution(model)
    frames = decode_video_frames(video_path, process_width, process_height)

    # Always ask for "default" rather than "clean_shot": it returns the same ranges plus
    # the transition labels, so one pass serves both kinds of caller.
    frame_ranges, transition_types, boundary_types = model.inference(
        frames, mode="default", overlap=overlap_frames
    )

    shots = [
        Shot(
            index=index,
            start_frame=int(start_frame),
            end_frame=int(end_frame),
            start_seconds=int(start_frame) / fps,
            end_seconds=int(end_frame) / fps,
            transition_type=transition_type,
            boundary_type=boundary_type,
        )
        for index, ((start_frame, end_frame), transition_type, boundary_type) in enumerate(
            zip(frame_ranges, transition_types, boundary_types)
        )
    ]

    if hard_cuts_only:
        shots = [shot for shot in shots if not shot.begins_with_gradual_transition]

    return ShotDetectionResult(
        video_path=video_path, fps=fps, frame_count=len(frames), shots=shots
    )
