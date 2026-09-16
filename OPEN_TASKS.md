# Open tasks

Known gaps in `backend/services/video_download/` and `chrome-extension/`, left open
deliberately. Each entry says where it stands, what actually goes wrong, and what closing
it would take.

Everything listed here is a **known limitation, not a regression**: the download,
transcript, cancel and capture paths were exercised end to end against a running
companion and a real browser before this file was written.

---

## 1. Verify the extension in real Chrome

**Status:** not done. Everything else has been exercised; this cannot be, without loading
the unpacked extension.

**Problem:** two behaviours are unverifiable outside a real browser.

- `chrome.permissions.request()` is called from the action popup in `popup.ts`. Chrome
  historically dismissed the popup when the permission prompt opened, which would mean
  nothing after that line runs — no session, no job, no tracker.
- The companion requires an `Origin` header. Requests from the service worker are covered
  by a host permission, and it is not certain from the source alone that Chrome attaches
  `Origin` to them.

The `Origin` half is already defused: `authorize` in `api.py` now requires `Origin` only on
state-changing methods, and a token stays bound to the origin it was issued to, so an
origin that *is* sent must still match. Polling cannot 401 for a missing header.

**To close:** build `dist/`, load it at `chrome://extensions`, put its id in
`VIDSEEK_EXTENSION_IDS`, run the companion, and take one video through inspect → download →
transcript. Confirm the popup survives the permission prompt, and that a job appears.

---

## 2. Discovery misses embedded and adaptive players

