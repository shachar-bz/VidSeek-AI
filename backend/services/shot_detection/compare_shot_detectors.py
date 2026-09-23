"""Runs every shot detector on the same videos and writes a side-by-side comparison.

For each video, each detector (PySceneDetect, OmniShotCut, TransNetV2) is run once,
decoding at its own resolution. Model loading is timed apart from detection, so the
latency reported is what a warm service would pay per video. The output lands in
`results/`:

* `results.md`   - shot counts, latency, and every cut aligned across detectors.
* `results.json` - the raw shots, for anything that wants to re-analyse them.
* `images/<video>/<detector>/` - one frame grabbed at the start of every detected shot.

Usage (from the repo root):

    python -m backend.services.shot_detection.compare_shot_detectors \
        "Course Overview=path/to/course.webm" "Goodbye Tokenmaxxing=path/to/talk.mp4"
"""

from __future__ import annotations

import argparse
import gc
import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import ffmpeg
import torch

from backend.services.shot_detection import omni, pyscenedetect, transnetv2

RESULTS_DIR = Path(__file__).parent / "results"
IMAGES_DIRNAME = "images"

# Two detectors' cuts closer together than this are treated as the same cut. A detector
# may place a cut a few frames early or late, and a dissolve can be reported anywhere
# inside the transition, so exact-frame matching would undercount agreement.
MATCH_TOLERANCE_SECONDS = 0.5

SCREENSHOT_WIDTH = 480
THUMBNAIL_DISPLAY_WIDTH = 160


@dataclass(frozen=True)
class DetectorSpec:
    """One detector as the comparison runs it."""

    key: str
    display_name: str
    resolution_policy: str
    load_model: object  # callable() -> None, warms any model cache
    detect_shots: object  # callable(video_path) -> ShotDetectionResult
    release_model: object  # callable() -> None, frees GPU memory for the next detector


def _clear_cache(cached_function) -> None:
    cached_function.cache_clear()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


DETECTORS = [
    DetectorSpec(
        key="pyscenedetect",
        display_name="PySceneDetect",
        resolution_policy=f"downscaled towards {pyscenedetect.shot_detector.TARGET_PROCESS_WIDTH} px wide, on the CPU",
        load_model=lambda: None,
        detect_shots=pyscenedetect.detect_shots,
        release_model=lambda: None,
    ),
    DetectorSpec(
        key="omni",
        display_name="OmniShotCut",
        resolution_policy="the checkpoint's own process resolution, on the GPU",
        load_model=omni.load_detection_model,
        detect_shots=omni.detect_shots,
        release_model=lambda: _clear_cache(omni.shot_detector._load_detection_model_cached),
    ),
    DetectorSpec(
        key="transnetv2",
        display_name="TransNetV2",
        resolution_policy="fixed 48x27, on the GPU",
        load_model=transnetv2.load_detection_model,
        detect_shots=transnetv2.detect_shots,
        release_model=lambda: _clear_cache(transnetv2.shot_detector._load_detection_model_cached),
    ),
]


@dataclass(frozen=True)
class DetectorRun:
    """One detector's result on one video, with how long it took."""

    detector: DetectorSpec
    result: object
    load_seconds: float
    detect_seconds: float

    @property
    def cut_seconds(self) -> list[float]:
        """Where each new shot begins, excluding the video's opening frame."""
        return [shot.start_seconds for shot in self.result.shots[1:]]


@dataclass(frozen=True)
class VideoInput:
    title: str
    path: Path

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "_", self.title.lower()).strip("_")


def _format_timestamp(seconds: float) -> str:
    minutes, remainder = divmod(seconds, 60)
    return f"{int(minutes):02d}:{remainder:06.3f}"


def _probe_source(video_path: Path) -> tuple[int, int, float]:
    probe = ffmpeg.probe(str(video_path))
    stream = next(s for s in probe["streams"] if s["codec_type"] == "video")
    return int(stream["width"]), int(stream["height"]), float(probe["format"]["duration"])


def _run_detector(detector: DetectorSpec, video: VideoInput) -> DetectorRun:
    started = time.perf_counter()
    detector.load_model()
    load_seconds = time.perf_counter() - started

    started = time.perf_counter()
    result = detector.detect_shots(str(video.path))
    detect_seconds = time.perf_counter() - started

    return DetectorRun(detector, result, load_seconds, detect_seconds)


