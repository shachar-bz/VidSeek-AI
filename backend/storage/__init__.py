"""Where a video's bytes and its records are kept.

This is the layer that outlives one machine, or is meant to. `r2` holds the video files
themselves in a Cloudflare R2 bucket. `transcript_store` holds the normalized transcript
of each video, still as a JSON file under the download root, and is written as the seam a
database will replace without any caller noticing. Supabase is what will sit beside them
here and hold the rest of what describes a video — jobs, users, metadata — and is not
configured yet.

Nothing is re-exported here on purpose. `transcript_store.save` says what it acts on at
the call site; `storage.save` would not.

Like `core`, this layer may not import from `backend.api`: a service reaches down into
storage, never the other way round. `transcript_store` is the one exception to that rule
today, because normalizing a transcript is a service's job and the store has to speak the
normalized shape.
"""
