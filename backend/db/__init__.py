"""Persistence, such as it is today.

There is still no database: jobs live in memory for the lifetime of the process, and the
one thing that outlives them is the normalized transcript, which `transcript_store` keeps
as a JSON file per video under VIDSEEK_DOWNLOAD_ROOT. That module is written so that the
database, when it arrives, replaces it without any caller noticing.

Nothing is re-exported here on purpose. `transcript_store.save` and `transcript_store.load`
say what they act on at the call site; `db.save` and `db.load` would not.
"""
