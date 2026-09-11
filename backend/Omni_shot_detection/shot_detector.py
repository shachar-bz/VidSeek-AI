"""Detects shot boundaries in a video and reports each shot's frame range and timecode.

Wraps the OmniShotCut model (https://github.com/UVA-Computer-Vision-Lab/OmniShotCut),
which requires a CUDA GPU and the ffmpeg binary on PATH.
"""

import functools
import os
from dataclasses import dataclass, field, replace

import omnishotcut

from .video_decoder import decode_video_frames, read_video_fps

DEFAULT_CHECKPOINT_REPO = "uva-cv-lab/OmniShotCut_v1.5"
DEFAULT_CHECKPOINT_FILENAME = "OmniShotCut_ckpt.pth"

# Frames shared between adjacent inference windows, so a cut near a window edge is
# still seen with context on both sides. This is the value OmniShotCut's own CLI uses.
DEFAULT_OVERLAP_FRAMES = 10

# 0 disables merging: the model's own output is returned as-is. OmniShotCut does not
# expose a confidence score or a minimum-duration filter of its own, so callers who want
# one apply it here, after detection, via `min_shot_duration_seconds`.
DEFAULT_MIN_SHOT_DURATION_SECONDS = 0.0

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


def _merge_short_shots(shots: list[Shot], min_duration_seconds: float) -> list[Shot]:
    """Merge every shot shorter than `min_duration_seconds` into a neighboring shot.

    A short shot is absorbed into the previous shot by extending the previous shot's end
    to cover it, so the surviving shot keeps the transition label it was already opened
    with — the discarded shot's own label is what made it noise in the first place. The
    video's opening shot has no previous shot, so if it is itself too short it is instead
    absorbed forward into the shot after it, which keeps the fixed New_Start/General
    labels of the very first frame.

    Repeats until no shot is left under the threshold (merging can chain: merging two
    shots can leave the result still short next to another short one) or only one shot
    remains, whichever comes first.
    """
    if min_duration_seconds <= 0:
        return shots

    merged = list(shots)
    while len(merged) > 1:
        short_index = next(
            (i for i, shot in enumerate(merged) if shot.duration_seconds < min_duration_seconds),
            None,
        )
        if short_index is None:
            break

        keep_index = 0 if short_index == 0 else short_index - 1
        absorbed_index = 1 if short_index == 0 else short_index
        absorbed = merged[absorbed_index]

        merged[keep_index] = replace(
            merged[keep_index], end_frame=absorbed.end_frame, end_seconds=absorbed.end_seconds
        )
        del merged[absorbed_index]

    return [replace(shot, index=index) for index, shot in enumerate(merged)]


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
    min_shot_duration_seconds: float = DEFAULT_MIN_SHOT_DURATION_SECONDS,
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

    `min_shot_duration_seconds` merges away shots shorter than that into a neighbor
    before `hard_cuts_only` is applied, cleaning up the spurious sub-second shots the
    model sometimes emits at its internal window-stitching seams. The merged result
    still tiles the whole video.
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

    shots = _merge_short_shots(shots, min_shot_duration_seconds)

    if hard_cuts_only:
        shots = [shot for shot in shots if not shot.begins_with_gradual_transition]

    return ShotDetectionResult(
        video_path=video_path, fps=fps, frame_count=len(frames), shots=shots
    )
