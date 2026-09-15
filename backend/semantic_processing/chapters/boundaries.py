"""The only shape the chapter grouping model is allowed to answer in.

These models are handed to OpenAI Structured Outputs as the response schema, so the SDK
returns them already parsed and typed. Nothing in this package reads free-form JSON out of
a model response, and nothing hand-parses one.

A boundary is two memory IDs, a title and a summary: the model chooses where a chapter
starts and ends and says what it is about, and every timestamp in the finished chapter is
read out of the original memories instead — see `chapter.py`.
"""

from pydantic import BaseModel, ConfigDict, Field


class ChapterBoundary(BaseModel):
    """One chapter, as the model describes it: where it starts, where it ends, what it is."""

    model_config = ConfigDict(extra="forbid")

    start_memory_id: str = Field(
        description="The ID of the first memory belonging to the chapter."
    )
    end_memory_id: str = Field(description="The ID of the last memory belonging to the chapter.")
    title: str = Field(
        description=(
            "A short, clear, human-readable name for the chapter, briefly identifying its "
            "main topic and useful for navigation."
        )
    )
    summary: str = Field(
        description=(
            "A concise description of the broader topic or discussion the chapter covers, "
            "rather than a concatenation of the individual memory summaries."
        )
    )


class VideoChapterBoundaries(BaseModel):
    """Every chapter the model grouped one video's memories into, in chronological order.

    Structured Outputs requires the root of a schema to be an object, which is why the
    list is wrapped rather than returned on its own.
    """

    model_config = ConfigDict(extra="forbid")

    chapters: list[ChapterBoundary] = Field(
        description="The chapters the memories group into, in chronological order."
    )
