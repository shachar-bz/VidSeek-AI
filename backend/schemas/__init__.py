"""The Pydantic contract shared with the Chrome extension and the website.

These models are both the wire format and the input types the services work with, and they
are deliberately not duplicated into a second set of service-layer dataclasses: there is
one producer and one consumer per model, the clients mirror them field for field, and a
parallel hierarchy would add converters that express an identity mapping.

Which module serves which client:

- `browser`, `video_jobs`     — the extension's half: discovery, job creation, job polling.
  `chrome-extension/src/types.ts` mirrors these.
- `auth`                      — both, since one sign-in covers both surfaces.
- `account`, `library`, `videos`, `conversations`, `readiness` — the website's half.
  `frontend/src/api/types.ts` mirrors these.

`readiness` is the one module that is more than a shape: the stage a video is shown in is
derived from a job row and from what the video has produced, and two endpoints have to
derive it identically, so the rule lives there beside the enum it produces.

Depending on pydantic is not the same as depending on the web framework — the rule this
layout enforces is that FastAPI stays out of `backend.services`, not that Pydantic does.
Nothing here imports FastAPI, and nothing here reaches a database: a model in this package
describes what crosses the wire, and assembling one from several tables is the API layer's
work.
"""
