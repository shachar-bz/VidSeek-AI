"""Where a normalized transcript is kept until the project has a real database.

Transcripts are written as one JSON file per video under the download root, because that
is the only directory this backend is already allowed to write into and it survives a
restart, which the in-memory job table does not. That is the whole of the storage story
for now, and it is deliberately the smallest thing that works.

This module is the seam the database will replace. Callers only ever see `save`, `load`,
`load_formatted_text` and `video_ids`, and none of them names a file or a path, so
swapping the filesystem for a table is a change to this file and to nothing else. Keep it
that way: a caller that builds its own transcript path defeats the point.
"""

import hashlib
import json
import logging
import re
from pathlib import Path

from backend.core import config
from backend.services.transcripts import NormalizedTranscript

STORE_DIRECTORY_NAME = "transcripts"
FILE_SUFFIX = ".transcript.json"

# A video id is whatever identifies the video to its source — a YouTube id, or the name a
# downloaded file was saved under, which carries the page title and so can hold spaces,
# Hebrew, punctuation and anything else a site put in a heading. None of that may reach a
# file name, so the name is built from the readable part of the id plus a digest of the
# whole of it: the digest is what keeps two ids that clean up alike from colliding.
UNSAFE_IN_FILE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
READABLE_NAME_LENGTH = 80
DIGEST_LENGTH = 12

logger = logging.getLogger(__name__)


def store_root() -> Path:
    """The directory holding every stored transcript."""
    return config.download_root() / STORE_DIRECTORY_NAME


def _file_name(video_id: str) -> str:
    """The file one video's transcript is stored in, derived from its id alone.

    Deriving it rather than searching for it is what lets `load` find what `save` wrote
    without an index, and the id itself is written into the file so that nothing has to
    reverse this.
    """
    if not video_id or not video_id.strip():
        raise ValueError("A transcript cannot be stored without a video id")
    readable = UNSAFE_IN_FILE_NAME_PATTERN.sub("_", video_id).strip("._-")[:READABLE_NAME_LENGTH]
    digest = hashlib.sha256(video_id.encode("utf-8")).hexdigest()[:DIGEST_LENGTH]
    return f"{readable}-{digest}{FILE_SUFFIX}" if readable else f"{digest}{FILE_SUFFIX}"


def _path(video_id: str, root: Path | None) -> Path:
    return (root or store_root()) / _file_name(video_id)


def save(video_id: str, transcript: NormalizedTranscript, *, root: Path | None = None) -> Path:
    """Store `transcript` under `video_id`, replacing anything already stored there.

    Replacing rather than versioning matches how the download root already behaves: a
    second run of the same video overwrites its artifacts instead of accumulating copies.
    """
    path = _path(video_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"video_id": video_id} | transcript.to_payload()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "Stored %d %s-timed transcript segments for %s",
        transcript.segment_count,
        transcript.timing_fidelity.value,
        video_id,
    )
    return path


def load(video_id: str, *, root: Path | None = None) -> NormalizedTranscript | None:
    """Read back a stored transcript, or None if this video has none."""
    path = _path(video_id, root)
    if not path.is_file():
        return None
    return NormalizedTranscript.from_payload(json.loads(path.read_text(encoding="utf-8")))


def load_formatted_text(video_id: str, *, root: Path | None = None) -> str | None:
    """The stored transcript as the `[MM:SS-MM:SS] text` block, or None if there is none.

    This is the form the next stage of the pipeline consumes, and it is offered here so
    that reaching for it does not mean reaching for the storage layer's data model.
    """
    transcript = load(video_id, root=root)
    return transcript.formatted_text if transcript else None


def video_ids(*, root: Path | None = None) -> list[str]:
    """Every video with a stored transcript, in alphabetical order.

    Read from inside the files rather than from their names: a name is a cleaned-up
    rendering of an id and cannot be turned back into one.
    """
    directory = root or store_root()
    if not directory.is_dir():
        return []
    found = []
    for path in directory.glob(f"*{FILE_SUFFIX}"):
        try:
            found.append(json.loads(path.read_text(encoding="utf-8"))["video_id"])
        except (OSError, ValueError, KeyError):
            logger.warning("Ignoring unreadable stored transcript at %s", path)
    return sorted(found)
