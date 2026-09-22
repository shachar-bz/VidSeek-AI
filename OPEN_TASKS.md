# Open tasks

Known gaps in `backend/services/video_download/` and `chrome-extension/`, left open
deliberately. Each entry says where it stands, what actually goes wrong, and what closing
it would take.

Everything listed here is a **known limitation, not a regression**: the download,
transcript, cancel and capture paths were exercised end to end against a running
companion and a real browser before this file was written.

---

## 1. Discovery misses embedded and adaptive players

The remaining two share one root: `discoverPage` only reads what's already sitting in the
DOM before playback starts.

### 1a. MSE and `blob:` playback look like "no video"

**Status:** open. **Problem:** `discoverPage` drops `blob:` URLs and never reads
`video.srcObject`. Most adaptive players feed the element through Media Source Extensions,
so the element's `currentSrc` is a `blob:` URL and discovery finds zero candidates. The
popup says "No direct source found yet", the job falls back to handing the page URL to
yt-dlp, that fails, and only then is capture offered.

**To close:** when a `<video>` has a `blob:` source or a non-null `srcObject`, report that
as a flag on `DiscoveryResult` (it is not a media candidate). The popup can then offer
capture straight away instead of after a failed download. Needs a matching optional field
on `CreateVideoJobRequest`, or it can stay purely client-side.

### 1b. The `<video>` element's MIME type is always empty

**Status:** open, cosmetic. **Problem:** `discoverPage` reads
`video.getAttribute("type")`, but `type` is a `<source>` attribute and is never present on
`<video>`; the call always yields `null`. So a `<video src>` candidate is classified by URL
extension alone, and an extension-less signed CDN URL is dropped entirely.

**To close:** either drop the dead `getAttribute` call, or derive a type from a `<source>`
sibling or `canPlayType`. Dropping it alone changes nothing; it is listed because it reads
as though it does something.

---

## 2. SSRF gate: known limits, accepted

**Status:** accepted as is, documented here rather than fixed.

`validate_remote_url` resolves a hostname and rejects it unless every resolved address is
globally routable. That holds for a direct URL, and it is verified by tests. Three gaps
remain:

- **Redirects are validated after the fact.** `SafeYoutubeDL.urlopen` validates
  `response.url`, but yt-dlp has already followed the redirect chain by then. A 302 to an
  internal address is issued; only reading the body is prevented.
- **DNS rebinding is not mitigated.** The name is resolved once for validation and again
  when connecting. A short-TTL record can return a public address to the first and a
  private one to the second.
- **Adaptive fragments bypass it.** HLS and DASH segments fetched by ffmpeg or an external
  downloader never pass through `SafeYoutubeDL.urlopen`.

**Why accepted:** the companion binds to loopback, accepts jobs only from an allowlisted
extension id, and acts on a page the user already has open in their own browser. The
attacker would need to already control what the user is watching.

**If that changes:** disabling redirect following and validating each hop closes the first
gap; a custom resolver that pins the validated address into the connection closes the
second. The third needs the fragment fetches routed through the same gate.

---

## 3. Jobs are never evicted

**Status:** open; the schema for the fix now exists. **Problem:** `JobManager._jobs` only
grows. A failed job that is still capture-eligible keeps its caption text (up to 50 × 2 MB)
so the retry has something to work with, and nothing ever drops it.

**To close:** `0018_video_jobs.sql` creates the `video_jobs` table a job's status, phase,
progress, message and error code now belong in. Once the manager writes there, the
in-memory dict only has to hold what a *running* job needs — the cancel event, the
browser-supplied cookies and headers, the caption text a capture retry works from — and a
terminal job can be dropped from it entirely, because everything anyone reads afterwards is
a row. The website needs that table anyway: a hosted page cannot see a dict in the
companion's memory, and a restart loses every job in flight.

---

## 4. `discoverPage` has no automated test

**Status:** partially covered. **Problem:** `tests/discovery.test.ts` covers
`classifyMediaUrl`, `originPatterns` and `chooseDirectCandidate`, but not `discoverPage`
itself, which holds the real logic. Vitest runs in the plain node environment with no DOM.

`discoverPage` *was* verified against a real browser over a fixture page — relative URL
resolution, `blob:` filtering, `<source>`/`<track>` walking, JSON-LD `@graph` traversal,
performance-entry mining, transcript scraping and dedup all behaved correctly — but that
check is manual and does not run in CI.

**To close:** add `jsdom` (or `happy-dom`) and `environment: "jsdom"` to `vite.config.ts`,
then assert against a fixture document. Note that `discoverPage` duplicates its regexes
on purpose — it is serialized into the page by `executeScript` and cannot reference module
scope — so a test also guards against the two copies drifting apart.

---

## 5. A missing FFmpeg can yield a silent video

**Status:** partly handled. **Problem:** `_download_options` sets
`merge_output_format: "mp4/mkv"` with `no_warnings: True`. If ffmpeg is absent, yt-dlp
cannot mux the separate video and audio streams and its warning is suppressed.
`_find_downloaded_media` then picks the largest file — the video-only stream — which passes
`probe_media_file` because it does have a video stream, and goes to ElevenLabs as a silent
video. The result is a "successful" job with an empty transcript.

`probe_media_file` now raises `MissingDependencyError` when `ffprobe` is missing, which the
API maps to 503 naming FFmpeg, so the common case of no FFmpeg at all is caught. The
remaining hole is an install with `ffprobe` but no usable `ffmpeg`.

**To close:** check for an audio stream after a merge was requested, and fail the job with
an actionable message rather than shipping a silent video.

---

## 6. Chapters, memories and embeddings — closed

**Status:** closed. Kept here because this entry was the longest-standing gap in the
project and its absence would read as an oversight.

`backend/download_pipeline/` now runs all four stages of a job in order — acquire, store,
segment, embed — so every finished video is divided into memories, grouped into chapters
and embedded without anything else being asked to trigger it:

- `segmentation.py` calls `segment_transcript` and `group_memories`, and writes both
  through `PostgresMemories.replace` and `PostgresChapters.replace`.
- `embedding.py` calls `embed_memories_for_video` and `embed_chapters_for_video`.
- Both are reported as problem codes rather than raising, so a model that will not answer
  costs a video its chapters and not its download.

`0012_chapters_memories_written.sql` corrected what those two tables say about themselves,
and `0021_embedding_ann_indexes.sql` added the hnsw index on both `vector(384)` embedding
columns that 0007, 0010 and 0011 each deferred while nothing was writing them.

**What is still not produced anywhere:** a video's generated summary, key takeaways and
suggested questions. `0020_video_insights.sql` creates the table they belong in;
§12.4 of `frontend/WEBSITE_FUNCTIONALITY.md` is what has to fill it, as a fifth pipeline
stage after embedding. Until it does, no video reaches the website's `ready` stage.
