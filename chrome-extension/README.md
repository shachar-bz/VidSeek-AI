# VidSeek AI Chrome extension

Build the internal Manifest V3 extension with:

```powershell
npm install
npm run typecheck
npm test
npm run build
```

Load `dist/` from `chrome://extensions` using **Load unpacked**, then place its generated
extension ID in the companion's `VIDSEEK_EXTENSION_IDS` setting. The companion must be
running at `http://127.0.0.1:8765`.

The first click inspects the active page. If it finds only a plain progressive file, a
second, explicit click requests access to the discovered page/CDN origins and starts the
download directly.

When no caption candidates were found, inspection also reads an open transcript panel
using its accessible label or transcript/caption/subtitle markup, without site-specific
selectors. It pairs visible clock labels with speech and preserves their timestamps.
For a panel that loads rows while scrolling, inspection collects overlapping windows
for up to eight seconds and restores the original scroll position. It does not click
transcript tabs or load unopened panels automatically.

This fallback requires one native video player with a known duration and one discovered
video. It rejects hidden panels, ambiguous owners, invalid or non-increasing clocks,
large gaps, and text that does not cover approximately the whole recording. Partial
transcripts remain a reason to use the existing transcription fallback. Open the full
transcript panel and inspect again if the site's transcript was not loaded initially.

If discovery finds an adaptive (HLS/DASH) source, or nothing playable yet, DRM can still
activate once the player actually starts — `video.mediaKeys` is `null` until then, so
inspecting before playback cannot rule it out. In that case the popup shows **Verify &
play** instead of Download: it requests the same page/CDN access, attaches Chrome's
debugger, and asks you to reload the page and press Play. Reopen the popup and click
**Finish verification**; the extension inspects the manifest, any license-server traffic
and the page's own EME activity (`setMediaKeys`, the `encrypted` event) before deciding.
DRM found at any point stops the flow with a clear message and no download is attempted; no
DRM found starts the download immediately, using what was actually observed during
playback. The debugger always detaches before the popup moves on.

**Capture difficult player** is the separate, existing fallback for a download that fails
for a non-DRM reason (missing headers, an unusual origin): reload or replay the video, then
click **Stop capture and retry**. It goes through the same DRM check before retrying.

Once a scan starts, the panel shows its progress until the video is ready, then opens a chat
with the video agent — the same conversations the website shows. The scan is remembered per
signed-in user, so closing the panel or signing out does not stop or lose it: the companion
keeps running the job, and reopening the panel (or signing back in) returns to the progress
screen or the chat. A cited timestamp in an answer seeks the video when its tab is active.
