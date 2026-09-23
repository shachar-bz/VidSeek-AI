# Architecture

A directory-level map: what each package is for, what it may import, and where new
code goes. It is not a file index — use Glob and Grep to find files and definitions.

```
VidSeek-AI/
├── backend/                                # Python backend.
│   ├── api/                                # The HTTP layer, and the only package that imports FastAPI.
│   │   └── routes/                         # One module per resource the companion exposes.
│   ├── video_agent/                         # The conversational agent that talks about a video.
│   │   └── tools/                          # Pydantic AI tools the agent calls; one directory per tool.
│   │       ├── get_chapter_context/        # Reads one whole chapter of the current video.
│   │       ├── get_memory_context/         # Reads one memory with the memories around it in its chapter.
│   │       ├── get_video_info/             # Looks up the current video's metadata.
│   │       ├── get_video_outline/          # Lists the current video's chapters without their contents.
│   │       └── memories_semantic_search/   # Finds the current video's moments closest in meaning to a query.
│   ├── schemas/                            # The Pydantic contract shared with the Chrome extension.
│   ├── core/                               # Cross-cutting foundations: config, errors, auth primitives, security.
│   ├── storage/                            # Where a video's bytes and its records are kept.
│   │   ├── blob/                           # Video files stored in an Azure Blob Storage container.
│   │   └── postgres/                       # Video metadata, transcripts, comments, memories, chapters and embeddings.
│   │       └── migrations/                 # SQL applied by the runner, in filename order.
│   ├── services/                           # Business logic, grouped by domain.
│   │   ├── transcription/                  # Speech-to-text services.
│   │   │   ├── elevenlabs/                 # Transcription of a video file in one hosted call.
│   │   │   └── openai_pipeline/            # OpenAI transcription plus local word alignment.
│   │   │       ├── transcription/          # Speech transcription over a video file.
│   │   │       ├── word_alignment/         # Word-level timestamps for a transcript, aligned locally.
│   │   │       └── word_timed/             # Transcription and word alignment run together as one pipeline.
│   │   ├── forced_alignment/               # Times an already-known transcript against a video via ElevenLabs' hosted forced aligner.
│   │   ├── transcripts/                    # The normalized timestamped transcript every source is converted into.
│   │   ├── embeddings/                     # Shared sentence-transformers embedding model, loaded once per process.
│   │   │   ├── chapter_embedding/          # Embeds a video's chapters and stores the vectors.
│   │   │   └── memory_embedding/           # Embeds a video's memories and stores the vectors.
│   │   ├── shot_detection/                 # Shot boundary detection services.
│   │   │   ├── omni/                       # Shot boundary detection on a GPU (OmniShotCut).
│   │   │   ├── pyscenedetect/              # Shot boundary detection without a GPU.
│   │   │   ├── transnetv2/                 # Shot boundary detection with TransNetV2, CPU or GPU.
│   │   │   └── results/                    # Generated output of the detector comparison; never imported.
│   │   └── video_download/                 # Video acquisition, one package per source, plus shared orchestration.
│   │       ├── web/                        # Authenticated non-YouTube download and transcript pipeline.
│   │       └── youtube/                    # Downloads a YouTube video, its transcript and its top comments.
│   ├── semantic_segmentation/              # What a transcript becomes once transcription is done.
│   │   ├── memories/                       # Stage two: a transcript divided into semantic memories by an LLM.
│   │   └── chapters/                       # Stage three: memories grouped into higher-level chapters by an LLM.
│   ├── download_pipeline/                  # The order one video runs through: download, store, segment, embed.
│   └── tests/                              # Automated backend companion tests.
├── chrome-extension/                       # Internal Manifest V3 video download extension.
│   ├── public/                             # Static files copied into the extension build.
│   ├── src/                                # Extension discovery, API, background and popup source.
│   └── tests/                              # Extension helper unit tests.
└── frontend/                               # The VidSeek website: a React + Vite single-page app.
    ├── src/                                # Pages, components and the API client.
    │   └── api/                            # The wire contract, and the one place fetch is called.
    └── tests/                              # Website unit tests, run by Vitest under jsdom.
```

## Rules

* `api/` is the only package that imports FastAPI.
* `services/` imports no web framework.
* `download_pipeline/` holds the order the stages run in and nothing else; every stage
  calls a service or a store rather than doing the work itself. Nothing imports it but
  `services/video_download/jobs.py`, which is where a job becomes a pipeline run.
* `core/` imports nothing from other project packages.
* `storage/` is the only path to PostgreSQL and Blob Storage.
* `schemas/` is the contract shared with the extension and the website; it depends only on
  `core/`, imports no web framework, and reaches no database. Assembling one of its models
  out of several tables is `api/`'s work, not its own.
* `video_agent/tools/` gets one directory per tool.
* `frontend/src/api/` is the only place the website calls `fetch`; a page asks it for data
  rather than building a request itself. `frontend/src/api/types.ts` mirrors
  `backend/schemas/` field for field, the same way `chrome-extension/src/types.ts` does,
  and is the only declaration of the wire format the website is written against.
* The website adds no way to put a video into the system — the extension remains the only
  one — which is why nothing under `frontend/` calls `/v1/video-jobs`.
