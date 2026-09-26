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
   # Optional; this must match Chrome's Downloads/VidSeek directory. Each job works in
   # its own jobs/<job_id> folder under it, deleted when the job ends, and the companion
   # empties jobs/ and visual-queue/ when it starts; keep nothing of your own in either.
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

By default the service refuses non-loopback clients, private network targets, live streams,
and DRM-protected media. Chrome cookies and captured request headers are kept on the machine
and discarded after the job.

## Hosted API

The same ASGI entry point also serves the website API. A hosted deployment sets
`VIDSEEK_REQUIRE_LOOPBACK=false` and lists every exact website origin in the comma-separated
`VIDSEEK_WEBSITE_ORIGINS` value. `VIDSEEK_EXTENSION_IDS` remains configured when that API must
also accept extension traffic. Wildcard website origins are rejected because authenticated
requests carry bearer credentials. Keep `VIDSEEK_REQUIRE_LOOPBACK=true` (the default) for the
local companion.

The private-network check resolves a hostname and rejects it unless every address is
globally routable. It does not cover redirects already followed by yt-dlp, DNS rebinding,
or HLS/DASH fragments fetched by FFmpeg.

