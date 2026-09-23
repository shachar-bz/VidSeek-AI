"""Aggregate PostgreSQL reads used by the hosted library and video HTTP APIs."""

from __future__ import annotations

from dataclasses import dataclass

from .connection import connection, iso_text


@dataclass(frozen=True)
class LibraryViewRow:
    """One library link or pre-link job with all readiness facts in the same row."""

    video_id: str | None
    job_id: str | None
    original_title: str
    custom_title: str | None
    source: str | None
    source_url: str
    duration_seconds: float | None
    tags: list[str]
    added_at: str | None
    job_status: str | None
    job_phase: str | None
    progress: float
    status_message: str
    error_code: str | None
    conversation_count: int
    has_video_row: bool
    has_transcript: bool
    has_timed_transcript: bool
    has_chapters: bool
    has_embeddings: bool
    has_insights: bool
    transcript_source: str | None = None
    transcript_language: str | None = None
    transcript_timing_fidelity: str | None = None
    blob_container: str | None = None
    blob_name: str | None = None
    insights_summary: str | None = None
    insights_takeaways: list[str] | None = None
    insights_suggested_questions: list[str] | None = None
    # How far the video's visual index is (`videos.visual_status`); None for a job with
    # no video row yet.
    visual_status: str | None = None

    @classmethod
    def from_row(cls, row: dict) -> "LibraryViewRow":
        return cls(
            video_id=str(row["video_id"]) if row.get("video_id") else None,
            job_id=str(row["job_id"]) if row.get("job_id") else None,
            original_title=row.get("original_title") or row.get("page_title") or "video",
            custom_title=row.get("custom_title"),
            source=row.get("source"),
            source_url=row.get("source_url") or row.get("page_url") or "",
            duration_seconds=(
                float(row["duration_seconds"])
                if row.get("duration_seconds") is not None
                else None
            ),
            tags=list(row.get("tags") or []),
            added_at=iso_text(row["added_at"]) if row.get("added_at") else None,
            job_status=row.get("job_status"),
            job_phase=row.get("job_phase"),
            progress=float(row.get("progress") or 0),
            status_message=row.get("status_message") or "",
            error_code=row.get("error_code"),
            conversation_count=int(row.get("conversation_count") or 0),
            has_video_row=bool(row.get("has_video_row")),
            has_transcript=bool(row.get("has_transcript")),
            has_timed_transcript=bool(row.get("has_timed_transcript")),
            has_chapters=bool(row.get("has_chapters")),
            has_embeddings=bool(row.get("has_embeddings")),
            has_insights=bool(row.get("has_insights")),
            transcript_source=row.get("transcript_source"),
            transcript_language=row.get("transcript_language"),
            transcript_timing_fidelity=row.get("transcript_timing_fidelity"),
            blob_container=row.get("blob_container"),
            blob_name=row.get("blob_name"),
            insights_summary=row.get("insights_summary"),
            insights_takeaways=list(row.get("insights_takeaways") or []),
            insights_suggested_questions=list(
                row.get("insights_suggested_questions") or []
            ),
            visual_status=row.get("visual_status"),
        )


ARTIFACT_COLUMNS = """
    (i.video_id is not null) as has_video_row,
    exists(select 1 from public.transcript_segments ts where ts.video_id = i.video_id) as has_transcript,
    (i.transcript_timing_fidelity is not null) as has_timed_transcript,
    exists(select 1 from public.chapters ch where ch.video_id = i.video_id) as has_chapters,
    exists(select 1 from public.memory_embeddings me where me.video_id = i.video_id)
      and exists(select 1 from public.chapter_embeddings ce where ce.video_id = i.video_id)
      as has_embeddings,
    (i.insights_summary is not null) as has_insights
"""


BASE_ITEMS = """
with linked as (
    select v.id as video_id, j.id as job_id, v.title as original_title,
           uv.custom_title, v.source, v.source_url, v.duration_seconds, uv.tags,
           uv.added_at, j.status as job_status, j.phase as job_phase,
           coalesce(j.progress, 0) as progress, coalesce(j.message, '') as status_message,
           j.error_code, v.transcript_source, v.transcript_language,
           v.transcript_timing_fidelity, v.blob_container, v.blob_name,
           vi.summary as insights_summary, vi.takeaways as insights_takeaways,
           vi.suggested_questions as insights_suggested_questions,
           v.visual_status,
           (select count(*) from public.conversations c
             where c.user_id = uv.user_id and c.video_id = uv.video_id) as conversation_count
    from public.user_videos uv
    join public.videos v on v.id = uv.video_id
    left join lateral (
        select * from public.video_jobs candidate
        where candidate.user_id = uv.user_id and candidate.video_id = uv.video_id
        order by candidate.updated_at desc limit 1
    ) j on true
    left join public.video_insights vi on vi.video_id = v.id
    where uv.user_id = %s::uuid
), pending as (
    select j.video_id, j.id as job_id, j.page_title as original_title,
           null::text as custom_title, j.acquisition_mode as source,
           j.page_url as source_url, null::double precision as duration_seconds,
           '{{}}'::text[] as tags, null::timestamptz as added_at,
           j.status as job_status, j.phase as job_phase, j.progress,
           j.message as status_message, j.error_code,
           null::text as transcript_source, null::text as transcript_language,
           null::text as transcript_timing_fidelity, null::text as blob_container,
           null::text as blob_name, null::text as insights_summary,
           null::text[] as insights_takeaways,
           null::text[] as insights_suggested_questions, null::text as visual_status,
           0::bigint as conversation_count
    from public.video_jobs j
    where j.user_id = %s::uuid and (
        j.video_id is null or not exists (
            select 1 from public.user_videos uv
            where uv.user_id = j.user_id and uv.video_id = j.video_id
        )
    )
), items as (select * from linked union all select * from pending),
facts as (select i.*, {artifacts} from items i)
""".format(artifacts=ARTIFACT_COLUMNS)


