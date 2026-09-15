"""The instruction the segmentation model is given, and nothing else.

The prompt lives alone in its own module, as the docstring of the function that returns
it, so that it can be read and reviewed as prose rather than as a string literal wrapped
in quotes and escapes. `inspect.cleandoc` strips the indentation the docstring picks up
from the function body, so what the model receives is the text exactly as written here.
"""

import inspect


def memory_segmentation_prompt() -> str:
    """
    You are given a video transcript with timestamps.

    Your task is to divide the transcript into meaningful semantic moments.

    A **memory** is a meaningful part of a conversation that focuses on one specific idea, point, story, argument, or discussion.

    It should be long enough to include the relevant context, so it can still make sense when read on its own.
    
    The goal is to create moments that will later be useful for semantic search, embeddings, and answering user questions about specific parts of the video.

    Rules:

    * Do not split based only on sentence boundaries.
    * Do not split based only on fixed time intervals.
    * Create a new moment when the main idea changes.
    * Keep each moment semantically coherent.
    * Preserve the original transcript text exactly.
    * Avoid moments that are too small unless they contain a clearly distinct idea.
    * Return `start_segment_id` and `end_segment_id` instead of timestamps.
    * Use only the provided segment IDs and never invent, modify, or skip segment IDs.

    For each moment, return:

    * `start_segment_id`: the first transcript segment belonging to the memory
    * `end_segment_id`: the last transcript segment belonging to the memory
    * `summary`: a short description of what happens or is discussed

    """
    return inspect.cleandoc(memory_segmentation_prompt.__doc__)
