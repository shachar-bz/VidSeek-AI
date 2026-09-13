# VidSeek Chrome extension

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

The first click inspects the active page. A second, explicit click requests access only to
the discovered page/CDN origins and starts the download. When a normal authenticated replay
fails, **Capture difficult player** attaches Chrome's debugger; reload or replay the video,
then click **Stop capture and retry**. The debugger detaches before the captured request is
submitted.

