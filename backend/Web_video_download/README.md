# VidSeek local companion

The companion accepts jobs only from configured Chrome extension IDs, downloads into a
single local root, and passes the resulting media to the existing ElevenLabs integration
when captions or a published transcript are unavailable.

## Setup

1. Install Python 3.11 or newer, FFmpeg, and the packages in `backend/requirements.txt`.
2. Build and load `frontend/chrome-extension/dist` as an unpacked Chrome extension.
3. Copy the extension ID from `chrome://extensions` into `backend/.env`:

   ```dotenv
   VIDSEEK_EXTENSION_IDS=the_extension_id
   ELEVENLABS_API_KEY=your_key
   FIRECRAWL_API_KEY=your_key
   # Optional; this must match Chrome's Downloads/VidSeek directory.
   VIDSEEK_DOWNLOAD_ROOT=C:\Users\you\Downloads\VidSeek
   ```

4. From the repository root, start the loopback service:

   ```powershell
   uvicorn backend.app:app --host 127.0.0.1 --port 8765
   ```

The service intentionally refuses non-loopback deployment assumptions, YouTube, private
network targets, live streams, and DRM-protected media. Firecrawl receives only the public
page URL; Chrome cookies and captured request headers are kept on the machine and discarded
after the job.

