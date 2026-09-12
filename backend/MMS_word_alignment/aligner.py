"""Gives each word of a transcript a start and end time, by aligning it to the audio.

Wraps torchaudio's MMS forced aligner (`torchaudio.pipelines.MMS_FA`), a CTC model trained
on over a thousand languages. It is used here in preference to a Hebrew-specific model
because this project's videos code-switch: a Hebrew-only vocabulary would have no tokens
for the English words in a Hebrew sentence, leaving a hole at every one of them. MMS works
on romanized text, so Hebrew and English land in the same alphabet.

Alignment is a batch job, and it runs on the GPU when one is available and on the CPU
otherwise. It needs the audio and the transcript together: this is not recognition, so a
word the transcript does not contain can never be produced.

Requires the ffmpeg binary on PATH.
"""

import functools
from dataclasses import dataclass, field

import numpy as np
import torch
import torchaudio

from .audio_loader import SAMPLE_RATE_HZ, duration_seconds, load_samples
from .text_normalizer import NormalizedWord, normalize_text, normalize_words

# The model emits one probability distribution per frame rather than per sample, so a
# frame index is converted to a time by scaling it by how many samples it stands for.
ALIGNMENT_BUNDLE = torchaudio.pipelines.MMS_FA


@dataclass(frozen=True)
class AlignedWord:
    """One transcript word, timed against the media it was spoken in."""

    index: int
    text: str
    start_seconds: float
    end_seconds: float
    score: float
    is_interpolated: bool = False

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True)
class AlignmentResult:
    """Every word of one transcript, timed against one media file."""

    media_path: str
    duration_seconds: float
    words: list[AlignedWord] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return len(self.words)

    @property
    def interpolated_word_count(self) -> int:
        """How many words got their timing from their neighbours rather than from the audio."""
        return sum(1 for word in self.words if word.is_interpolated)

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)


def _resolve_device(device: str | None) -> str:
    return device or ("cuda" if torch.cuda.is_available() else "cpu")


@functools.lru_cache(maxsize=2)
def _load_aligner(device: str):
    """Load the MMS model, tokenizer and aligner onto a device, once per device."""
    model = ALIGNMENT_BUNDLE.get_model().to(device).eval()
    return model, ALIGNMENT_BUNDLE.get_tokenizer(), ALIGNMENT_BUNDLE.get_aligner()


def _interpolate_missing(
    timed: list[AlignedWord | None],
    originals: list[NormalizedWord],
    start_seconds: float,
    end_seconds: float,
) -> list[AlignedWord]:
    """Give every unaligned word a time between the aligned words on either side of it.

    A word with nothing alignable in it — an emoji, a number the speller could not spell —
    would otherwise have to be dropped, and dropping one silently shifts the caller's idea
    of which word is which. Sharing out the gap between its neighbours keeps the word list
    complete and keeps a single failure from desynchronizing everything after it.
    """
    filled: list[AlignedWord] = []
    index = 0
    while index < len(timed):
        if timed[index] is not None:
            filled.append(timed[index])
            index += 1
            continue

        run_end = index
        while run_end < len(timed) and timed[run_end] is None:
            run_end += 1

        gap_start = filled[-1].end_seconds if filled else start_seconds
        next_aligned = next((word for word in timed[run_end:] if word is not None), None)
        gap_end = max(next_aligned.start_seconds if next_aligned else end_seconds, gap_start)

        run_length = run_end - index
        step = (gap_end - gap_start) / run_length
        for position in range(run_length):
            filled.append(
                AlignedWord(
                    index=index + position,
                    text=originals[index + position].original,
                    start_seconds=gap_start + position * step,
                    end_seconds=gap_start + (position + 1) * step,
                    score=0.0,
                    is_interpolated=True,
                )
            )
        index = run_end

    return filled


def align_samples(
    samples: np.ndarray,
    normalized: list[NormalizedWord],
    *,
    device: str | None = None,
    offset_seconds: float = 0.0,
) -> list[AlignedWord]:
    """Time every word in `normalized` against `samples`, in media-absolute seconds.

    `offset_seconds` is added to every time, so a chunk cut out of a longer video can be
    aligned on its own and still report times against the whole video.
    """
    device = _resolve_device(device)
    model, tokenizer, aligner = _load_aligner(device)

    alignable = [word for word in normalized if word.is_alignable]
    pieces = [piece for word in alignable for piece in word.romanized]
    if not pieces:
        raise ValueError("Nothing in this transcript can be aligned: no romanizable words.")

    waveform = torch.from_numpy(samples).unsqueeze(0).to(device)
    with torch.inference_mode():
        emission, _ = model(waveform)

    token_spans = aligner(emission[0], tokenizer(pieces))

    # The emission is one frame per group of samples; this is how many seconds a frame is.
    seconds_per_frame = waveform.size(1) / emission.size(1) / SAMPLE_RATE_HZ

    # Regroup the per-piece spans back onto the original words, since a word spelled out as
    # several spoken pieces was aligned as several sequences.
    timed_by_index: dict[int, AlignedWord] = {}
    piece_position = 0
    for word in alignable:
        spans = token_spans[piece_position : piece_position + len(word.romanized)]
        piece_position += len(word.romanized)
        flat = [span for group in spans for span in group]
        timed_by_index[word.index] = AlignedWord(
            index=word.index,
            text=word.original,
            start_seconds=offset_seconds + flat[0].start * seconds_per_frame,
            end_seconds=offset_seconds + flat[-1].end * seconds_per_frame,
            score=float(np.mean([span.score for span in flat])),
        )

    ordered: list[AlignedWord | None] = [timed_by_index.get(word.index) for word in normalized]
    return _interpolate_missing(
        ordered,
        normalized,
        start_seconds=offset_seconds,
        end_seconds=offset_seconds + duration_seconds(samples),
    )


def align_media(
    media_path: str,
    transcript: str | list[str],
    *,
    device: str | None = None,
    offset_seconds: float = 0.0,
) -> AlignmentResult:
    """Time every word of `transcript` against the speech in `media_path`.

    `transcript` is either the text or an already-split list of words; passing the list is
    what keeps the returned words identical to the ones the caller already holds.
    """
    samples = load_samples(media_path)
    normalized = (
        normalize_text(transcript) if isinstance(transcript, str) else normalize_words(transcript)
    )
    words = align_samples(samples, normalized, device=device, offset_seconds=offset_seconds)
    return AlignmentResult(
        media_path=media_path,
        duration_seconds=duration_seconds(samples),
        words=words,
    )
