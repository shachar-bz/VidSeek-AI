"""Turns a finished transcript into something more useful than its raw timeline.

Semantic processing is the umbrella for every stage that runs after transcription and
before a video is searchable. The stages build on each other: `semantic_processing.memories`
divides a transcript into memories, and `semantic_processing.chapters` groups those
memories into the broader sections of the video.
"""
