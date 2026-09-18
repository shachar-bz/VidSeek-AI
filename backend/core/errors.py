"""The backend's named exceptions.

Each one inherits from the builtin that was raised in its place before these existed, so
every `except ValueError` and `except KeyError` already written against the old behavior
keeps working and the routes can be narrowed one at a time.

Catching a bare builtin across a package boundary is really a blanket catch of anything a
transitive dependency happens to raise, and it already misfires in one place the routes
document.
"""


class JobNotFoundError(KeyError):
    """No job with the requested id exists."""


class InvalidJobInputError(ValueError):
    """The request described work that can never be performed as written."""


class JobStateConflictError(ValueError):
    """The job exists but is not in a state where this operation is meaningful."""


class MissingDependencyError(RuntimeError):
    """A required external binary is not installed, so no job can ever succeed."""


class UnsupportedMediaError(RuntimeError):
    """The URL points to media deliberately outside the v1 scope."""


class EmailAlreadyRegisteredError(ValueError):
    """An account already exists for this email address."""

    def __init__(self, email: str):
        super().__init__(f"An account already exists for {email}")
        self.email = email


class VideoNotFoundError(KeyError):
    """No video with the requested id exists."""


class ChapterNotFoundError(KeyError):
    """The video being talked about has no chapter with the requested id.

    Raised for a chapter that exists under a different video as well as for one that exists
    nowhere: which of the two it was is not something a conversation about one video is
    told.
    """
