"""Reads the Cloudflare R2 credentials, endpoint and bucket out of `backend/.env`.

Cloudflare names the two halves of an R2 API token "Access Key ID" and "Secret Access
Key". The secret is read from `R2_ACCESS_KEY` here, which is what this project's `.env`
calls it; the more conventional `R2_SECRET_ACCESS_KEY` is accepted as well so that a
value copied straight out of Cloudflare's own snippet also works.

Nothing is read at import time. A machine with no R2 credentials still runs every other
service, and only a call that actually touches the bucket fails, with a message naming
the variable to set.
"""

from dataclasses import dataclass
from urllib.parse import urlparse

from backend.core import config

ACCESS_KEY_ID_NAME = "R2_ACCESS_KEY_ID"
SECRET_ACCESS_KEY_NAME = "R2_ACCESS_KEY"
ALTERNATE_SECRET_ACCESS_KEY_NAME = "R2_SECRET_ACCESS_KEY"
ENDPOINT_URL_NAME = "R2_ENDPOINT_URL"
BUCKET_NAME = "R2_BUCKET_NAME"
PUBLIC_BASE_URL_NAME = "R2_PUBLIC_BASE_URL"

# R2 is one global namespace with no regions, but the S3 protocol requires a region in
# the request signature, and "auto" is the value Cloudflare documents for it.
REGION = "auto"


@dataclass(frozen=True)
class R2Settings:
    """Everything needed to address one R2 bucket over the S3 API."""

    access_key_id: str
    secret_access_key: str
    endpoint_url: str
    bucket: str
    # Set only when the bucket is served publicly, either through an r2.dev subdomain or
    # a custom domain. Without it, a stored object is reachable only through a presigned
    # URL, which is the safer default and the one this project assumes.
    public_base_url: str | None = None


def load_r2_settings() -> R2Settings:
    """Collect the R2 settings, failing with the name of whatever is missing."""
    secret_access_key = config.get(SECRET_ACCESS_KEY_NAME) or config.get(
        ALTERNATE_SECRET_ACCESS_KEY_NAME
    )
    if not secret_access_key:
        raise RuntimeError(
            f"{SECRET_ACCESS_KEY_NAME} (or {ALTERNATE_SECRET_ACCESS_KEY_NAME}) "
            f"is not set in {config.ENV_PATH} or the environment"
        )
    return R2Settings(
        access_key_id=config.require(ACCESS_KEY_ID_NAME),
        secret_access_key=secret_access_key,
        endpoint_url=_account_endpoint(config.require(ENDPOINT_URL_NAME)),
        bucket=config.require(BUCKET_NAME),
        public_base_url=(config.get(PUBLIC_BASE_URL_NAME) or "").rstrip("/") or None,
    )


def is_r2_configured() -> bool:
    """Whether there is an R2 bucket to talk to at all.

    A job asks this before uploading, so that a checkout with no R2 credentials still
    downloads and transcribes videos instead of failing at the last step. Half a
    configuration counts as none: the missing half is then reported by
    `load_r2_settings`, which names it.
    """
    return all(
        config.get(name)
        for name in (ACCESS_KEY_ID_NAME, ENDPOINT_URL_NAME, BUCKET_NAME)
    ) and bool(
        config.get(SECRET_ACCESS_KEY_NAME) or config.get(ALTERNATE_SECRET_ACCESS_KEY_NAME)
    )


def _account_endpoint(endpoint_url: str) -> str:
    """Reject a bucket-scoped endpoint, which boto3 would silently turn into a bad key.

    Cloudflare's dashboard shows both `https://<account>.r2.cloudflarestorage.com` and
    the same URL with the bucket appended. Only the first belongs here: boto3 adds the
    bucket itself, so pasting the second produces requests for `<bucket>/<bucket>/<key>`
    that fail as a missing object rather than as a misconfiguration.
    """
    trimmed = endpoint_url.strip().rstrip("/")
    path = urlparse(trimmed).path
    if path:
        raise RuntimeError(
            f"{ENDPOINT_URL_NAME} must be the account endpoint without the bucket "
            f"(drop '{path}'); the bucket belongs in {BUCKET_NAME}"
        )
    return trimmed
