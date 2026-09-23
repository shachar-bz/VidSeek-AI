"""Detects shot boundaries in a video and reports each shot's frame range and timecode.

Wraps TransNetV2 (https://github.com/soCzech/TransNetV2) via its PyTorch
reimplementation, the `transnetv2-pytorch` package. Runs on CPU, CUDA or MPS, and
downloads its converted weights from the HuggingFace Hub on first use.

This package is deliberately standalone: it shares no code with the other detectors in
`backend/services/shot_detection` (`omni`, `pyscenedetect`), so any one of the three can
be deleted without touching the others.
"""

import functools
import os
from dataclasses import dataclass, field, replace

import torch
from huggingface_hub import hf_hub_download
from transnetv2_pytorch import TransNetV2

DEFAULT_CHECKPOINT_REPO = "Sn4kehead/TransNetV2"
DEFAULT_CHECKPOINT_FILENAME = "transnetv2-pytorch-weights.pth"

# TransNetV2's own default: a frame is a shot boundary once the model's predicted
# probability for it crosses this line.
DEFAULT_THRESHOLD = 0.5

# 0 disables merging: the model's own scenes are returned as-is. TransNetV2 does not
# classify a transition's type (cut vs. dissolve vs. wipe) the way OmniShotCut does, so
# there is nothing to preserve here beyond the shot boundaries themselves.
DEFAULT_MIN_SHOT_DURATION_SECONDS = 0.0

# "auto" prioritizes CUDA, then CPU, then MPS - the package's own default.
DEFAULT_DEVICE = "auto"


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
    shots: list[Shot] = field(default_factory=list)

    @property
    def shot_count(self) -> int:
        return len(self.shots)

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.fps if self.fps else 0.0


@functools.lru_cache(maxsize=1)
def _load_detection_model_cached(checkpoint_repo: str, checkpoint_filename: str, device: str):
    model = TransNetV2(device=device)
    weights_path = hf_hub_download(repo_id=checkpoint_repo, filename=checkpoint_filename)
    state_dict = torch.load(weights_path, map_location=model.device)
    model.load_state_dict(state_dict)
    model.eval()
    return model


def load_detection_model(
    checkpoint_repo: str = DEFAULT_CHECKPOINT_REPO,
    checkpoint_filename: str = DEFAULT_CHECKPOINT_FILENAME,
    device: str = DEFAULT_DEVICE,
):
    """Load TransNetV2 onto `device`, caching it so repeated detections reuse one model.

    Weights are a HuggingFace repo ID by default, downloaded to the HuggingFace cache on
    first use; a local .pth path also works.

    The defaults are resolved before the cache is consulted, because an lru_cache keys on
    how a function was called: caching this function directly would treat a call that
    omits the arguments and one that passes those same defaults as two separate models,
    and each would evict the other from the single-entry cache.
    """
    return _load_detection_model_cached(checkpoint_repo, checkpoint_filename, device)


def _merge_short_shots(shots: list[Shot], min_duration_seconds: float) -> list[Shot]:
    """Merge every shot shorter than `min_duration_seconds` into a neighboring shot.

    A short shot is absorbed into the previous shot by extending the previous shot's end
    to cover it. The video's opening shot has no previous shot, so if it is itself too
    short it is instead absorbed forward into the shot after it.

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


def detect_shots(
    video_path: str,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    min_shot_duration_seconds: float = DEFAULT_MIN_SHOT_DURATION_SECONDS,
    checkpoint_repo: str = DEFAULT_CHECKPOINT_REPO,
    checkpoint_filename: str = DEFAULT_CHECKPOINT_FILENAME,
    device: str = DEFAULT_DEVICE,
) -> ShotDetectionResult:
    """Detect every shot in `video_path`.

    The returned shots tile the whole video back to back, so `shot_count` is the number
    of shots it contains and each shot carries both its frame range and its timecode.

    `threshold` is the per-frame boundary probability above which TransNetV2 calls a
    frame a shot boundary; raising it finds fewer, more confident cuts.

    `min_shot_duration_seconds` merges away shots shorter than that into a neighbor,
    cleaning up spurious sub-second shots near noisy boundaries.
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    model = load_detection_model(checkpoint_repo, checkpoint_filename, device)

    with torch.no_grad():
        analysis = model.analyze_video(video_path)

    fps = float(analysis["fps"])
    scenes = model.predictions_to_scenes_with_data(
        analysis["single_frame_predictions"], fps=fps, threshold=threshold
    )

    shots = [
        Shot(
            index=index,
            start_frame=round(scene["start_time"] * fps),
            end_frame=round(scene["end_time"] * fps),
            start_seconds=scene["start_time"],
            end_seconds=scene["end_time"],
        )
        for index, scene in enumerate(scenes)
    ]

    shots = _merge_short_shots(shots, min_shot_duration_seconds)

    frame_count = shots[-1].end_frame if shots else 0
    return ShotDetectionResult(
        video_path=video_path, fps=fps, frame_count=frame_count, shots=shots
    )
