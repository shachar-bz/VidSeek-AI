"""The only shape the segmentation model is allowed to answer in.

These models are handed to OpenAI Structured Outputs as the response schema, so the SDK
returns them already parsed and typed. Nothing in this package reads free-form JSON out of
a model response, and nothing hand-parses one.

Note how little is here. A boundary is two segment IDs and a sentence: the model chooses
where a memory starts and ends and says what it is about, and every timestamp and every
word of transcript in the finished memory is read out of the original transcript instead —
see `memory.py`.
"""

from pydantic import BaseModel, ConfigDict, Field


class MemoryBoundary(BaseModel):
    """One memory, as the model describes it: where it starts, where it ends, what it is."""

    model_config = ConfigDict(extra="forbid")

    start_segment_id: str = Field(
        description="The ID of the first transcript segment belonging to the memory."
    )
    end_segment_id: str = Field(
        description="The ID of the last transcript segment belonging to the memory."
    )
    summary: str = Field(description="A concise description of what happens or is discussed.")


class TranscriptMemoryBoundaries(BaseModel):
    """Every memory the model divided one transcript into, in chronological order.

    Structured Outputs requires the root of a schema to be an object, which is why the
    list is wrapped rather than returned on its own.
    """

    model_config = ConfigDict(extra="forbid")

    memories: list[MemoryBoundary] = Field(
        description="The memories the transcript divides into, in chronological order."
    )
