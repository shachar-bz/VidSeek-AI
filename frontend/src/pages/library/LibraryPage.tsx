import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type MouseEvent
} from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  getLibrary,
  getLibraryTags,
  removeLibraryVideo,
  subscribeToLibraryEvents,
  updateLibraryVideo
} from "../../api/library";
import type {
  LibraryProgressEvent,
  LibraryQuery,
  LibraryVideo,
  ReadinessStage,
  UpdateLibraryLinkRequest
} from "../../api/types";
import {
  Button,
  Dialog,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  Panel,
  StatusBadge,
  type StatusTone
} from "../../components/ui";
import { ROUTES, videoPath } from "../../routes";
import { featureFailureMessage } from "../shared";

const EXTENSION_INSTALL_URL =
  "https://github.com/shachar-bz/VidSeek-AI/tree/main/chrome-extension";
const PAGE_SIZE = 50;

interface FilterDraft {
  search: string;
  tag: string;
  source_site: string;
  stage: "" | ReadinessStage;
  added_after: string;
  added_before: string;
  has_conversations: "" | "true" | "false";
  sort: "added_at" | "duration";
  direction: "asc" | "desc";
}

const EMPTY_FILTERS: FilterDraft = {
  search: "",
  tag: "",
  source_site: "",
  stage: "",
  added_after: "",
  added_before: "",
  has_conversations: "",
  sort: "added_at",
  direction: "desc"
};

function toQuery(filters: FilterDraft): LibraryQuery {
  return {
    search: filters.search.trim() || undefined,
    tags: filters.tag ? [filters.tag] : undefined,
    source_site: filters.source_site.trim() || undefined,
    stage: filters.stage || undefined,
    added_after: filters.added_after
      ? `${filters.added_after}T00:00:00.000Z`
      : undefined,
    added_before: filters.added_before
      ? `${filters.added_before}T23:59:59.999Z`
      : undefined,
    has_conversations:
      filters.has_conversations === "" ? undefined : filters.has_conversations === "true",
    sort: filters.sort,
    direction: filters.direction,
    limit: PAGE_SIZE,
    offset: 0
  };
}

