"""Where a video's bytes and its records are kept.

This is the layer that outlives one machine, or is meant to. `blob` holds the video files
themselves in an Azure Blob Storage container. `postgres` holds what describes them, in one
Azure Database for PostgreSQL server: `videos`, one row per stored blob, with
`transcript_segments` and `comments` hanging off it (the latter only ever populated for
YouTube videos), and `memories`, `chapters` and `chapter_embeddings` still waiting for
something to produce them -- `memory_embeddings` is the first of the four with a writer,
`backend.services.embeddings.memory_embedding`. The split between the two is the obvious
one: bytes in Blob Storage, everything else in Postgres, joined by `videos.blob_name`.

Both are reached remotely. Nothing in this project is deployed to Azure — the backend is
still the loopback companion — so these two connection strings are the whole of what makes a
video durable, and neither of them ever reaches the extension.

`transcript_store` keeps the same normalized transcript as a JSON file under the download
root. It is not yet redundant: it is keyed by the video's own id and needs no network,
which is what the pipeline reads back today, while the database copy is keyed by a row id
that only exists once a video has been uploaded. It is still the seam `postgres` will take
over, and a caller that builds its own transcript path defeats that.

Nothing is re-exported here on purpose. `transcript_store.save` says what it acts on at
the call site; `storage.save` would not.

Like `core`, this layer may not import from `backend.api`: a service reaches down into
storage, never the other way round. `transcript_store` is the one exception to that rule
today, because normalizing a transcript is a service's job and the store has to speak the
normalized shape.
"""
