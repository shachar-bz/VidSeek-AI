"""The library page's contract: what a user's videos look like, and how they are asked for.

One row of a library is not one table. The title a user sees comes from their `user_videos`
link when they renamed it and from `videos` otherwise; the stage comes from a `video_jobs`
row while one is running and from what the video has produced once it is not; and a video
that is still downloading has no `videos` row at all, only a job. `LibraryVideo` is that
join flattened into the shape the page renders, which is why several of its fields are
optional in ways the underlying columns are not.

`LibraryQuery` is the other half: every filter, sort and page control §3.3 asks for, in one
model so that the website builds a query string against the same names the API reads. This
is metadata search only -- searching the *content* of videos is out of scope.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from .readiness import ReadinessStage

# One page of a library. Generous, because a personal library is small and the page shows
# rows rather than cards; the cap exists to stop a client asking for everything at once.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

MAX_CUSTOM_TITLE_LENGTH = 512
MAX_TAG_LENGTH = 64
MAX_TAGS_PER_VIDEO = 50


class LibrarySort(str, Enum):
    """What a library can be ordered by, from §3.3."""

    ADDED_AT = "added_at"
    DURATION = "duration"


class SortDirection(str, Enum):
    ASCENDING = "asc"
    DESCENDING = "desc"


class LibraryVideo(BaseModel):
    """One row of the library page.

    `video_id` is null for a video whose job has not produced a `videos` row yet, which is
    the whole of the `downloading` and `transcribing` stages. Such a row is not clickable
    through to a video page, and everything derived from the video -- duration, tags,
    conversations -- is empty on it. `job_id` is null for the opposite case: a video whose
    job has finished and been pruned, or one recorded before jobs were persisted at all.
    At least one of the two is always set.
    """

    video_id: str | None = None
    job_id: str | None = None

    # What the page prints: the user's custom title when they set one, the captured title
    # otherwise. Resolved by the API rather than by the client, so that sorting and
    # searching on the server agree with what the user reads.
    title: str
    custom_title: str | None = None

    # The site the video came from -- a hostname, not a full URL -- and the page it came
    # from, which is what an "open original" link points at.
    source_site: str
    source: str = ""
    source_url: str

    duration_seconds: float | None = None
    thumbnail_url: str | None = None
    tags: list[str] = Field(default_factory=list)

    # When this user added it. Null only while the library link does not exist yet, which
    # is the same window in which `video_id` is null.
    added_at: str | None = None

    stage: ReadinessStage
    # Live progress for a row that is still working, and the sentence the job is reporting.
    # Both stay populated on a finished row, where they describe how it finished: §1.3 wants
    # a failed video to show its reason.
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    status_message: str = ""
    error_code: str | None = None

    # §3 asks each row to show "whether it has conversations", and §3.3 to filter on it.
    # A count rather than a flag: it costs the same aggregate and says more.
    conversation_count: int = 0


class LibraryPage(BaseModel):
    """One page of a library, and enough to ask for the next.

    `total` counts every row matching the filters, not the rows returned, which is what a
    "showing 20 of 134" line and a page count both need.
    """

    videos: list[LibraryVideo]
    total: int
    limit: int
    offset: int


class LibraryQuery(BaseModel):
    """Every filter, sort and page control `GET /v1/library` accepts.

    Read from the query string; a route takes it as `Depends(LibraryQuery)`. Every field is
    optional, and a request with none of them is the whole library, newest addition first.

    `tags` filters on *all* of the tags given rather than any of them, which is what makes
    a tag list narrow a search the way a user expects when they click a second tag.
    """

    search: str | None = Field(default=None, max_length=256)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS_PER_VIDEO)
    source_site: str | None = Field(default=None, max_length=256)
    stage: ReadinessStage | None = None

    # ISO 8601 instants, inclusive at both ends, filtering on when this user added the
    # video rather than on when the video was first recorded by anyone.
    added_after: str | None = None
    added_before: str | None = None

    has_conversations: bool | None = None

    sort: LibrarySort = LibrarySort.ADDED_AT
    direction: SortDirection = SortDirection.DESCENDING

    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0)


class UpdateLibraryLinkRequest(BaseModel):
    """A rename, a re-tag, or both, on one library link.

    Both fields are optional and mean "leave this alone" when absent, which is what makes
    one endpoint serve the two edits §3.4 describes without a client having to send a tag
    list it did not change. `custom_title` set to null explicitly is the documented way to
    clear a rename back to the video's own title -- so a route has to tell an absent field
    from a null one, which `model_fields_set` answers.
    """

    custom_title: str | None = Field(default=None, max_length=MAX_CUSTOM_TITLE_LENGTH)
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS_PER_VIDEO)


class TagList(BaseModel):
    """Every tag this account has used, alphabetically -- the suggestions §3.4 asks for."""

    tags: list[str]


class LibraryProgressEvent(BaseModel):
    """One update on the live channel the library's processing rows read.

    Deliberately the same fields a `LibraryVideo` carries for a job in flight, so that
    applying an event to a row is a field-by-field overwrite rather than a re-fetch. A row
    that reaches a terminal stage is not removed and not re-ordered; §3.2 wants it to flip
    to `ready` in place.

    `video_id` appears mid-stream: a row that started with only a `job_id` gains one the
    moment stage two writes the `videos` row, and that is the event that makes the row
    clickable.
    """

    job_id: str
    video_id: str | None = None
    stage: ReadinessStage
    progress: float = Field(ge=0.0, le=1.0)
    status_message: str = ""
    error_code: str | None = None
