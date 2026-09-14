"""Builds the S3-compatible client that Cloudflare R2 speaks.

R2 is addressed through the ordinary S3 API, so boto3 is the client; only the endpoint,
the region and a couple of protocol details differ from AWS. Those differences are
collected here so that no caller has to remember them.

Needs R2_ACCESS_KEY_ID, R2_ACCESS_KEY, R2_ENDPOINT_URL and R2_BUCKET_NAME in
`backend/.env`.
"""

from functools import lru_cache

import boto3
from botocore.config import Config

from .settings import REGION, R2Settings, load_r2_settings

# R2 supports the path-style addressing boto3 defaults to for a custom endpoint, and
# SigV4 is the only signature it accepts.
SIGNATURE_VERSION = "s3v4"

# botocore 1.36 began attaching a CRC32 checksum to every upload and demanding one back
# on every download. R2 tolerates the request header but does not always return the
# matching response header, which surfaces as a checksum error on an otherwise fine
# download, so both are asked for only when the operation genuinely requires them.
CHECKSUM_MODE = "when_required"

# A video is large enough that a single PUT is the wrong shape: uploads switch to
# multipart above this, in parts of the same size. R2 allows 10,000 parts, which at this
# size covers a 640 GB file, far beyond anything this project handles.
MULTIPART_CHUNK_BYTES = 64 * 1024 * 1024

DEFAULT_MAX_RETRY_ATTEMPTS = 5


def build_client(settings: R2Settings | None = None):
    """Return a boto3 S3 client bound to the configured R2 account."""
    resolved = settings or load_r2_settings()
    return boto3.client(
        "s3",
        endpoint_url=resolved.endpoint_url,
        aws_access_key_id=resolved.access_key_id,
        aws_secret_access_key=resolved.secret_access_key,
        region_name=REGION,
        config=Config(
            signature_version=SIGNATURE_VERSION,
            request_checksum_calculation=CHECKSUM_MODE,
            response_checksum_validation=CHECKSUM_MODE,
            retries={"max_attempts": DEFAULT_MAX_RETRY_ATTEMPTS, "mode": "standard"},
        ),
    )


@lru_cache(maxsize=1)
def shared_client():
    """The process-wide client, so that connections are pooled across jobs.

    boto3 clients are thread-safe once created, which is what makes one instance shared
    by every job the right default; `build_client` stays available for a test or a second
    set of credentials.
    """
    return build_client()
