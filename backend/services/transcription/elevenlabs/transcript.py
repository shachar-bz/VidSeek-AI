"""The transcript data model of the ElevenLabs transcription module.

A transcript holds the whole video's speech as one text, the per-word timing and speaker
label that make that text seekable, and the non-speech sounds heard alongside it.

Words and audio events are kept in separate lists on purpose. Scribe returns them
interleaved in a single array, and leaving them mixed corrupts anything built on top:
a word index picks up `[music]` as if someone had said it, and a word count counts it.
"""

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TranscriptWord:
    """One spoken word, timed against the video and attributed to a speaker."""

    text: str
    start_seconds: float
    end_seconds: float
    speaker_id: str | None
    logprob: float

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds

    @property
    def confidence(self) -> float:
        """How sure the model was of this word, as a probability between 0 and 1.

        `logprob` is the natural log of that probability, which is the convenient form to
        sum over a phrase but not one to rank or threshold by eye. This is the same
        number on a readable scale.
        """
        return math.exp(self.logprob)


@dataclass(frozen=True)
class TranscriptAudioEvent:
    """One non-speech sound Scribe tagged, such as music, laughter or applause.

    `label` is kept exactly as returned, brackets and all, because Scribe writes it in
    the language it detected rather than in English: a Hebrew video yields
    `[מוזיקה דרמטית]`, not `(music)`. Anything matching on these labels therefore has to
    be language-aware, so the language they are in stays on `TranscriptionResult`.
    """

    label: str
    start_seconds: float
    end_seconds: float

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True)
class TranscriptionResult:
    """Everything transcribed from one video.

    `text` is Scribe's own transcript, which reads as the video sounds: audio event tags
    appear inline among the words. `speech_text` is the same transcript with only what
    was actually spoken, which is the one to index for search.
    """

    video_path: str
    text: str
    language_code: str
    language_probability: float
    duration_seconds: float
    model: str
    words: list[TranscriptWord] = field(default_factory=list)
    audio_events: list[TranscriptAudioEvent] = field(default_factory=list)

    @property
    def speaker_ids(self) -> list[str]:
        """Every speaker who actually says a word, in the order each is first heard.

        Deliberately ignores `audio_events`: diarization labels those too, and it hands
        a sound with no speaker behind it — a music bed, say — a speaker id of its own.
        Counting those would report more people in the video than ever speak in it.
        """
        return list(dict.fromkeys(word.speaker_id for word in self.words if word.speaker_id))

    @property
    def speech_text(self) -> str:
        """The spoken words alone, with every audio event tag left out."""
        return " ".join(word.text for word in self.words)

    @property
    def word_count(self) -> int:
        return len(self.words)
