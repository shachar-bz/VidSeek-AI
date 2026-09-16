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
   # Required for a job to finish: Blob Storage is where a finished video is uploaded,
   # and the local copy is deleted once it is there. A job fails at the upload step
   # without them. See backend/.env.example for the full set.
   AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
   AZURE_STORAGE_CONTAINER_NAME=videos
   # Optional; where the video's metadata, transcript and comments are recorded. Without
   # it a job still succeeds and reports that the video was stored but not recorded.
   AZURE_DATABASE_URL=postgresql://user:password@server.postgres.database.azure.com:5432/db?sslmode=require
   ```

   Then apply the schema once, from the repository root:

   ```powershell
   python -m backend.storage.postgres.migrate
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

