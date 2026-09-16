"""Reads the Azure Blob Storage connection string and container out of `backend/.env`.

Azure hands out one connection string that carries the account name, the account key and
the endpoint together, so there is a single credential to configure rather than the four
values an S3 client needed. The account name and key are still pulled back out of it here,
because signing a SAS URL needs them individually and the SDK does not expose them in a
form worth depending on.

Nothing is read at import time. A machine with no storage account still runs every other
service, and only a call that actually touches the container fails, with a message naming
the variable to set.
"""

from dataclasses import dataclass

from backend.core import config

CONNECTION_STRING_NAME = "AZURE_STORAGE_CONNECTION_STRING"
CONTAINER_NAME = "AZURE_STORAGE_CONTAINER_NAME"

# The two fields this code reads out of the connection string, keyed by the lower-cased
# name it is looked up under and spelled the way Azure writes it for the error message.
# Matching case-insensitively is what the SDK does too, so a string copied from any of
# Azure's pages works whichever casing it happens to use.
REQUIRED_FIELDS = {"accountname": "AccountName", "accountkey": "AccountKey"}


@dataclass(frozen=True)
class BlobSettings:
    """Everything needed to address one Blob Storage container."""

    connection_string: str
    container: str

    # Parsed out of the connection string, not configured separately. Both are needed to
    # sign a download URL; neither is needed to upload, which the connection string alone
    # covers.
    account_name: str
    account_key: str


def load_blob_settings() -> BlobSettings:
    """Collect the Blob Storage settings, failing with the name of whatever is missing."""
    connection_string = config.require(CONNECTION_STRING_NAME)
    fields = _connection_string_fields(connection_string)
    missing = [spelling for key, spelling in REQUIRED_FIELDS.items() if not fields.get(key)]
    if missing:
        raise RuntimeError(
            f"{CONNECTION_STRING_NAME} is missing {' and '.join(missing)}; use the full "
            "connection string from the storage account's Access keys page"
        )
    return BlobSettings(
        connection_string=connection_string.strip(),
        container=config.require(CONTAINER_NAME),
        account_name=fields["accountname"],
        account_key=fields["accountkey"],
    )


def is_blob_configured() -> bool:
    """Whether there is a container to talk to at all.

    A job asks this before uploading, so that a checkout with no storage account still
    downloads and transcribes videos instead of failing at the last step. Half a
    configuration counts as none: the missing half is then reported by `load_blob_settings`,
    which names it.
    """
    return all(config.get(name) for name in (CONNECTION_STRING_NAME, CONTAINER_NAME))


def _connection_string_fields(connection_string: str) -> dict[str, str]:
    """The `key=value;` pairs of a connection string, keyed in lower case.

    Split on the first `=` of each pair only: an account key is base64 and routinely ends
    in one or two `=` of padding, which a split on every separator would tear off.
    """
    fields: dict[str, str] = {}
    for pair in connection_string.strip().split(";"):
        if "=" not in pair:
            continue
        name, _, value = pair.partition("=")
        fields[name.strip().lower()] = value.strip()
    return fields
