"""Builds the Blob Storage client the video container is reached through.

Everything the client needs is inside the connection string -- the account, the key and the
endpoint -- so unlike the S3 client this replaces there is nothing here to assemble from
separate parts, and no protocol quirk to work around. What is left are the two upload
settings that decide how a large file is sent.

Needs AZURE_STORAGE_CONNECTION_STRING and AZURE_STORAGE_CONTAINER_NAME in `backend/.env`.
"""

from functools import lru_cache

from azure.storage.blob import BlobServiceClient

from .settings import BlobSettings, load_blob_settings

# A video is large enough that a single PUT is the wrong shape: above this the SDK stages
# the upload in blocks of the same size and commits them together. Azure allows 50,000
# blocks, which at this size covers a 3 TB file, far beyond anything this project handles.
BLOCK_BYTES = 64 * 1024 * 1024

# How many of those blocks are sent at once. Above one, the SDK reports progress out of
# order and from several threads, which is what `_byte_counter` in `video_storage` exists
# to absorb.
UPLOAD_CONCURRENCY = 4


def build_client(settings: BlobSettings | None = None) -> BlobServiceClient:
    """Return a Blob Storage client bound to the configured storage account."""
    resolved = settings or load_blob_settings()
    return BlobServiceClient.from_connection_string(
        resolved.connection_string,
        max_block_size=BLOCK_BYTES,
        max_single_put_size=BLOCK_BYTES,
    )


@lru_cache(maxsize=1)
def shared_client() -> BlobServiceClient:
    """The process-wide client, so that connections are pooled across jobs.

    The client wraps one HTTP transport and is safe to share between threads once built;
    `build_client` stays available for a test or a second account.
    """
    return build_client()