function hasNarrowingFilter(query: LibraryQuery): boolean {
  return Boolean(
    query.search ||
      query.tags?.length ||
      query.source_site ||
      query.stage ||
      query.added_after ||
      query.added_before ||
      query.has_conversations !== undefined
  );
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "Not available yet";
  const rounded = Math.max(0, Math.round(seconds));
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const remainder = rounded % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
    : `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function formatDate(value: string | null): string {
  if (!value) return "Being added";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

function stageLabel(stage: ReadinessStage): string {
  return stage.charAt(0).toUpperCase() + stage.slice(1);
}

function stageTone(stage: ReadinessStage): StatusTone {
  if (stage === "ready") return "positive";
  if (stage === "failed") return "critical";
  if (stage === "partial") return "caution";
  return "active";
}

function applyProgress(video: LibraryVideo, event: LibraryProgressEvent): LibraryVideo {
  if (video.job_id !== event.job_id) return video;
  return {
    ...video,
    video_id: event.video_id,
    stage: event.stage,
    progress: event.progress,
    status_message: event.status_message,
    error_code: event.error_code
  };
}

function isInteractiveTarget(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest("a, button, input, select, textarea"));
}

function VideoRow({
  video,
  onEdit,
  onRemove
}: {
  video: LibraryVideo;
  onEdit(video: LibraryVideo): void;
  onRemove(video: LibraryVideo): void;
}) {
  const navigate = useNavigate();
  const canOpen = video.video_id !== null;
  const progress = Math.round(video.progress * 100);

  function openVideo(event: MouseEvent<HTMLTableRowElement>) {
    if (canOpen && !isInteractiveTarget(event.target)) navigate(videoPath(video.video_id!));
  }

  function openVideoFromKeyboard(event: KeyboardEvent<HTMLTableRowElement>) {
    if (canOpen && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      navigate(videoPath(video.video_id!));
    }
  }

  return (
    <tr
      className={canOpen ? "library-row library-row--clickable" : "library-row"}
      onClick={openVideo}
      onKeyDown={openVideoFromKeyboard}
      tabIndex={canOpen ? 0 : undefined}
      aria-label={canOpen ? `Open ${video.title}` : undefined}
    >
      <td className="library-row__title">
        {canOpen ? <Link to={videoPath(video.video_id!)}>{video.title}</Link> : <strong>{video.title}</strong>}
        <span>{video.source_site || "Unknown source"}</span>
      </td>
      <td>{formatDuration(video.duration_seconds)}</td>
      <td>{formatDate(video.added_at)}</td>
      <td>
        {video.video_id && video.tags.length > 0 ? (
          <div className="tag-list">
            {video.tags.map((tag) => (
              <span className="tag" key={tag}>{tag}</span>
            ))}
          </div>
        ) : (
          <span className="muted-text">None</span>
        )}
      </td>
      <td>
        <div className="library-row__status">
          <StatusBadge tone={stageTone(video.stage)}>{stageLabel(video.stage)}</StatusBadge>
          {video.stage === "downloading" ||
          video.stage === "transcribing" ||
          video.stage === "understanding" ? (
            <>
              <progress value={video.progress} max={1} aria-label={`${stageLabel(video.stage)} ${progress}%`} />
              <span>{video.status_message || `${progress}% complete`}</span>
            </>
          ) : null}
          {video.stage === "failed" ? (
            <span className="library-row__failure">
              {video.status_message || "Processing failed"}
              {video.error_code ? ` (${video.error_code})` : ""}
            </span>
          ) : null}
        </div>
      </td>
      <td>{video.video_id ? (video.conversation_count > 0 ? `${video.conversation_count} conversation${video.conversation_count === 1 ? "" : "s"}` : "No conversations") : "Not available yet"}</td>
      <td>
        <div className="library-row__actions">
          {video.video_id ? (
            <Button variant="ghost" onClick={() => onEdit(video)} aria-label={`Edit ${video.title}`}>
              Edit
            </Button>
          ) : null}
          {video.video_id ? (
            <Button className="danger-button" variant="ghost" onClick={() => onRemove(video)} aria-label={`Remove ${video.title}`}>
              Remove
            </Button>
          ) : null}
        </div>
      </td>
    </tr>
  );
}

function MetadataDialog({
  video,
  suggestions,
  onClose,
  onSaved
}: {
  video: LibraryVideo | null;
  suggestions: string[];
  onClose(): void;
  onSaved(video: LibraryVideo): void;
}) {
  const [title, setTitle] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [tagDraft, setTagDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setTitle(video?.custom_title ?? "");
    setTags(video?.tags ?? []);
    setTagDraft("");
    setError(null);
  }, [video]);

  function addTag() {
    const next = tagDraft.trim();
    if (!next || tags.includes(next)) return;
    setTags((current) => [...current, next]);
    setTagDraft("");
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!video?.video_id) return;
    setSaving(true);
    setError(null);
    const update: UpdateLibraryLinkRequest = {
      // Sending null is intentional: it clears a private rename. Omitting this field would
      // mean "leave it unchanged" and would make a blank title unable to restore the source.
      custom_title: title.trim() || null,
      tags
    };
    try {
      onSaved(await updateLibraryVideo(video.video_id, update));
    } catch (caught) {
      setError(featureFailureMessage(caught, "We couldn’t save this library item."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={video !== null}
      title="Edit library details"
      onClose={onClose}
      actions={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" pending={saving} type="submit" form="library-metadata-form">
            {saving ? "Saving…" : "Save changes"}
          </Button>
        </>
      }
    >
      <form className="stack-form" id="library-metadata-form" onSubmit={save}>
        <Field
          label="Private title"
          value={title}
          maxLength={512}
          onChange={(event) => setTitle(event.target.value)}
          hint="Leave blank to use the title captured from the source. Only you see this rename."
        />
        <div className="ui-field">
          <label className="ui-field__label" htmlFor="library-tag-input">Tags</label>
          <div className="tag-entry">
            <input
              className="ui-field__input"
              id="library-tag-input"
              list="library-tag-suggestions"
              maxLength={64}
              value={tagDraft}
              onChange={(event) => setTagDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  addTag();
                }
              }}
            />
            <Button onClick={addTag}>Add tag</Button>
          </div>
          <datalist id="library-tag-suggestions">
            {suggestions.map((tag) => <option value={tag} key={tag} />)}
          </datalist>
          <div className="tag-list" aria-label="Selected tags">
            {tags.map((tag) => (
              <button className="tag tag--removable" type="button" key={tag} onClick={() => setTags((current) => current.filter((item) => item !== tag))}>
                {tag} <span aria-hidden="true">×</span><span className="visually-hidden">Remove</span>
              </button>
            ))}
          </div>
          <p className="ui-field__hint">Choose an existing suggestion or create free-text tags. Tags are private to your library.</p>
        </div>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
      </form>
    </Dialog>
  );
}

export function LibraryPage() {
  const [filters, setFilters] = useState<FilterDraft>(EMPTY_FILTERS);
  const [query, setQuery] = useState<LibraryQuery>(toQuery(EMPTY_FILTERS));
  const [videos, setVideos] = useState<LibraryVideo[]>([]);
  const [total, setTotal] = useState(0);
  const [tags, setTags] = useState<string[]>([]);
  const [knownSources, setKnownSources] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [reloadVersion, setReloadVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [editing, setEditing] = useState<LibraryVideo | null>(null);
  const [removing, setRemoving] = useState<LibraryVideo | null>(null);
  const [removalPending, setRemovalPending] = useState(false);
  const [removalError, setRemovalError] = useState<string | null>(null);
  const videosRef = useRef<LibraryVideo[]>([]);
  const libraryLoadedRef = useRef(false);
  const pendingEventsRef = useRef<LibraryProgressEvent[]>([]);
  const queryKey = JSON.stringify(query);

  useEffect(() => {
    const controller = new AbortController();
    libraryLoadedRef.current = false;
    pendingEventsRef.current = [];
    setLoading(true);
    setError(null);
    getLibrary(query, controller.signal)
      .then((page) => {
        const currentVideos = pendingEventsRef.current.reduce(
          (items, event) => items.map((video) => applyProgress(video, event)),
          page.videos
        );
        pendingEventsRef.current = [];
        libraryLoadedRef.current = true;
        videosRef.current = currentVideos;
        setVideos(currentVideos);
        setTotal(page.total);
        setKnownSources((current) =>
          Array.from(new Set([...current, ...page.videos.map((video) => video.source_site).filter(Boolean)])).sort()
        );
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setError(featureFailureMessage(caught, "We couldn’t load your library."));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
    // queryKey is a stable value dependency for the query object's complete wire shape.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey, reloadVersion]);

  useEffect(() => {
    const controller = new AbortController();
    getLibraryTags(controller.signal)
      .then((response) => setTags(response.tags))
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setLiveError(featureFailureMessage(caught, "Tag suggestions are unavailable."));
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLiveError(null);
    void (async () => {
      try {
        for await (const event of subscribeToLibraryEvents(controller.signal)) {
          if (controller.signal.aborted) return;
          if (!libraryLoadedRef.current) {
            pendingEventsRef.current.push(event);
            continue;
          }
          const found = videosRef.current.some((video) => video.job_id === event.job_id);
          if (found) {
            setVideos((current) => {
              const updated = current.map((video) => applyProgress(video, event));
              videosRef.current = updated;
              return updated;
            });
          }
          // A job can begin in the extension after this page loads. An event does not carry
          // enough metadata to invent its row, so fetch that row from the canonical listing.
          if (!found) {
            const page = await getLibrary(query, controller.signal);
            if (!controller.signal.aborted) {
              videosRef.current = page.videos;
              setVideos(page.videos);
              setTotal(page.total);
            }
          }
        }
      } catch (caught) {
        if (!controller.signal.aborted) {
          setLiveError(featureFailureMessage(caught, "Live progress is unavailable. Refresh to update processing videos."));
        }
      }
    })();
    return () => controller.abort();
    // queryKey makes an unknown-job refresh respect all current server-side filters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey]);

  const pageStart = query.offset ?? 0;
  const pageEnd = Math.min(pageStart + videos.length, total);
  const filtered = hasNarrowingFilter(query);
  const resultSummary = useMemo(
    () => total === 0 ? "No videos" : `Showing ${pageStart + 1}–${pageEnd} of ${total}`,
    [pageEnd, pageStart, total]
  );

  function applyFilters(event: FormEvent) {
    event.preventDefault();
    setQuery(toQuery(filters));
  }

  function resetFilters() {
    setFilters(EMPTY_FILTERS);
    setQuery(toQuery(EMPTY_FILTERS));
  }

  async function confirmRemoval() {
    if (!removing?.video_id) return;
    setRemovalPending(true);
    setRemovalError(null);
    try {
      await removeLibraryVideo(removing.video_id);
      setVideos((current) => {
        const updated = current.filter((video) => video.video_id !== removing.video_id);
        videosRef.current = updated;
        return updated;
      });
      setTotal((current) => Math.max(0, current - 1));
      setRemoving(null);
    } catch (caught) {
      setRemovalError(featureFailureMessage(caught, "We couldn’t remove this video."));
    } finally {
      setRemovalPending(false);
    }
  }

  return (
    <div className="feature-page library-page">
      <header className="feature-page__heading">
        <div>
          <p className="eyebrow">Your collection</p>
          <h1>Library</h1>
          <p>Videos sent from the Chrome extension, ready to revisit and explore.</p>
        </div>
        <Link className="button-link button-link--ghost" to={ROUTES.setup}>Set up the extension</Link>
      </header>

      <Panel className="library-filters" aria-label="Library filters">
        <form onSubmit={applyFilters}>
          <Field label="Search titles" type="search" value={filters.search} placeholder="Search by title" onChange={(event) => setFilters({ ...filters, search: event.target.value })} />
          <label className="compact-field">Tag<select value={filters.tag} onChange={(event) => setFilters({ ...filters, tag: event.target.value })}><option value="">All tags</option>{tags.map((tag) => <option key={tag}>{tag}</option>)}</select></label>
          <label className="compact-field">Source<input list="library-source-suggestions" value={filters.source_site} placeholder="All sources" onChange={(event) => setFilters({ ...filters, source_site: event.target.value })} /></label>
          <datalist id="library-source-suggestions">{knownSources.map((source) => <option value={source} key={source} />)}</datalist>
          <label className="compact-field">Readiness<select value={filters.stage} onChange={(event) => setFilters({ ...filters, stage: event.target.value as FilterDraft["stage"] })}><option value="">All stages</option>{(["downloading", "transcribing", "understanding", "ready", "partial", "failed"] as ReadinessStage[]).map((stage) => <option value={stage} key={stage}>{stageLabel(stage)}</option>)}</select></label>
          <label className="compact-field">Added after<input type="date" value={filters.added_after} onChange={(event) => setFilters({ ...filters, added_after: event.target.value })} /></label>
          <label className="compact-field">Added before<input type="date" value={filters.added_before} onChange={(event) => setFilters({ ...filters, added_before: event.target.value })} /></label>
          <label className="compact-field">Conversations<select value={filters.has_conversations} onChange={(event) => setFilters({ ...filters, has_conversations: event.target.value as FilterDraft["has_conversations"] })}><option value="">Any</option><option value="true">Has conversations</option><option value="false">No conversations</option></select></label>
          <label className="compact-field">Sort by<select value={filters.sort} onChange={(event) => setFilters({ ...filters, sort: event.target.value as FilterDraft["sort"] })}><option value="added_at">Date added</option><option value="duration">Duration</option></select></label>
          <label className="compact-field">Direction<select value={filters.direction} onChange={(event) => setFilters({ ...filters, direction: event.target.value as FilterDraft["direction"] })}><option value="desc">Descending</option><option value="asc">Ascending</option></select></label>
          <div className="library-filters__actions"><Button type="submit">Apply filters</Button><Button variant="ghost" onClick={resetFilters}>Reset</Button></div>
        </form>
      </Panel>

      {liveError ? <div className="inline-notice" role="status">{liveError}</div> : null}
      {loading ? <LoadingState label="Loading your library…" /> : error ? <ErrorState title="Unable to load library" message={error} actionLabel="Try again" onAction={() => setReloadVersion((current) => current + 1)} /> : videos.length === 0 && !filtered ? (
        <EmptyState
          title="Your library is ready for its first video"
          description={<p>Videos arrive through the Chrome extension: open a video in Chrome, send it with VidSeek, and follow its progress here. The website cannot ingest URLs or files.</p>}
          action={<div className="empty-state-actions"><a className="button-link button-link--primary" href={EXTENSION_INSTALL_URL} target="_blank" rel="noreferrer">Install the Chrome extension</a><Link to={ROUTES.setup}>Read the setup guide</Link></div>}
        />
      ) : videos.length === 0 ? (
        <EmptyState title="No videos match these filters" description="Try a broader title, source, date, or readiness filter." action={<Button onClick={resetFilters}>Clear filters</Button>} />
      ) : (
        <>
          <div className="library-results-heading"><p aria-live="polite">{resultSummary}</p></div>
          <div className="library-table-wrap">
            <table className="library-table">
              <thead><tr><th>Video</th><th>Duration</th><th>Added</th><th>Tags</th><th>Status</th><th>Conversations</th><th><span className="visually-hidden">Actions</span></th></tr></thead>
              <tbody>{videos.map((video) => <VideoRow key={video.job_id ?? video.video_id!} video={video} onEdit={setEditing} onRemove={(item) => { setRemovalError(null); setRemoving(item); }} />)}</tbody>
            </table>
          </div>
          {total > PAGE_SIZE ? <nav className="pagination" aria-label="Library pages"><Button variant="ghost" disabled={pageStart === 0} onClick={() => setQuery({ ...query, offset: Math.max(0, pageStart - PAGE_SIZE) })}>Previous</Button><Button variant="ghost" disabled={pageEnd >= total} onClick={() => setQuery({ ...query, offset: pageStart + PAGE_SIZE })}>Next</Button></nav> : null}
        </>
      )}

      <MetadataDialog video={editing} suggestions={tags} onClose={() => setEditing(null)} onSaved={(saved) => { setVideos((current) => { const updated = current.map((video) => video.video_id === saved.video_id ? saved : video); videosRef.current = updated; return updated; }); setTags((current) => Array.from(new Set([...current, ...saved.tags])).sort()); setEditing(null); }} />
      <Dialog open={removing !== null} title="Remove this video?" onClose={() => setRemoving(null)} actions={<><Button variant="ghost" onClick={() => setRemoving(null)}>Cancel</Button><Button className="danger-button" pending={removalPending} onClick={confirmRemoval}>{removalPending ? "Removing…" : "Remove video"}</Button></>}>
        <p>Removing this link permanently deletes your conversation history and pins for this video. Re-adding the video later restores its shared video content and artifacts, but your conversation history is permanently lost.</p>
        {removalError ? <p className="form-error" role="alert">{removalError}</p> : null}
      </Dialog>
    </div>
  );
}