def _grab_frame(video_path: Path, seconds: float, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    (
        ffmpeg.input(str(video_path), ss=f"{seconds:.3f}")
        .output(str(destination), vframes=1, vf=f"scale={SCREENSHOT_WIDTH}:-2", **{"q:v": 3})
        .overwrite_output()
        .run(capture_stdout=True, capture_stderr=True)
    )


def _screenshot_path(video: VideoInput, detector_key: str, shot) -> Path:
    stamp = _format_timestamp(shot.start_seconds).replace(":", "m") + "s"
    return (
        RESULTS_DIR / IMAGES_DIRNAME / video.slug / detector_key
        / f"shot_{shot.index:03d}_{stamp}.jpg"
    )


def _write_screenshots(video: VideoInput, run: DetectorRun) -> dict[int, Path]:
    paths = {}
    for shot in run.result.shots:
        path = _screenshot_path(video, run.detector.key, shot)
        _grab_frame(video.path, shot.start_seconds, path)
        paths[shot.index] = path
    return paths


def _align_cuts(runs: list[DetectorRun]) -> list[dict[str, tuple[int, float] | None]]:
    """Group every detector's cuts into rows of cuts that are the same moment.

    Cuts are swept in time order; a cut joins the open row if it is within the tolerance
    of that row's first cut and its detector has not already filled that row, and starts a
    new row otherwise. Each row maps detector key -> (shot index, cut seconds) or None.
    """
    events = sorted(
        (seconds, run.detector.key, shot_index)
        for run in runs
        for shot_index, seconds in enumerate(run.cut_seconds, start=1)
    )
    rows: list[dict] = []
    row_anchor = None
    for seconds, key, shot_index in events:
        current = rows[-1] if rows else None
        if (
            current is not None
            and seconds - row_anchor <= MATCH_TOLERANCE_SECONDS
            and current[key] is None
        ):
            current[key] = (shot_index, seconds)
            continue
        rows.append({run.detector.key: None for run in runs})
        rows[-1][key] = (shot_index, seconds)
        row_anchor = seconds
    return rows


def _relative(path: Path) -> str:
    return path.relative_to(RESULTS_DIR).as_posix()


def _video_section(
    video: VideoInput,
    runs: list[DetectorRun],
    screenshots: dict[str, dict[int, Path]],
) -> list[str]:
    width, height, duration = _probe_source(video.path)
    lines = [
        f"## {video.title}",
        "",
        f"Source: {width}x{height}, {duration:.1f} s ({_format_timestamp(duration)}), "
        f"`{video.path.name}`",
        "",
        "### Summary",
        "",
        "| Detector | Process resolution | Shots | Cuts | Model load (s) | Detection (s) "
        "| Speed (x realtime) | Mean shot (s) |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for run in runs:
        result = run.result
        mean_shot = duration / result.shot_count if result.shot_count else 0.0
        lines.append(
            f"| {run.detector.display_name} | {result.process_width}x{result.process_height} "
            f"| {result.shot_count} | {len(run.cut_seconds)} | {run.load_seconds:.2f} "
            f"| {run.detect_seconds:.2f} | {duration / run.detect_seconds:.1f} | {mean_shot:.1f} |"
        )

    rows = _align_cuts(runs)
    keys = [run.detector.key for run in runs]
    agreement_counts = {n: 0 for n in range(1, len(runs) + 1)}
    for row in rows:
        agreement_counts[sum(row[key] is not None for key in keys)] += 1

    lines += [
        "",
        "### Agreement",
        "",
        f"Cuts within {MATCH_TOLERANCE_SECONDS} s of each other are counted as the same cut.",
        "",
        "| Found by | Cuts |",
        "|---|---:|",
    ]
    for n in sorted(agreement_counts, reverse=True):
        label = "all detectors" if n == len(runs) else f"{n} detector{'s' if n > 1 else ''}"
        lines.append(f"| {label} | {agreement_counts[n]} |")

    lines.append("")
    lines.append("| Only found by | Cuts |")
    lines.append("|---|---:|")
    for run in runs:
        only = sum(
            1 for row in rows
            if row[run.detector.key] is not None
            and all(row[k] is None for k in keys if k != run.detector.key)
        )
        lines.append(f"| {run.detector.display_name} | {only} |")

    header_names = " | ".join(run.detector.display_name for run in runs)
    lines += [
        "",
        "### Cuts, aligned across detectors",
        "",
        "Each row is one moment in the video. A cell shows the timestamp (mm:ss.sss) at which "
        "that detector starts a new shot and the frame grabbed there; `—` means it found no "
        "cut there. The opening shot at 00:00 is listed first for reference.",
        "",
        f"| # | {header_names} |",
        "|---:|" + "---|" * len(runs),
    ]

    def cell(key: str, shot_index: int, seconds: float) -> str:
        image = _relative(screenshots[key][shot_index])
        return (
            f"{_format_timestamp(seconds)}<br>"
            f'<img src="{image}" width="{THUMBNAIL_DISPLAY_WIDTH}">'
        )

    lines.append(
        "| 0 | " + " | ".join(cell(key, 0, 0.0) for key in keys) + " |"
    )
    for row_number, row in enumerate(rows, start=1):
        cells = [
            cell(key, row[key][0], row[key][1]) if row[key] is not None else "—"
            for key in keys
        ]
        lines.append(f"| {row_number} | " + " | ".join(cells) + " |")

    lines.append("")
    return lines


def _run_json(video: VideoInput, runs: list[DetectorRun]) -> dict:
    return {
        "title": video.title,
        "file": video.path.name,
        "detectors": {
            run.detector.key: {
                "process_resolution": [run.result.process_width, run.result.process_height],
                "fps": run.result.fps,
                "frame_count": run.result.frame_count,
                "load_seconds": run.load_seconds,
                "detect_seconds": run.detect_seconds,
                "shots": [
                    {
                        "index": shot.index,
                        "start_frame": shot.start_frame,
                        "end_frame": shot.end_frame,
                        "start_seconds": shot.start_seconds,
                        "end_seconds": shot.end_seconds,
                        **(
                            {"transition_type": shot.transition_type}
                            if hasattr(shot, "transition_type") else {}
                        ),
                    }
                    for shot in run.result.shots
                ],
            }
            for run in runs
        },
    }


def _parse_video_argument(argument: str) -> VideoInput:
    title, separator, path = argument.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError(f"Expected TITLE=PATH, got {argument!r}")
    video_path = Path(path)
    if not video_path.is_file():
        raise argparse.ArgumentTypeError(f"Video not found: {video_path}")
    return VideoInput(title=title.strip(), path=video_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("videos", nargs="+", type=_parse_video_argument, metavar="TITLE=PATH")
    videos = parser.parse_args().videos

    shutil.rmtree(RESULTS_DIR / IMAGES_DIRNAME, ignore_errors=True)
    runs_by_video: dict[str, list[DetectorRun]] = {video.slug: [] for video in videos}

    # Detector-major order: each model is loaded once, used on every video, then released
    # so the next one has the GPU to itself.
    for detector in DETECTORS:
        for video in videos:
            print(f"[{detector.display_name}] {video.title} ...", flush=True)
            run = _run_detector(detector, video)
            print(
                f"    {run.result.shot_count} shots, load {run.load_seconds:.2f}s, "
                f"detect {run.detect_seconds:.2f}s",
                flush=True,
            )
            runs_by_video[video.slug].append(run)
        detector.release_model()

    report = [
        "# Shot detection comparison",
        "",
        "Generated by `compare_shot_detectors.py`. Every detector gets the same source file "
        "and decodes it at its own resolution:",
        "",
    ]
    report += [f"* **{d.display_name}** — {d.resolution_policy}." for d in DETECTORS]
    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none"
    report += [
        "",
        "Latency: *model load* is the one-off cost of loading weights (cached after the "
        "first video, so the second video shows ~0). *Detection* is decode + inference for "
        "one video with the model already loaded — the per-video cost of a warm service. "
        f"Hardware: GPU {gpu}. All detectors run at their default settings.",
        "",
    ]

    all_json = []
    for video in videos:
        runs = runs_by_video[video.slug]
        print(f"Grabbing screenshots for {video.title} ...", flush=True)
        screenshots = {run.detector.key: _write_screenshots(video, run) for run in runs}
        report += _video_section(video, runs, screenshots)
        all_json.append(_run_json(video, runs))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "results.md").write_text("\n".join(report), encoding="utf-8")
    (RESULTS_DIR / "results.json").write_text(json.dumps(all_json, indent=2), encoding="utf-8")
    print(f"Wrote {RESULTS_DIR / 'results.md'}")


if __name__ == "__main__":
    main()
