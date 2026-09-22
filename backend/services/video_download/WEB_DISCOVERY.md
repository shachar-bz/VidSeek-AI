# Authenticated web video discovery

The extension observes the user's rendered page. The backend does not open a second
login session. Inspect collects video/source/track elements, open shadow roots,
bounded JSON and JSON objects inside inline scripts, Open edX metadata, and resource
timing. Each discovered video is kept separate, including multiple videos in one frame.
Cross-origin frames are inspected separately after Chrome grants their origin access.

For lazy players, scroll the player into view and play it. Inspect again, or finish
playback verification: it enumerates the frames and scans the DOM again. Merely finding
a lazy iframe does not load or play arbitrary page content. YouTube iframe identities,
including data-src placeholders, go to the existing YouTube pipeline. Wrapper captions
stay attached to that identity (for example, Hebrew CampusIL course captions).

## Captions and timing

Track URLs are read in their authenticated owner frame when possible, then through the
extension with host permission. Reads have a 15-second timeout and a 2 MB limit; at most
five preferred tracks are fetched concurrently. Known VTT/SRT/TTML and Open edX JSON
are parsed locally. Open edX times are explicitly milliseconds; native cues are seconds.
Original cues are saved in source_segments. Missing end times remain absent there;
details.inferred_end_times marks cases where normalization supplied display boundaries.
Caption cue timestamps are supported; this change does not add a separate chapter API.

Unknown JSON tables use optional structured model output. The model receives observed
field paths, URL hosts/extensions, types, text lengths and numeric samples. It returns
only URL indices and field mappings, never replacement URLs, speech or invented times.
Cookies, authorization headers, signed query strings and raw caption text are withheld.
Every returned index, key and timing range is checked locally. Ambiguity, invalid output,
timeout or unavailable configuration yields no mapping. Existing transcription/alignment
fallbacks remain available when no usable timed captions exist.

Configuration in backend/.env or the process environment:

```
VIDSEEK_DISCOVERY_LLM=true
VIDSEEK_DISCOVERY_MODEL=gpt-5.6-sol
```

The resolver uses the project's existing OPENAI_API_KEY_DUDU. Set
VIDSEEK_DISCOVERY_LLM=false to disable it. This is a fallback, not proof that an arbitrary
website schema can be understood reliably. Signed addresses stay local to the companion
and must still be valid when downloaded.

## Playback capture and download

Chrome 125+ is required for flat debugger sessions. Capture attaches recursively to
out-of-process iframe targets, records request headers and bounded caption/JSON/manifest
bodies, and filters known ad hosts, audio-only responses and segment files. It does not
record media bytes. DRM signals stop the download; no DRM bypass is attempted. Finish
ads before starting verification, especially when an ad activates encrypted playback.

Selected direct resources or HLS/DASH manifests are downloaded with the user's captured
cookies and per-request headers. The backend validates remote requests and handles
adaptive video/audio through yt-dlp/FFmpeg. A selected source never falls back to a
different video on the containing page. Capture retries must match the selected resource
path; ambiguous captures require reinspection. Captions from ambiguous multi-source
captures are not assigned to every video.

Each selected video gets a separate deduplication identity while the actual page/frame
URLs remain the request/referrer URLs. Subtitle filenames preserve language suffixes.

## Site evidence and validation

Observed structures from the user's open pages, represented by sanitized DOM fixtures:

| Site | Observed resource | Caption evidence |
| --- | --- | --- |
| Coursera | Signed native source URLs | Native tracks using subtitleAssetProxy URLs |
| TED | HLS in hydration data; main player uses blob | No usable timed track observed in this talk |
| TED Ed | YouTube iframe | Existing YouTube route |
| ynet | Three inline SiteVideoMedia configurations; MPD and progressive MP4 | No captions observed |
| TikTok | Per-item extensionless playAddr/downloadAddr and format hints | Empty subtitle fields in inspected items |
| CampusIL | Course iframe, separate video blocks, YouTube embeds | Hebrew translation endpoint and DOM cue starts |

Tests cover those structures, selection identity, local time parsing, validated unknown
schema mapping, authenticated caption read limits, child debugger sessions and preservation
of course captions through the YouTube pipeline. They are fixture/mocked integration tests,
not full live downloads from all six sites. A real downloader smoke test on the supplied ynet page succeeded (7,668,673 bytes, 33.941 seconds, validated with FFprobe). The configured OpenAI API returned HTTP 429 for a synthetic resolver smoke test; successful live model inference remains unverified. Browser permissions, anti-bot checks,
expiring URLs, closed shadow roots and DRM can still prevent a site's acquisition.

Build the extension with npm install, npm run typecheck, npm test and npm run build in
chrome-extension. Load that worktree's chrome-extension/dist as an unpacked extension,
and run the companion from the same worktree with the project's existing backend settings.
If Chrome assigns a different extension ID, include it in VIDSEEK_EXTENSION_IDS.
