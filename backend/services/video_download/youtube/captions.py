"""Reads YouTube's own caption track for a video, so that nothing has to be transcribed.

Most videos already carry captions — written by the uploader, or produced by YouTube's own
speech recognition — and reading them costs no API call, no model and no minutes of audio
processing. That makes captions the first thing to try, and transcribing the audio the
fallback for the videos that have none.

A hand-written track wins over an automatic one for the same language: the automatic ones
mishear names and come with no punctuation. Returning None means the video has no captions
in any of the requested languages, which is the pipeline's signal to transcribe instead.

The two kinds of track measure timing at different granularities, and this module keeps
whichever one a track actually offers rather than flattening both to the coarser one. A
hand-written track only ever times whole cues. An automatic track additionally stamps when
each word inside a cue appears — `<00:00:04.120>` — and that per-word timing is preserved
as `TimingFidelity.WORD` instead of being discarded as styling noise.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from yt_dlp import YoutubeDL

from backend.core.captions import CaptionSegment, clean_caption_text, parse_timestamp_seconds
from backend.services.transcripts import TimingFidelity

from .downloader import build_download_options

SUBTITLE_FORMAT = "vtt"

CUE_TIMING_SEPARATOR = "-->"

# Only the word stamps among the tags a cue may carry, captured so its text can be split
# on them. `<c>` styling tags are left to `clean_caption_text`.
WORD_TIMESTAMP_PATTERN = re.compile(r"<(\d{2}:\d{2}:\d{2}\.\d{3})>")

# WebVTT separates one cue from the next with a blank line.
CUE_SEPARATOR_PATTERN = re.compile(r"\n\s*\n")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchedCaptions:
    """A caption track's segments, at whatever granularity it actually measured."""

    segments: list[CaptionSegment]
    timing_fidelity: TimingFidelity


def _match_language(tracks: dict, language: str) -> str | None:
    """Find `language` among the tracks on offer, tolerating a regional tag.

    Asking for `en` should still find a video whose only English captions are tagged
    `en-US`, and asking for `he` should find `he-IL`.
    """
    if language in tracks:
        return language

    prefix = f"{language}-"
    return next((code for code in sorted(tracks) if code.startswith(prefix)), None)


def _select_track(info: dict, languages: tuple[str, ...]) -> tuple[str, bool] | None:
    """Choose the caption track to read, as `(language code, is automatic)`.

    Every hand-written track is considered before any automatic one, so a video captioned
    by its uploader in the second-choice language is still preferred over YouTube's
    transcription of the first.
    """
    manual = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}

    for tracks, is_automatic in ((manual, False), (automatic, True)):
        for language in languages:
            code = _match_language(tracks, language)
            if code:
                return code, is_automatic

    return None


def _iter_cues(vtt_text: str):
    """Yield each cue as `(start_seconds, end_seconds, text_lines)`, skipping non-cue blocks.

    A block with no timing line is the WEBVTT header, a NOTE or a style block, and is left
    out entirely. `text_lines` is everything after the timing line; a line before it is the
    cue's optional identifier, which is not part of what anyone said.
    """
    for block in CUE_SEPARATOR_PATTERN.split(vtt_text.replace("\r\n", "\n")):
        lines = block.splitlines()
        timing_index = next(
            (index for index, line in enumerate(lines) if CUE_TIMING_SEPARATOR in line),
            None,
        )
        if timing_index is None:
            continue

        start_raw, _, end_raw = lines[timing_index].partition(CUE_TIMING_SEPARATOR)
        # Cue settings such as `align:start position:0%` ride along after the end stamp.
        end_stamp = end_raw.split()
        if not end_stamp:
            continue

        yield (
            parse_timestamp_seconds(start_raw),
            parse_timestamp_seconds(end_stamp[0]),
            lines[timing_index + 1 :],
        )


def _parse_cue_lines(cues) -> list[CaptionSegment]:
    """One segment per cue, dropping styling tags and the lines a cue only repeats.

    Automatic tracks scroll: each cue repeats the lines of the one before it with a new
    line added underneath, so a line is kept only the first time it is seen. The cost is
    that a line genuinely said twice in a row collapses into one, which is a far smaller
    problem than a transcript with every line doubled.
    """
    segments: list[CaptionSegment] = []
    previous_line = None

    for start_seconds, end_seconds, lines in cues:
        texts = []
        for line in lines:
            cleaned = clean_caption_text(line)
            if not cleaned or cleaned == previous_line:
                continue
            texts.append(cleaned)
            previous_line = cleaned

        if not texts:
            continue

        segments.append(
            CaptionSegment(
                text=" ".join(texts),
                start_seconds=start_seconds,
                end_seconds=end_seconds,
            )
        )

    return segments


