"""Where a video's bytes and, in time, its records are kept.

This is the layer that outlives one machine. `r2` holds the video files themselves in a
Cloudflare R2 bucket; VIDSEEK_DOWNLOAD_ROOT stays what it always was, a scratch copy on
whichever laptop ran the job. Supabase will sit beside it here and hold everything that
describes a video rather than being one — jobs, transcripts, metadata — and is not
configured yet.

Like `core`, this layer may not import from `backend.services` or `backend.api`: a
service reaches down into storage, never the other way round.
"""
