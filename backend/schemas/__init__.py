"""The Pydantic contract shared with the Chrome extension.

These models are both the wire format and the input types the services work with, and they
are deliberately not duplicated into a second set of service-layer dataclasses: there is
one producer and one consumer, `frontend/chrome-extension/src/types.ts` mirrors them field
for field, and a parallel hierarchy would add converters that express an identity mapping.

Depending on pydantic is not the same as depending on the web framework — the rule this
layout enforces is that FastAPI stays out of `backend.services`, not that Pydantic does.
"""