def _parse_word_timings(cues) -> list[CaptionSegment]:
    """One segment per word, from the `<HH:MM:SS.mmm>` stamps automatic tracks embed in a cue.

    Only a line carrying at least one stamp is new text. An automatic track also redraws
    each earlier cue's line once more with no stamps at all, purely so the caption reads
    smoothly on screen as it scrolls; that repeat carries no word this has not already
    timed, so it is skipped rather than read as those words being said a second time.

    A word's end is the next word's start, which is itself a measured stamp; only the very
    last word has no next word to borrow from, so it takes the end of the cue it was last
    seen in — the one other boundary this track measured.
    """
    words: list[list] = []
    last_cue_end: float | None = None

    for start_seconds, end_seconds, lines in cues:
        added_from_this_cue = False
        for line in lines:
            if not WORD_TIMESTAMP_PATTERN.search(line):
                continue
            word_start = start_seconds
            for index, chunk in enumerate(WORD_TIMESTAMP_PATTERN.split(line)):
                if index % 2 == 1:
                    word_start = parse_timestamp_seconds(chunk)
                    continue
                cleaned = clean_caption_text(chunk)
                if cleaned:
                    words.append([cleaned, word_start, None])
                    added_from_this_cue = True
        if added_from_this_cue:
            last_cue_end = end_seconds

    for index in range(len(words) - 1):
        words[index][2] = words[index + 1][1]
    if words:
        words[-1][2] = max(last_cue_end if last_cue_end is not None else words[-1][1], words[-1][1])

    return [
        CaptionSegment(text=text, start_seconds=start, end_seconds=end) for text, start, end in words
    ]


def parse_vtt(vtt_text: str, *, is_automatic: bool = False) -> tuple[list[CaptionSegment], TimingFidelity]:
    """Turn a WebVTT file into timed segments, at the finest granularity it actually measured.

    A hand-written track only ever times whole cues, so it always comes back as
    `TimingFidelity.CAPTION`. An automatic track additionally stamps when each word inside
    a cue appears, and those are read as one segment per word — `TimingFidelity.WORD` — so
    that nothing downstream has to treat a caption-derived transcript as coarser than it
    has to be. A track flagged automatic but carrying no word stamps (some languages, or an
    older track) falls back to cue segments rather than being read as having no captions.
    """
    cues = list(_iter_cues(vtt_text))
    if is_automatic:
        word_segments = _parse_word_timings(cues)
        if word_segments:
            return word_segments, TimingFidelity.WORD

    return _parse_cue_lines(cues), TimingFidelity.CAPTION


def fetch_captions(
    url: str,
    output_dir: str | Path,
    *,
    languages: tuple[str, ...],
) -> FetchedCaptions | None:
    """Read the best caption track YouTube has for `url` in one of `languages`.

    `languages` is in preference order. The raw `.vtt` is left in `output_dir` beside the
    video: it is the unedited original, and keeping it means a parsing change can be
    replayed against it without going back to YouTube.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_options = build_download_options(output_dir) | {"skip_download": True}
    with YoutubeDL(base_options) as reader:
        info = reader.extract_info(url, download=False)

    selection = _select_track(info, languages)
    if selection is None:
        logger.info("%s has no captions in any of: %s", url, ", ".join(languages))
        return None

    language_code, is_automatic = selection
    with YoutubeDL(
        base_options
        | {
            "writesubtitles": not is_automatic,
            "writeautomaticsub": is_automatic,
            "subtitleslangs": [language_code],
            "subtitlesformat": SUBTITLE_FORMAT,
        }
    ) as downloader:
        downloader.extract_info(url, download=True)

    captions_path = output_dir / f"{info['id']}.{language_code}.{SUBTITLE_FORMAT}"
    if not captions_path.is_file():
        logger.warning(
            "yt-dlp listed %s captions for %s but wrote no file to %s",
            language_code,
            url,
            captions_path,
        )
        return None

    segments, timing_fidelity = parse_vtt(
        captions_path.read_text(encoding="utf-8"), is_automatic=is_automatic
    )
    if not segments:
        return None

    logger.info(
        "Read %d %s caption segments for %s (%s, %s)",
        len(segments),
        language_code,
        url,
        "automatic" if is_automatic else "hand-written",
        timing_fidelity.value,
    )
    return FetchedCaptions(segments=segments, timing_fidelity=timing_fidelity)
