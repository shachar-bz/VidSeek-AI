# VidSeek local companion

The companion accepts jobs only from configured Chrome extension IDs, downloads into a
single local root, and passes the resulting media to the existing ElevenLabs integration
when captions or a published transcript are unavailable.

## Setup

1. Install Python 3.11 or newer, FFmpeg, and the packages in `backend/requirements.txt`.
2. Build and load `chrome-extension/dist` as an unpacked Chrome extension.
3. Copy the extension ID from `chrome://extensions` into `backend/.env`:

   ```dotenv
   VIDSEEK_EXTENSION_IDS=the_extension_id
   ELEVENLABS_API_KEY_TRANSCRIPT=your_key
   FIRECRAWL_API_KEY=your_key
   # Optional; this must match Chrome's Downloads/VidSeek directory.
   VIDSEEK_DOWNLOAD_ROOT=C:\Users\you\Downloads\VidSeek
   # Optional; where a finished video is uploaded. Without these a job downloads and
   # transcribes as before and the video stays on this machine only. See
   # backend/.env.example for the full set.
   R2_ACCESS_KEY_ID=your_key_id
   R2_ACCESS_KEY=your_secret
   R2_ENDPOINT_URL=https://your_account_id.r2.cloudflarestorage.com
   R2_BUCKET_NAME=your_bucket
   ```

4. From the repository root, start the loopback service:

   ```powershell
   uvicorn backend.app:app --host 127.0.0.1 --port 8765
   ```

The service intentionally refuses non-loopback deployment assumptions, YouTube, private
network targets, live streams, and DRM-protected media. Firecrawl receives the page URL
with its query string and fragment removed, so this session's signed parameters stay local;
Chrome cookies and captured request headers are kept on the machine and discarded after the
job.

The private-network check resolves a hostname and rejects it unless every address is
globally routable. It does not cover redirects already followed by yt-dlp, DNS rebinding,
or HLS/DASH fragments fetched by FFmpeg. See `OPEN_TASKS.md` in the repository root for why
that is accepted here and what closing it would take.

