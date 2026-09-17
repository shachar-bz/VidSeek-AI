"""The instruction the chapter grouping model is given, and nothing else.

The prompt lives alone in its own module, as the docstring of the function that returns
it, so that it can be read and reviewed as prose rather than as a string literal wrapped
in quotes and escapes. `inspect.cleandoc` strips the indentation the docstring picks up
from the function body, so what the model receives is the text exactly as written here.
"""

import inspect


def chapter_grouping_prompt() -> str:
    """
    You are given an ordered list of semantic memories from a video.

    Each memory represents a coherent idea, point, story, argument, or discussion from the video and includes its timestamp and a short summary.

    Your task is to group consecutive memories into meaningful higher-level chapters.

    A chapter is a larger semantic section of the video that contains several related memories focused on the same broader topic, theme, argument, story, or stage of the discussion.

    The goal is to create chapters that will later be useful for high-level semantic search, embeddings, navigation, and answering user questions about broader sections of the video.

    Rules:

    Group memories based on semantic meaning, not based on fixed duration or number of memories.
    Create a new chapter when the broader topic, theme, argument, story, or discussion clearly changes.
    Do not merge clearly different topics into the same chapter just to make chapters larger.
    Preserve the chronological order of the memories.
    Every memory must belong to exactly one chapter.
    Chapters must not overlap.
    Return start_memory_id and end_memory_id instead of generating timestamps.
    Use only the provided memory IDs and never invent, modify, reorder, or skip memory IDs.
    Base your decision only on the provided memory summaries and their order.

    For each chapter, return:

    start_memory_id: the first memory belonging to the chapter
    end_memory_id: the last memory belonging to the chapter
    title: a short, clear, human-readable name for the chapter. It should be briefly identify the main topic of the chapter and be useful for navigation
    summary: a description of the broader topic or discussion covered by the chapter. It should describe the overall subject of the chapter rather than simply repeating or concatenating the individual memory summaries.
    """
    return inspect.cleandoc(chapter_grouping_prompt.__doc__)