class PostgresLibraryViews:
    """Read models spanning jobs, links, videos, artifacts, insights and conversations."""

    def __init__(self, pool=None):
        self._pool = pool

    def list_page(
        self,
        user_id: str,
        *,
        search: str | None,
        tags: list[str],
        source_site: str | None,
        stage: str | None,
        added_after: str | None,
        added_before: str | None,
        has_conversations: bool | None,
        sort: str,
        direction: str,
        limit: int,
        offset: int,
    ) -> tuple[list[LibraryViewRow], int]:
        """Return one filtered page; all six artifact flags are aggregated in this query."""
        clauses: list[str] = []
        parameters: list[object] = [user_id, user_id]
        if search:
            clauses.append("coalesce(custom_title, original_title) ilike %s")
            parameters.append(f"%{search}%")
        if tags:
            clauses.append("tags @> %s::text[]")
            parameters.append(tags)
        if source_site:
            clauses.append(
                "lower(split_part(split_part(source_url, '://', 2), '/', 1)) = lower(%s)"
            )
            parameters.append(source_site)
        if added_after:
            clauses.append("added_at >= %s::timestamptz")
            parameters.append(added_after)
        if added_before:
            clauses.append("added_at <= %s::timestamptz")
            parameters.append(added_before)
        if has_conversations is not None:
            clauses.append("conversation_count > 0" if has_conversations else "conversation_count = 0")
        if stage:
            clauses.append("(" + _stage_sql() + ") = %s")
            parameters.append(stage)
        where = " where " + " and ".join(clauses) if clauses else ""
        order_column = "duration_seconds" if sort == "duration" else "added_at"
        order_direction = "asc" if direction == "asc" else "desc"
        parameters.extend([limit, offset])
        statement = (
            BASE_ITEMS
            + ", filtered as (select * from facts"
            + where
            + ") select page.*, totals.total from "
            + "(select count(*) as total from filtered) totals "
            + "left join lateral (select * from filtered "
            + f"order by {order_column} {order_direction} nulls last limit %s offset %s"
            + ") page on true"
        )
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(statement, parameters).fetchall()
        total = int(rows[0].get("total", 0)) if rows else 0
        page_rows = [row for row in rows if row.get("video_id") or row.get("job_id")]
        return [LibraryViewRow.from_row(row) for row in page_rows], total

    def get_video(self, user_id: str, video_id: str) -> LibraryViewRow | None:
        """Get one linked video and every fact needed by its detail and playback routes."""
        statement = BASE_ITEMS + " select * from facts where video_id = %s::uuid limit 1"
        with connection(self._pool) as open_connection:
            row = open_connection.execute(statement, (user_id, user_id, video_id)).fetchone()
        return LibraryViewRow.from_row(row) if row else None

    def progress_rows(self, user_id: str) -> list[LibraryViewRow]:
        """Read all of this user's job-backed rows for a progress stream poll."""
        statement = BASE_ITEMS + " select * from facts where job_id is not null order by job_id"
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(statement, (user_id, user_id)).fetchall()
        return [LibraryViewRow.from_row(row) for row in rows]


def _stage_sql() -> str:
    """SQL equivalent used only to apply the stage filter before pagination."""
    return """
    case
      when job_status in ('queued','running','awaiting_browser_download') and
           (job_phase is null or job_phase = 'download') then 'downloading'
      when job_status in ('queued','running','awaiting_browser_download') and
           job_phase in ('transcript_lookup','transcription','upload') then 'transcribing'
      when job_status in ('queued','running','awaiting_browser_download') then 'understanding'
      when error_code in ('transcription_failed','record_failed') then 'failed'
      when job_status in ('failed','cancelled') and not has_transcript then 'failed'
      when not has_video_row or not has_transcript then 'failed'
      when not (has_chapters and has_embeddings and has_insights) then 'understanding'
      when error_code = 'untimed_transcript' or not has_timed_transcript then 'partial'
      else 'ready'
    end
    """
