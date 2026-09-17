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

**Status:** open, low priority. **Problem:** `JobManager._jobs` only grows. A failed job
that is still capture-eligible keeps its caption text (up to 50 × 2 MB) so the retry has
something to work with, and nothing ever drops it.

**To close:** evict terminal jobs older than some age, or keep the most recent N. Restarting
the companion clears everything today, which is why this has not bitten anyone.

---

## 4. Firecrawl's containment check may reject valid transcripts

**Status:** unverified. **Problem:** `scrape_public_page_transcript` accepts the extracted
transcript only if it appears verbatim inside the returned markdown. With
`onlyMainContent: true` the markdown usually carries speaker labels, timestamps and
structure that the extraction drops, so the check may reject almost everything and the
function may be dead in practice.

**To close:** run it against two or three real transcript pages with a `FIRECRAWL_API_KEY`
set and see whether it ever returns non-`None`. If it does not, compare normalized token
overlap instead of requiring a substring. The check exists to stop a hallucinated
transcript being persisted as fact, so it should be loosened, not removed.

---

## 5. `discoverPage` has no automated test

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

## 6. A missing FFmpeg can yield a silent video

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

## 7. Nothing writes the chapters and memories tables

**Status:** the schema exists, the writers do not. `0005_chapters.sql`,
`0006_memories.sql` and `0007_embeddings.sql` created `chapters`, `memories`,
`chapter_embeddings` and `memory_embeddings` during the move to Azure, so the shape is
settled; what is missing is a store for each and something in the request path that calls
them.

**What each is for:**

- `chapters` — one row per broad section of a video: a title, a summary and a start/end
  timestamp range, linked to `video_id`. `backend/semantic_segmentation/chapters/` produces
  these and is tested.
- `memories` — one row per semantic moment within a video: the original text, the model's
  summary and a timestamp range, linked to `video_id` and, once the grouping stage has run,
  to `chapter_id`. `backend/semantic_segmentation/memories/` produces these and is tested.

Neither stage is called from anywhere: `segment_transcript` and `group_memories` appear
only in their own packages and in the tests.

**To close:** add `backend/storage/postgres/chapters.py` and `memories.py`, mirroring
`transcript_segments.py` (a `replace` that upserts every position in one transaction and
trims the tail). Then call them from `backend/services/video_download/video_record.py`,
after the transcript is written, which is the only place that has both the transcript and
the `videos.id` the rows hang off.

**The embedding model is chosen, and both embedding tables have writers now.**
`memory_embeddings.embedding` and `chapter_embeddings.embedding` are `vector(384)`, matching
the shared all-MiniLM-L6-v2 model in `backend/services/embeddings/model.py`
(`0010_memory_embeddings_video_chapter.sql` and `0011_chapter_embeddings_video_times.sql`).
`backend/services/embeddings/memory_embedding/` and
`backend/services/embeddings/chapter_embedding/` populate them from whatever rows
`memories` and `chapters` already hold; neither is called from the request path yet, so
closing this task's `memories`/`chapters` gap is also what gives the embedding pipelines
something to run against automatically. No ANN index (hnsw or ivfflat) exists on either
column — retrieval and search strategy belong to a dedicated semantic search layer, added
when one exists, rather than to the migrations that only store the vectors.
