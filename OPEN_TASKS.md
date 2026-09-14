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

These four share one root: `discoverPage` only reads what the top frame's DOM exposes
before playback starts. The capture fallback covers every case, but only after a download
attempt has already failed, which costs the user a slow round trip.

### 2a. Iframes are never scanned

**Status:** open. **Problem:** `popup.ts` calls `chrome.scripting.executeScript` without
`allFrames: true`, so only the top frame is inspected. Vimeo, JW Player, Brightcove and
Kaltura embeds are usually in an iframe, and discovery returns nothing for them.

**To close:** pass `allFrames: true` and merge the per-frame results (`executeScript`
resolves to one entry per frame). `activeTab` already grants sub-frame access, so no new
permission is needed. Dedup by resolved URL, as the single-frame path already does, and
keep the 100/50 caps applied after the merge rather than per frame.

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

### 2c. DRM is only detected after playback starts

**Status:** open. **Problem:** `drm_detected` reads `video.mediaKeys`, which is `null`
until the player calls `setMediaKeys()`. Inspecting a DRM-protected page before pressing
play reports `drm_detected: false`, and the refusal only happens later, if at all.

**To close:** re-check at download time rather than at inspect time, or watch for
`encrypted` events on the element during a short observation window. Note the companion
also refuses DRM independently, from yt-dlp's `has_drm`, so this is a wasted round trip
rather than a way to download protected media.

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

## 7. Caption parsing is duplicated between the two download pipelines

**Status:** open. **Problem:** `services/video_download/web/transcript.py` and
`services/video_download/youtube/captions.py` each carry their own WebVTT parser,
timestamp parser, cue tag stripper and `CaptionSegment` dataclass. They can drift, and a
fix to one will not reach the other.

**To close:** promote one parser into `backend/core/captions.py` and have both pipelines
use it. Not urgent — both are covered by their own tests — but the next caption bug will
have to be fixed twice.

---

## 8. `discoverPage` has no automated test

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

## 9. A missing FFmpeg can yield a silent video

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

## 10. Untimed page transcripts are recovered via forced alignment — closed

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

## 11. Chapters and memories tables are not built yet

**Status:** not started, deliberately deferred. `backend/storage/supabase/` holds `videos`
and `transcript_segments` today; `chapters` and `memories` are the two tables Supabase was
introduced for that have no schema, no store, and nothing producing them yet.

**What each is for:**

- `chapters` — one row per chapter of a video: a title, a summary, a start/end timestamp
  range, and an embedding, linked to `video_id`. Nothing currently segments a video into
  chapters; that segmentation is itself unbuilt.
- `memories` — one row per notable moment within a chapter: the original text, a summary
  or semantic idea, a timestamp range, and an embedding, linked to both `video_id` and
  `chapter_id`. Nothing currently extracts memories either.

**To close:** once something produces chapters and memories, add
`0003_chapters.sql` and `0004_memories.sql` alongside the existing migrations in
`backend/storage/supabase/migrations/`, following the shape of `0002_transcript_segments.sql`
(FK to `videos`, `ON DELETE CASCADE`, RLS enabled with no policies). `pgvector` is already
enabled by `0001_videos.sql` for exactly this; the one decision to make first is which
embedding model sets the `vector(N)` dimension, since that is fixed at table creation.
Store code goes in `backend/storage/supabase/chapters.py` and `memories.py`, mirroring
`video_records.py` and `transcript_segments.py`.
