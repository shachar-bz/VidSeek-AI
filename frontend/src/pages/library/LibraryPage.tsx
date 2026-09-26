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
  getLibraryThumbnail,
  removeFailedLibraryJob,
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
import { Button, Dialog, EmptyState, ErrorState, Field, LoadingState } from "../../components/ui";
import { ROUTES, videoPath } from "../../routes";
import { featureFailureMessage, sourceLabel } from "../shared";

const EXTENSION_INSTALL_URL =
  "https://github.com/shachar-bz/VidSeek-AI/tree/main/chrome-extension";
const PAGE_SIZE = 5;

interface FilterDraft {
  search: string;
  tag: string;
  source_site: string;
  stage: "" | ReadinessStage;
  added_after: string;
  added_before: string;
  sort: "added_at" | "duration";
  direction: "asc" | "desc";
}

type EditMode = "rename" | "tags";
type ViewMode = "list" | "grid";

const EMPTY_FILTERS: FilterDraft = {
  search: "",
  tag: "",
  source_site: "",
  stage: "",
  added_after: "",
  added_before: "",
  sort: "added_at",
  direction: "desc"
};

function toQuery(filters: FilterDraft, offset = 0): LibraryQuery {
  return {
    search: filters.search.trim() || undefined,
    tags: filters.tag ? [filters.tag] : undefined,
    source_site: filters.source_site || undefined,
    stage: filters.stage || undefined,
    added_after: filters.added_after ? `${filters.added_after}T00:00:00.000Z` : undefined,
    added_before: filters.added_before ? `${filters.added_before}T23:59:59.999Z` : undefined,
    sort: filters.sort,
    direction: filters.direction,
    limit: PAGE_SIZE,
    offset
  };
}

function hasNarrowingFilter(query: LibraryQuery): boolean {
  return Boolean(
    query.search ||
      query.tags?.length ||
      query.source_site ||
      query.stage ||
      query.added_after ||
      query.added_before
  );
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  const rounded = Math.max(0, Math.round(seconds));
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const remainder = rounded % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function formatDate(value: string | null): string {
  if (!value) return "Processing";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) return "Today";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}

function stageLabel(stage: ReadinessStage): string {
  if (stage === "understanding") return "Indexing";
  return stage.charAt(0).toUpperCase() + stage.slice(1);
}

function applyProgress(video: LibraryVideo, event: LibraryProgressEvent): LibraryVideo {
  if (video.job_id !== event.job_id) return video;
  return {
    ...video,
    video_id: event.video_id,
    thumbnail_url: event.video_id ? `/v1/videos/${event.video_id}/thumbnail` : null,
    stage: event.stage,
    progress: event.progress,
    status_message: event.status_message,
    error_code: event.error_code
  };
}

function isInteractiveTarget(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest("a, button, input, select, textarea, summary, details"));
}