The remaining three share one root: `discoverPage` only reads what's already sitting in the
DOM before playback starts. (2a's iframe gap shared that root too, and is now closed.) The
capture fallback used to cover every remaining case, but only after a download attempt had
already failed, which cost the user a slow round trip; 2c closes that gap for DRM
specifically, with a play-and-verify step that runs before a download is ever attempted.

### 2a. Iframes are never scanned — closed

**Status:** closed. **Problem:** `popup.ts` called `chrome.scripting.executeScript` without
`allFrames: true`, so only the top frame was inspected. Vimeo, JW Player, Brightcove and
Kaltura embeds are usually in an iframe, and discovery returned nothing for them.

**Fix:** `popup.ts` now passes `allFrames: true`. `discovery.ts` exports
`mergeDiscoveryResults`, which combines the one `DiscoveryResult` per frame that
`executeScript` returns: page identity (URL, title, language) comes from the top frame
(frameId 0, falling back to whichever frame answered first if frame 0 didn't produce a
result), a DRM flag or a media/caption candidate from *any* frame counts, and candidates are
deduped by URL across frames before the existing 100/50 caps are applied to the merged
totals rather than per frame. `activeTab` already covered sub-frame access, so no new
permission was needed. Covered by `mergeDiscoveryResults` tests in `discovery.test.ts`.

### 2b. MSE and `blob:` playback look like "no video"

**Status:** open. **Problem:** `discoverPage` drops `blob:` URLs and never reads
`video.srcObject`. Most adaptive players feed the element through Media Source Extensions,
so the element's `currentSrc` is a `blob:` URL and discovery finds zero candidates. The
popup says "No direct source found yet", the job falls back to handing the page URL to
yt-dlp, that fails, and only then is capture offered.

**To close:** when a `<video>` has a `blob:` source or a non-null `srcObject`, report that
as a flag on `DiscoveryResult` (it is not a media candidate). The popup can then offer
capture straight away instead of after a failed download. Needs a matching optional field
on `CreateVideoJobRequest`, or it can stay purely client-side.

### 2c. DRM is only detected after playback starts — closed

**Status:** closed. **Problem:** `drm_detected` reads `video.mediaKeys`, which is `null`
until the player calls `setMediaKeys()`. Inspecting a DRM-protected page before pressing
play reported `drm_detected: false`, and the refusal only happened later, if at all — after
the companion had already started downloading a manifest and its segments.

**Fix:** discovery of an adaptive (HLS/DASH) source, or of nothing playable yet, now routes
through a play-and-verify step instead of an immediate Download button. `popup.ts`'s
**Verify & play** requests the same page/CDN access, then `background.ts`'s `startCapture`
attaches the debugger and injects `discovery.ts`'s `installEmeMonitor` into the page's MAIN
world, which patches `navigator.requestMediaKeySystemAccess` and `HTMLMediaElement
.setMediaKeys` and listens for the `encrypted` event. Once the user presses Play and clicks
**Finish verification**, `stopCapture` checks, before detaching: the page's own EME activity
(`readEmeMonitor`), every captured request against `isLicenseTraffic`, and every captured
HLS/DASH manifest body (read via `Network.getResponseBody` while still attached) against
`detectManifestDrm`. Any positive stops the flow with a specific reason and no job is ever
created; the same check now also guards the pre-existing post-failure capture-and-retry
path. Covered by `detectManifestDrm`/`isLicenseTraffic` tests in `discovery.test.ts`.

**Deliberately not flagged:** HLS `METHOD=AES-128` (a static key yt-dlp already fetches and
decrypts on its own) and a bare `requestMediaKeySystemAccess` call with no attached key or
`encrypted` event (several player libraries probe EME support even for unprotected content).

### 2d. The `<video>` element's MIME type is always empty

**Status:** open, cosmetic. **Problem:** `discoverPage` reads
`video.getAttribute("type")`, but `type` is a `<source>` attribute and is never present on
`<video>`; the call always yields `null`. So a `<video src>` candidate is classified by URL
extension alone, and an extension-less signed CDN URL is dropped entirely.

**To close:** either drop the dead `getAttribute` call, or derive a type from a `<source>`
sibling or `canPlayType`. Dropping it alone changes nothing; it is listed because it reads
as though it does something.

---

## 3. SSRF gate: known limits, accepted

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

## 4. Chrome's download folder must match `VIDSEEK_DOWNLOAD_ROOT`

**Status:** open. **Problem:** `background.ts` asks Chrome to save to `VidSeek/<name>`,
which Chrome resolves under whatever download folder the profile is configured with. The
companion accepts local paths only under `VIDSEEK_DOWNLOAD_ROOT`, which defaults to
`~/Downloads/VidSeek`. These agree only on a default profile. If they disagree, every
direct download is rejected as "outside VIDSEEK_DOWNLOAD_ROOT".

That rejection is no longer silent — `background.ts` now cancels the job and shows `!` on
the badge — but the message does not explain the mismatch.

**To close:** add a companion endpoint that reports the configured root, have the popup
compare it against `chrome.downloads` behaviour on first run, and say plainly which two
paths disagree. `GET /health` already exists and is a natural place to return it.

---

## 5. Jobs are never evicted

**Status:** open, low priority. **Problem:** `JobManager._jobs` only grows. A failed job
that is still capture-eligible keeps its caption text (up to 50 × 2 MB) so the retry has
something to work with, and nothing ever drops it.

**To close:** evict terminal jobs older than some age, or keep the most recent N. Restarting
the companion clears everything today, which is why this has not bitten anyone.

---

## 6. Firecrawl's containment check may reject valid transcripts

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

## 7. `discoverPage` has no automated test

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

## 8. A missing FFmpeg can yield a silent video

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

## 9. Untimed page transcripts are recovered via forced alignment — closed

**Status:** closed. A page transcript (scraped by Firecrawl, or read from a player's
transcript panel) still has no per-word timing of its own, and `normalize_caption_cues`
still refuses to fabricate it rather than spread words evenly and call the result a
timestamp — but the text is no longer thrown away just because of that.

**Behavior:** `backend/services/forced_alignment/` times that text against the video's
own audio through ElevenLabs' hosted forced aligner, on the web download pipeline, before
anything is retranscribed. The aligner only understands English, so `is_english_text`
gates every call; a transcript in another language, or an alignment call that fails, still
falls through to a full ElevenLabs transcription exactly as before. A transcript that
already has valid timing (Web captions, or YouTube captions, which always carry timing) is
used without calling either. A job left with no timing at all still finishes
`partial_success`/`untimed_transcript` — the text is kept but nothing downstream treats it
as indexable.

**Not covered:** the YouTube pipeline has no equivalent untimed-text-with-video state to
recover — its captions either carry usable timing or are treated as absent — so this path
exists only in `services/video_download/web/`.

---

## 10. Nothing writes the chapters and memories tables

**Status:** the schema exists, the writers do not. `0005_chapters.sql`,
`0006_memories.sql` and `0007_embeddings.sql` created `chapters`, `memories`,
`chapter_embeddings` and `memory_embeddings` during the move to Azure, so the shape is
settled; what is missing is a store for each and something in the request path that calls
them.

**What each is for:**

- `chapters` — one row per broad section of a video: a title, a summary and a start/end
  timestamp range, linked to `video_id`. `backend/semantic_processing/chapters/` produces
  these and is tested.
- `memories` — one row per semantic moment within a video: the original text, the model's
  summary and a timestamp range, linked to `video_id` and, once the grouping stage has run,
  to `chapter_id`. `backend/semantic_processing/memories/` produces these and is tested.

Neither stage is called from anywhere: `segment_transcript` and `group_memories` appear
only in their own packages and in the tests.

**To close:** add `backend/storage/postgres/chapters.py` and `memories.py`, mirroring
`transcript_segments.py` (a `replace` that upserts every position in one transaction and
trims the tail). Then call them from `backend/services/video_download/video_record.py`,
after the transcript is written, which is the only place that has both the transcript and
the `videos.id` the rows hang off.

**The embedding decision is still open.** `memory_embeddings.embedding` and
`chapter_embeddings.embedding` are declared as bare `vector` with no dimension, which
pgvector allows but cannot index: a similarity search against them today is a sequential
scan. Picking the embedding model fixes the dimension, and one migration then does both:

```sql
alter table public.memory_embeddings alter column embedding type vector(1536);
create index on public.memory_embeddings using hnsw (embedding vector_cosine_ops);
```

They are separate tables rather than columns on `memories` and `chapters` for exactly this
reason — an empty table can be altered freely, a column beside real rows cannot.
