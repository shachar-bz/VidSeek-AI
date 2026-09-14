"""Groups the OpenAI-based transcription pipeline: transcription, word alignment, and both
run together.

Three independently-focused modules that only make sense next to each other:
`OpenAI_transcription` produces text via OpenAI's gpt-transcribe, `MMS_word_alignment`
times any transcript's words against its audio, and `word_timed_transcription` is the glue
that runs both in order. Each stays importable on its own; this package just gives them one
place to live rather than sitting loose at `backend/`, alongside `ElevenLabs_transcription`
which does the same job as a single hosted call.
"""
