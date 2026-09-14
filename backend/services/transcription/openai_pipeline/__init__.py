"""Groups the OpenAI-based transcription pipeline: transcription, word alignment, and both
run together.

Three independently-focused modules that only make sense next to each other:
`transcription` produces text via OpenAI's gpt-transcribe, `word_alignment` times any
transcript's words against its audio, and `word_timed` is the glue that runs both in order.
Each stays importable on its own; this package just gives them one place to live, alongside
`elevenlabs` which does the same job as a single hosted call.
"""