function Thumbnail({ video }: { video: LibraryVideo }) {
  const [source, setSource] = useState<string | null>(null);

  useEffect(() => {
    if (!video.thumbnail_url) {
      setSource(null);
      return;
    }
    const controller = new AbortController();
    let objectUrl: string | null = null;
    getLibraryThumbnail(video.thumbnail_url, controller.signal)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setSource(objectUrl);
      })
      .catch(() => {
        if (!controller.signal.aborted) setSource(null);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [video.thumbnail_url]);

  return (
    <figure className="library-thumbnail">
      {source ? <img src={source} alt="" /> : <span className="library-thumbnail__placeholder" aria-hidden="true"><PlayIcon /></span>}
      <figcaption>{formatDuration(video.duration_seconds)}</figcaption>
    </figure>
  );
}

function Status({ video }: { video: LibraryVideo }) {
  const processing = video.stage === "downloading" || video.stage === "transcribing" || video.stage === "understanding";
  const progress = Math.round(video.progress * 100);
  if (!processing) {
    return <span className={`library-status library-status--${video.stage}`}>{stageLabel(video.stage)}</span>;
  }
  return (
    <div className="library-progress">
      <div><span>{stageLabel(video.stage)}</span><span>· {progress}%</span><i aria-hidden="true" /></div>
      <progress value={video.progress} max={1} aria-label={`${stageLabel(video.stage)} ${progress}%`} />
    </div>
  );
}

/** A failed upload that never produced a video: only its job row can be removed. */
function isFailedJob(video: LibraryVideo): boolean {
  return video.video_id === null && video.job_id !== null && video.stage === "failed";
}

function RowActions({ video, onEdit, onRemove }: {
  video: LibraryVideo;
  onEdit(video: LibraryVideo, mode: EditMode): void;
  onRemove(video: LibraryVideo): void;
}) {
  if (!video.video_id) {
    if (!isFailedJob(video)) return <span className="library-actions__pending">•••</span>;
    return (
      <details className="library-actions">
        <summary aria-label={`Actions for ${video.title}`}>•••</summary>
        <div className="library-actions__menu">
          <button type="button" aria-label={`Remove ${video.title}`} onClick={() => onRemove(video)}><TrashIcon />Remove from library</button>
        </div>
      </details>
    );
  }
  return (
    <details className="library-actions">
      <summary aria-label={`Actions for ${video.title}`}>•••</summary>
      <div className="library-actions__menu">
        <button type="button" aria-label={`Rename ${video.title}`} onClick={() => onEdit(video, "rename")}><PencilIcon />Rename</button>
        <button type="button" aria-label={`Edit tags for ${video.title}`} onClick={() => onEdit(video, "tags")}><TagIcon />Edit tags</button>
        <button type="button" aria-label={`Remove ${video.title}`} onClick={() => onRemove(video)}><TrashIcon />Remove from library</button>
      </div>
    </details>
  );
}

function VideoRow({ video, onEdit, onRemove }: {
  video: LibraryVideo;
  onEdit(video: LibraryVideo, mode: EditMode): void;
  onRemove(video: LibraryVideo): void;
}) {
  const navigate = useNavigate();
  const canOpen = video.video_id !== null;

  function openVideo(event: MouseEvent<HTMLTableRowElement>) {
    if (canOpen && !isInteractiveTarget(event.target)) navigate(videoPath(video.video_id!));
  }

  function openVideoFromKeyboard(event: KeyboardEvent<HTMLTableRowElement>) {
    if (canOpen && !isInteractiveTarget(event.target) && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      navigate(videoPath(video.video_id!));
    }
  }

  return (
    <tr className={canOpen ? "library-row library-row--clickable" : "library-row"} onClick={openVideo} onKeyDown={openVideoFromKeyboard} tabIndex={canOpen ? 0 : undefined}>
      <td>
        <div className="library-video-cell">
          <Thumbnail video={video} />
          <div>
            {canOpen ? <Link to={videoPath(video.video_id!)}>{video.title}</Link> : <strong>{video.title}</strong>}
            {canOpen ? <button className="library-rename" type="button" aria-label={`Rename ${video.title}`} onClick={() => onEdit(video, "rename")}><PencilIcon /></button> : null}
          </div>
        </div>
      </td>
      <td>{sourceLabel(video)}</td>
      <td>{video.tags.length > 0 ? <div className="tag-list">{video.tags.map((tag) => <span className="tag" key={tag}>{tag}</span>)}</div> : <span className="muted-text">—</span>}</td>
      <td>{formatDate(video.added_at)}</td>
      <td>{formatDuration(video.duration_seconds)}</td>
      <td><Status video={video} /></td>
      <td><RowActions video={video} onEdit={onEdit} onRemove={onRemove} /></td>
    </tr>
  );
}

function VideoGrid({ videos, onEdit, onRemove }: {
  videos: LibraryVideo[];
  onEdit(video: LibraryVideo, mode: EditMode): void;
  onRemove(video: LibraryVideo): void;
}) {
  return (
    <div className="library-grid">
      {videos.map((video) => (
        <article className="library-card" key={video.job_id ?? video.video_id!}>
          <Thumbnail video={video} />
          <div className="library-card__body">
            <div className="library-card__heading">
              {video.video_id ? <Link to={videoPath(video.video_id)}>{video.title}</Link> : <strong>{video.title}</strong>}
              <RowActions video={video} onEdit={onEdit} onRemove={onRemove} />
            </div>
            <p>{sourceLabel(video)} · {formatDate(video.added_at)}</p>
            {video.tags.length > 0 ? <div className="tag-list">{video.tags.map((tag) => <span className="tag" key={tag}>{tag}</span>)}</div> : null}
            <Status video={video} />
          </div>
        </article>
      ))}
    </div>
  );
}

function MetadataDialog({ video, mode, suggestions, onClose, onSaved }: {
  video: LibraryVideo | null;
  mode: EditMode;
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
    setTitle(video?.custom_title ?? video?.title ?? "");
    setTags(video?.tags ?? []);
    setTagDraft("");
    setError(null);
  }, [video, mode]);

  // A tag still sitting in the input counts as added, so Save never drops what was typed.
  function tagsWithDraft(): string[] {
    const next = tagDraft.trim();
    return !next || tags.includes(next) ? tags : [...tags, next];
  }

  function addTag() {
    setTags(tagsWithDraft());
    setTagDraft("");
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!video?.video_id) return;
    setSaving(true);
    setError(null);
    const update: UpdateLibraryLinkRequest = mode === "rename"
      ? { custom_title: title.trim() || null }
      : { tags: tagsWithDraft() };
    try {
      onSaved(await updateLibraryVideo(video.video_id, update));
    } catch (caught) {
      setError(featureFailureMessage(caught, "We couldn’t save this library item."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={video !== null} title={mode === "rename" ? "Rename video" : "Edit tags"} onClose={onClose} actions={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" pending={saving} type="submit" form="library-metadata-form">{saving ? "Saving…" : "Save changes"}</Button></>}>
      <form className="stack-form" id="library-metadata-form" onSubmit={save}>
        {mode === "rename" ? (
          <Field label="Video title" value={title} maxLength={512} onChange={(event) => setTitle(event.target.value)} hint="Leave blank to restore the title captured from the source." />
        ) : (
          <div className="ui-field">
            <label className="ui-field__label" htmlFor="library-tag-input">Tags</label>
            <div className="tag-entry">
              <input className="ui-field__input" id="library-tag-input" list="library-tag-suggestions" maxLength={64} value={tagDraft} onChange={(event) => setTagDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addTag(); } }} />
              <Button onClick={addTag}>Add tag</Button>
            </div>
            <datalist id="library-tag-suggestions">{suggestions.map((tag) => <option value={tag} key={tag} />)}</datalist>
            <div className="tag-list" aria-label="Selected tags">{tags.map((tag) => <button className="tag tag--removable" type="button" key={tag} onClick={() => setTags((current) => current.filter((item) => item !== tag))}>{tag} <span aria-hidden="true">×</span><span className="visually-hidden">Remove</span></button>)}</div>
          </div>
        )}
        {error ? <p className="form-error" role="alert">{error}</p> : null}
      </form>
    </Dialog>
  );
}

function pageNumbers(currentPage: number, totalPages: number): Array<number | "ellipsis"> {
  if (totalPages <= 5) return Array.from({ length: totalPages }, (_, index) => index + 1);
  const pages = new Set([1, totalPages, currentPage - 1, currentPage, currentPage + 1]);
  const valid = Array.from(pages).filter((page) => page >= 1 && page <= totalPages).sort((a, b) => a - b);
  const result: Array<number | "ellipsis"> = [];
  valid.forEach((page, index) => {
    const previous = valid.at(index - 1);
    if (previous !== undefined && page - previous > 1) result.push("ellipsis");
    result.push(page);
  });
  return result;
}

export function LibraryPage() {
  const [filters, setFilters] = useState<FilterDraft>(EMPTY_FILTERS);
  const [query, setQuery] = useState<LibraryQuery>(toQuery(EMPTY_FILTERS));
  const [videos, setVideos] = useState<LibraryVideo[]>([]);
  const [total, setTotal] = useState(0);
  const [tags, setTags] = useState<string[]>([]);
  const [knownSources, setKnownSources] = useState<string[]>([]);
  const [view, setView] = useState<ViewMode>("list");
  const [loading, setLoading] = useState(true);
  const [reloadVersion, setReloadVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [editing, setEditing] = useState<LibraryVideo | null>(null);
  const [editMode, setEditMode] = useState<EditMode>("rename");
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
        const currentVideos = pendingEventsRef.current.reduce((items, event) => items.map((video) => applyProgress(video, event)), page.videos);
        pendingEventsRef.current = [];
        libraryLoadedRef.current = true;
        videosRef.current = currentVideos;
        setVideos(currentVideos);
        setTotal(page.total);
        setKnownSources((current) => Array.from(new Set([...current, ...page.videos.map((video) => video.source_site).filter(Boolean)])).sort());
      })
      .catch((caught: unknown) => { if (!controller.signal.aborted) setError(featureFailureMessage(caught, "We couldn’t load your library.")); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey, reloadVersion]);

  useEffect(() => {
    const controller = new AbortController();
    getLibraryTags(controller.signal)
      .then((response) => setTags(response.tags))
      .catch((caught: unknown) => { if (!controller.signal.aborted) setLiveError(featureFailureMessage(caught, "Tag suggestions are unavailable.")); });
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
          } else {
            const page = await getLibrary(query, controller.signal);
            if (!controller.signal.aborted) {
              videosRef.current = page.videos;
              setVideos(page.videos);
              setTotal(page.total);
            }
          }
        }
      } catch (caught) {
        if (!controller.signal.aborted) setLiveError(featureFailureMessage(caught, "Live progress is unavailable. Refresh to update processing videos."));
      }
    })();
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey]);

  const pageStart = query.offset ?? 0;
  const pageEnd = Math.min(pageStart + videos.length, total);
  const currentPage = Math.floor(pageStart / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filtered = hasNarrowingFilter(query);
  const resultSummary = useMemo(() => total === 0 ? "No videos" : `Showing ${pageStart + 1}–${pageEnd} of ${total} videos`, [pageEnd, pageStart, total]);

  function updateFilters(update: Partial<FilterDraft>) {
    const next = { ...filters, ...update };
    setFilters(next);
    setQuery(toQuery(next));
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setQuery(toQuery(filters));
  }

  function resetFilters() {
    setFilters(EMPTY_FILTERS);
    setQuery(toQuery(EMPTY_FILTERS));
  }

  function openEdit(video: LibraryVideo, mode: EditMode) {
    setEditMode(mode);
    setEditing(video);
  }

  async function confirmRemoval() {
    if (!removing) return;
    const failedJobId = isFailedJob(removing) ? removing.job_id : null;
    if (!removing.video_id && !failedJobId) return;
    setRemovalPending(true);
    setRemovalError(null);
    try {
      if (failedJobId) await removeFailedLibraryJob(failedJobId);
      else await removeLibraryVideo(removing.video_id!);
      setVideos((current) => {
        const updated = current.filter((video) => failedJobId ? video.job_id !== failedJobId : video.video_id !== removing.video_id);
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
      <header className="library-heading">
        <div><h1>Library</h1><p>All your videos, ready to search.</p></div>
        <span>{total} {total === 1 ? "video" : "videos"}</span>
      </header>

      <div className="library-toolbar" aria-label="Library filters">
        <form className="library-search" onSubmit={submitSearch}>
          <SearchIcon /><label className="visually-hidden" htmlFor="library-search">Search video titles</label>
          <input id="library-search" type="search" value={filters.search} placeholder="Search video titles" onChange={(event) => setFilters({ ...filters, search: event.target.value })} />
        </form>
        <label className="library-select"><span className="visually-hidden">Tags</span><select aria-label="Filter by tag" value={filters.tag} onChange={(event) => updateFilters({ tag: event.target.value })}><option value="">Tags</option>{tags.map((tag) => <option key={tag}>{tag}</option>)}</select></label>
        <label className="library-select"><span className="visually-hidden">Source</span><select aria-label="Filter by source" value={filters.source_site} onChange={(event) => updateFilters({ source_site: event.target.value })}><option value="">Source</option>{knownSources.map((source) => <option value={source} key={source}>{source.replace(/^www\./, "")}</option>)}</select></label>
        <label className="library-select"><span className="visually-hidden">Stage</span><select aria-label="Filter by stage" value={filters.stage} onChange={(event) => updateFilters({ stage: event.target.value as FilterDraft["stage"] })}><option value="">Stage</option>{(["downloading", "transcribing", "understanding", "ready", "partial", "failed"] as ReadinessStage[]).map((stage) => <option value={stage} key={stage}>{stageLabel(stage)}</option>)}</select></label>
        <details className="date-filter">
          <summary>Date</summary>
          <div><label>From<input type="date" value={filters.added_after} onChange={(event) => updateFilters({ added_after: event.target.value })} /></label><label>To<input type="date" value={filters.added_before} onChange={(event) => updateFilters({ added_before: event.target.value })} /></label>{filters.added_after || filters.added_before ? <button type="button" onClick={() => updateFilters({ added_after: "", added_before: "" })}>Clear dates</button> : null}</div>
        </details>
        <label className="library-select library-sort"><span>Sort:</span><select aria-label="Sort library" value={`${filters.sort}:${filters.direction}`} onChange={(event) => { const [sort, direction] = event.target.value.split(":") as [FilterDraft["sort"], FilterDraft["direction"]]; updateFilters({ sort, direction }); }}><option value="added_at:desc">Date added</option><option value="added_at:asc">Oldest added</option><option value="duration:desc">Longest</option><option value="duration:asc">Shortest</option></select></label>
        <div className="view-toggle" aria-label="View style"><button type="button" className={view === "list" ? "view-toggle__active" : ""} aria-label="List view" aria-pressed={view === "list"} onClick={() => setView("list")}><ListIcon /></button><button type="button" className={view === "grid" ? "view-toggle__active" : ""} aria-label="Grid view" aria-pressed={view === "grid"} onClick={() => setView("grid")}><GridIcon /></button></div>
      </div>

      {filtered ? <button className="library-clear-filters" type="button" onClick={resetFilters}>Clear filters</button> : null}
      {liveError ? <div className="inline-notice" role="status">{liveError}</div> : null}
      {loading ? <LoadingState label="Loading your library…" /> : error ? <ErrorState title="Unable to load library" message={error} actionLabel="Try again" onAction={() => setReloadVersion((current) => current + 1)} /> : videos.length === 0 && !filtered ? (
        <EmptyState title="Your library is ready for its first video" description={<p>Videos arrive through the Chrome extension: open a video in Chrome, send it with VidSeek, and follow its progress here. The website cannot ingest URLs or files.</p>} action={<div className="empty-state-actions"><a className="button-link button-link--primary" href={EXTENSION_INSTALL_URL} target="_blank" rel="noreferrer">Install the Chrome extension</a><Link to={ROUTES.setup}>Read the setup guide</Link></div>} />
      ) : videos.length === 0 ? (
        <EmptyState title="No videos match these filters" description="Try a broader title, source, date, or stage filter." action={<Button onClick={resetFilters}>Clear filters</Button>} />
      ) : (
        <>
          {view === "list" ? <div className="library-table-wrap"><table className="library-table"><thead><tr><th>Video</th><th>Source</th><th>Tags</th><th>Added</th><th>Duration</th><th>Status</th><th><span className="visually-hidden">Actions</span></th></tr></thead><tbody>{videos.map((video) => <VideoRow key={video.job_id ?? video.video_id!} video={video} onEdit={openEdit} onRemove={(item) => { setRemovalError(null); setRemoving(item); }} />)}</tbody></table></div> : <VideoGrid videos={videos} onEdit={openEdit} onRemove={(item) => { setRemovalError(null); setRemoving(item); }} />}
          <footer className="library-footer"><p aria-live="polite">{resultSummary}</p>{totalPages > 1 ? <nav className="pagination" aria-label="Library pages"><Button variant="ghost" aria-label="Previous page" disabled={currentPage === 1} onClick={() => setQuery({ ...query, offset: Math.max(0, pageStart - PAGE_SIZE) })}>‹</Button>{pageNumbers(currentPage, totalPages).map((page, index) => page === "ellipsis" ? <span key={`ellipsis-${index}`}>…</span> : <button type="button" className={page === currentPage ? "pagination__current" : ""} aria-current={page === currentPage ? "page" : undefined} key={page} onClick={() => setQuery({ ...query, offset: (page - 1) * PAGE_SIZE })}>{page}</button>)}<Button variant="ghost" aria-label="Next page" disabled={currentPage === totalPages} onClick={() => setQuery({ ...query, offset: pageStart + PAGE_SIZE })}>›</Button></nav> : null}</footer>
        </>
      )}

      <MetadataDialog video={editing} mode={editMode} suggestions={tags} onClose={() => setEditing(null)} onSaved={(saved) => { setVideos((current) => { const updated = current.map((video) => video.video_id === saved.video_id ? saved : video); videosRef.current = updated; return updated; }); setTags((current) => Array.from(new Set([...current, ...saved.tags])).sort()); setEditing(null); }} />
      <Dialog open={removing !== null} title="Remove this video?" onClose={() => setRemoving(null)} actions={<><Button variant="ghost" onClick={() => setRemoving(null)}>Cancel</Button><Button className="danger-button" pending={removalPending} onClick={confirmRemoval}>{removalPending ? "Removing…" : "Remove video"}</Button></>}>{removing && isFailedJob(removing) ? <p>This upload failed before a video was saved, so there is nothing else to delete. You can add the video again from the extension.</p> : <p>Removing this link permanently deletes your chat history and pins for this video. Re-adding the video later restores its shared video content and artifacts, but your chat history is permanently lost.</p>}{removalError ? <p className="form-error" role="alert">{removalError}</p> : null}</Dialog>
    </div>
  );
}

function SearchIcon() { return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none"><circle cx="11" cy="11" r="7" /><path d="m16.5 16.5 4 4" /></svg>; }
function PlayIcon() { return <svg viewBox="0 0 24 24"><path d="m9 7 8 5-8 5V7Z" /></svg>; }
function PencilIcon() { return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none"><path d="m4 20 4.5-1 10-10-3.5-3.5-10 10L4 20Z" /><path d="m13.5 6.5 3.5 3.5" /></svg>; }
function TagIcon() { return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none"><path d="m3 12 9 9 9-9V3h-9L3 12Z" /><circle cx="16" cy="8" r="1" /></svg>; }
function TrashIcon() { return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none"><path d="M4 7h16M9 7V4h6v3m3 0-1 14H7L6 7m4 4v6m4-6v6" /></svg>; }
function ListIcon() { return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M5 6h14M5 12h14M5 18h14" /></svg>; }
function GridIcon() { return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 4h6v6H4V4Zm10 0h6v6h-6V4ZM4 14h6v6H4v-6Zm10 0h6v6h-6v-6Z" /></svg>; }
