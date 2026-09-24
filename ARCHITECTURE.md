# Architecture

A directory-level map: what each package is for, what it may import, and where new
code goes. It is not a file index — use Glob and Grep to find files and definitions.

```
VidSeek-AI/
├── backend/                                # Python backend; its ASGI entry point sits at this level.
│   ├── api/                                # The HTTP layer, the only package that imports FastAPI, and where the app is assembled.
│   │   └── routes/                         # One module per resource the companion exposes.
│   ├── video_agent/                        # The conversational agent that talks about a video: prompt, model runner, citations, stop control.
│   │   └── tools/                          # Pydantic AI tools the agent calls; one directory per tool.
│   │       ├── get_chapter_context/        # Reads one whole chapter of the current video.
│   │       ├── get_memory_context/         # Reads one memory with the memories around it in its chapter.
│   │       ├── get_video_info/             # Looks up the current video's metadata.
│   │       ├── get_video_outline/          # Lists the current video's chapters without their contents.
│   │       └── memories_semantic_search/   # Finds the current video's moments closest in meaning to a query.
│   ├── schemas/                            # The Pydantic contract shared with the Chrome extension and the website.
│   ├── core/                               # Cross-cutting foundations: config, errors, auth primitives, security.
│   ├── storage/                            # Where a video's bytes and its records are kept.
│   │   ├── blob/                           # Video files stored in an Azure Blob Storage container.
│   │   └── postgres/                       # Video metadata, transcripts, comments, memories, chapters and embeddings.
│   │       └── migrations/                 # SQL applied by the runner, in filename order.
│   ├── services/                           # Business logic, grouped by domain; a one-module domain sits directly here.
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
│   │   │   ├── memory_embedding/           # Embeds a video's memories and stores the vectors.
│   │   │   ├── image_embedding/            # SigLIP 2: frame vectors and the text queries scored against them.
│   │   │   └── multilingual_text_embedding/ # multilingual-e5-small, for on-screen text.
│   │   ├── visual_indexing/                # Builds one video's visual index from its local file; no database.
│   │   │   ├── sampling/                   # The ffmpeg decode pass (one shrunken frame every two seconds), and keyframes at full size.
│   │   │   ├── segments/                   # Content-change segmentation and keyframe choice.
│   │   │   └── ocr/                        # The OCR engine interface and the text a keyframe keeps.
│   │   │       └── surya/                  # Surya 2, run in a worker process of its own Python environment.
│   │   ├── visual_search/                  # Finds a video's moments matching a text query, placed in segment and chapter.
│   │   ├── video_frames/                   # Frames of a stored video, extracted on demand from Blob Storage.
│   │   ├── shot_detection/                 # Shot boundary detection services, plus the script that compares them.
│   │   │   ├── omni/                       # Shot boundary detection on a GPU (OmniShotCut).
│   │   │   ├── pyscenedetect/              # Shot boundary detection without a GPU.
│   │   │   ├── transnetv2/                 # Shot boundary detection with TransNetV2, CPU or GPU.
│   │   │   └── results/                    # The comparison's generated report, JSON and frame images; data, never imported.
│   │   └── video_download/                 # Video acquisition, one package per source; the job manager and shared record and upload steps sit at this level.
│   │       ├── web/                        # Authenticated non-YouTube download and transcript pipeline.
│   │       └── youtube/                    # Downloads a YouTube video, its transcript and its top comments.
│   ├── semantic_segmentation/              # What a transcript becomes once transcription is done.
│   │   ├── memories/                       # Stage two: a transcript divided into semantic memories by an LLM.
│   │   └── chapters/                       # Stage three: memories grouped into higher-level chapters by an LLM.
│   ├── download_pipeline/                  # The order one video runs through: download, store, segment, embed, and visual indexing beside them.
│   └── tests/                              # Automated backend companion tests.
├── chrome-extension/                       # Internal Manifest V3 video download extension.
│   ├── public/                             # Static files copied into the extension build.
│   ├── src/                                # Background worker, popup, page and frame discovery, and the companion API client.
│   └── tests/                              # Extension helper unit tests.
└── frontend/                               # The VidSeek website: a React + Vite single-page app.
    ├── src/                                # The app root, the route table and the directories below.
    │   ├── api/                            # The wire contract, and the one place fetch is called.
    │   ├── auth/                           # Signed-in account state and the route guards built on it.
    │   ├── components/
    │   │   └── ui/                         # Presentational building blocks with no knowledge of the app.
    │   ├── layout/                         # The shell every signed-in page renders inside.
    │   ├── pages/                          # One directory per page; helpers two pages share sit at this level.
    │   │   ├── account/                    # The signed-in user's display name and password.
    │   │   ├── auth/                       # Sign-in and sign-up.
    │   │   ├── library/                    # The user's videos.
    │   │   ├── setup/                      # How to install the extension and companion.
    │   │   └── video/                      # One video: player, transcript, outline and its conversations.
    │   ├── styles/                         # Global CSS, imported once at the browser entry.
    │   └── assets/                         # Images bundled by Vite.
    └── tests/                              # Website unit tests, run by Vitest under jsdom.
```

## Where to start

* The backend runs from the ASGI app at `backend/app.py`, which only calls `create_app` in
  `backend/api/`; everything a request depends on is wired there.
* A video's journey starts at `services/video_download/jobs.py` and runs the stages in
  `download_pipeline/`.
* The website starts at `frontend/src/main.tsx`; every URL it has is in `frontend/src/routes.ts`.
* `VISUAL_UNDERSTANDING_PLAN.md` designs the layer that answers questions about what a video
  shows; its ingestion half runs on a second executor in `jobs.py`.
* `frontend/WEBSITE_FUNCTIONALITY.md` specifies what the website does,
  `backend/services/video_download/WEB_DISCOVERY.md` how authenticated pages are searched for
  video, and `OPEN_TASKS.md` the known gaps left open on purpose.

## Rules

The rules bind production code. Tests (`backend/tests/`, `frontend/tests/`,
`chrome-extension/tests/`) may import across them to build fixtures and fakes.

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
* `services/video_frames/` is used only at query time. Visual indexing reads the local copy
  of a video while it exists and never goes through Blob Storage; nothing reads frames back
  from anywhere but the stored video, because no frame is ever stored.
* `services/visual_indexing/` touches no database; `download_pipeline/visual_indexing.py`
  stores what it builds and is the one stage that owns, and deletes, the local video file.
* `services/visual_indexing/ocr/surya/worker.py` runs in Surya's own Python environment, not
  the backend's, and imports nothing from `backend`. The backend reaches Surya only through
  that worker's stdin and stdout (`ocr/surya/engine.py`), and never imports `surya`; its
  dependencies are in `ocr/surya/requirements.txt`, not in `backend/requirements.txt`.
* `frontend/src/components/ui/` imports nothing from the rest of the app.
* A page never imports another page; what two pages share goes in `frontend/src/pages/`
  itself, or lower, in `auth/`, `layout/` or `components/ui/`.
* The website adds no way to put a video into the system — the extension remains the only
  one — which is why nothing under `frontend/` calls `/v1/video-jobs`.
