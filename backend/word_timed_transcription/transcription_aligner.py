"""Transcribes a video and gives every word a timestamp, by running both modules in order.

`OpenAI_transcription` produces the text and `MMS_word_alignment` times it. Neither module
knows about the other, and this is the only place that imports both, so deleting either one
breaks this module alone and leaves the other working.

Each transcription chunk is aligned against its own span of the audio, with the chunk's
start added back, so the word times are absolute against the whole video however many
requests the transcript took.
"""

import logging
from dataclasses import replace

from MMS_word_alignment import SAMPLE_RATE_HZ, align_samples, load_samples, normalize_words
from OpenAI_transcription import TranscriptChunk, TranscriptionResult, TranscriptWord
from OpenAI_transcription import transcribe_video
from OpenAI_transcription.transcriber import DEFAULT_LANGUAGES, DEFAULT_MAX_RETRIES

# Word alignment holds the whole span in memory at once, so it wants shorter chunks than
# transcription does: transcription alone is happy with 45 minutes a request. This is a
# conservative default rather than a measured ceiling, and the aligner falls back to the
# CPU if a chunk still does not fit on the GPU.
MAX_ALIGNMENT_SECONDS = 10 * 60

logger = logging.getLogger(__name__)


def _chunk_samples(samples, chunk: TranscriptChunk):
    """The slice of the decoded audio that one transcript chunk covers."""
    start = max(0, int(chunk.start_seconds * SAMPLE_RATE_HZ))
    end = min(len(samples), int(chunk.end_seconds * SAMPLE_RATE_HZ))
    return samples[start:end]


def add_word_timestamps(
    result: TranscriptionResult,
    *,
    device: str | None = None,
) -> TranscriptionResult:
    """Return `result` with every chunk's `words` filled in by forced alignment.

    A chunk whose text cannot be aligned — it is empty, or holds nothing but symbols —
    keeps its empty word list and is logged, rather than failing the whole video.
    """
    samples = load_samples(result.video_path)

    aligned_chunks = []
    for chunk in result.chunks:
        if not chunk.text.strip():
            aligned_chunks.append(chunk)
            continue

        try:
            aligned = align_samples(
                _chunk_samples(samples, chunk),
                normalize_words(chunk.text.split()),
                device=device,
                offset_seconds=chunk.start_seconds,
            )
        except ValueError as error:
            logger.warning(
                "Leaving chunk %d of %s without word timestamps: %s",
                chunk.index,
                result.video_path,
                error,
            )
            aligned_chunks.append(chunk)
            continue

        aligned_chunks.append(
            replace(
                chunk,
                words=[
                    TranscriptWord(
                        text=word.text,
                        start_seconds=word.start_seconds,
                        end_seconds=word.end_seconds,
                    )
                    for word in aligned
                ],
            )
        )

    return replace(result, chunks=aligned_chunks)


def transcribe_video_with_word_timestamps(
    video_path: str,
    *,
    languages: tuple[str, ...] = DEFAULT_LANGUAGES,
    keywords: list[str] | None = None,
    shot_spans: list[tuple[float, float]] | None = None,
    max_chunk_seconds: float = MAX_ALIGNMENT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    device: str | None = None,
) -> TranscriptionResult:
    """Transcribe `video_path` and time every word in the result.

    This is the whole pipeline: one transcription request per chunk, then one local
    alignment pass per chunk. The returned result has `has_word_timestamps` set and every
    word timed against the video rather than against its chunk.
    """
    result = transcribe_video(
        video_path,
        languages=languages,
        keywords=keywords,
        shot_spans=shot_spans,
        max_chunk_seconds=max_chunk_seconds,
        max_retries=max_retries,
    )
    return add_word_timestamps(result, device=device)
