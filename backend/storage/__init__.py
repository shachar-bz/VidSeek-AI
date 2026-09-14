"""Where a video's bytes and its records are kept.

This is the layer that outlives one machine, or is meant to. `r2` holds the video files
themselves in a Cloudflare R2 bucket. `supabase` holds what describes them: `videos`, one
row per stored object, `transcript_segments` hanging off it, and — once something produces
them — the `chapters` and `memories` that will hang off it too. The split between the two
databases is the obvious one: bytes in R2, everything else in Postgres, joined by
`videos.r2_object_key`.

`transcript_store` keeps the same normalized transcript as a JSON file under the download
root. It is not yet redundant: it is keyed by the video's own id and needs no network,
which is what the pipeline reads back today, while the Supabase copy is keyed by a row id
that only exists once a video has been uploaded. It is still the seam Supabase will take
over, and a caller that builds its own transcript path defeats that.

Nothing is re-exported here on purpose. `transcript_store.save` says what it acts on at
the call site; `storage.save` would not.

Like `core`, this layer may not import from `backend.api`: a service reaches down into
storage, never the other way round. `transcript_store` is the one exception to that rule
today, because normalizing a transcript is a service's job and the store has to speak the
normalized shape.
"""
