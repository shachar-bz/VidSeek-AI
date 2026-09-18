# Architecture

```
VidSeek-AI/
├── OPEN_TASKS.md                                   # Known gaps in the Chrome download companion and what closing each would take.
├── pytest.ini                                      # Backend test discovery and import path.
├── backend/                                        # Python backend.
│   ├── app.py                                      # ASGI entrypoint that builds the companion app.
│   ├── .env.example                                # Local companion and hosted API configuration template.
│   ├── requirements.txt                            # Python dependencies for the backend.
│   ├── requirements-dev.txt                        # Development-only backend test dependencies.
│   ├── api/                                        # The HTTP layer, and the only package that imports FastAPI.
│   │   ├── __init__.py                             # Public interface of the API layer.
│   │   ├── app.py                                  # Builds the app: state, CORS, loopback gate, error shaping and routes.
│   │   ├── dependencies.py                         # Request-scoped access to app state, and the bearer-token gate.
│   │   └── routes/                                 # One module per resource the companion exposes.
│   │       ├── __init__.py                         # Groups the route modules.
│   │       ├── auth.py                             # Signup, login, account lookup and logout for a user account.
│   │       ├── health.py                           # Liveness probe.
│   │       ├── sessions.py                         # Issues short-lived extension session tokens.
│   │       └── video_jobs.py                       # Video job create, poll, download-complete, capture and cancel.
│   ├── conversation_tools/                         # Pydantic AI tools the conversational agent calls while talking about a video.
│   │   ├── __init__.py                             # Public interface of the conversation tools package.
│   │   ├── deps.py                                 # ConversationDeps: per-run state injected into every tool's RunContext.
│   │   ├── get_chapter_context/                    # Tool that reads one whole chapter of the current video.
│   │   │   ├── __init__.py                         # Public interface of the get_chapter_context tool.
│   │   │   ├── result.py                           # ChapterContext and ChapterMemory: a chapter as the agent receives it.
│   │   │   └── tool.py                             # Reads the chapter and its memories, raising when this video has no such chapter.
│   │   ├── get_memory_context/                     # Tool that reads one memory with the memories around it in its chapter.
│   │   │   ├── __init__.py                         # Public interface of the get_memory_context tool.
│   │   │   ├── result.py                           # MemoryContext, ContextMemory and ChapterBoundary: the window as the agent receives it.
│   │   │   └── tool.py                             # Reads the target and its neighbours, clamping the range and reporting each clipped side.
│   │   ├── get_video_info/                         # Tool that looks up the current video's metadata via ctx.deps.video_id.
│   │   │   ├── __init__.py                         # Public interface of the get_video_info tool.
│   │   │   └── tool.py                             # VideoMetadata model and the get_video_info tool function.
│   │   └── memories_semantic_search/               # Tool that finds the current video's moments closest in meaning to a query.
│   │       ├── __init__.py                         # Public interface of the memories_semantic_search tool.
│   │       ├── result.py                           # MemorySearchHit: one matched moment as the agent receives it.
│   │       └── tool.py                             # Embeds the query and returns the five nearest memories.
│   ├── schemas/                                    # The Pydantic contract shared with the Chrome extension.
│   │   ├── __init__.py                             # Public interface of the schema layer.
│   │   ├── auth.py                                 # Signup, login and account-info request/response models.
│   │   ├── browser.py                              # Cookies, headers and the media and caption sources found in a tab.
│   │   └── video_jobs.py                           # Job request, lifecycle enums and the response the extension polls.
│   ├── core/                                       # Cross-cutting foundations, depending on nothing above them.
│   │   ├── __init__.py                             # Public interface of the core layer.
│   │   ├── auth.py                                 # Password hashing and the bearer tokens a logged-in user carries.
│   │   ├── captions.py                              # Shared CaptionSegment type and generic WebVTT/SRT/TTML parsing.
│   │   ├── config.py                               # The only reader of backend/.env, and the derived settings.
│   │   ├── errors.py                               # Named exceptions inheriting the builtins they replace.
│   │   └── security.py                             # Session tokens, URL/path guards and YouTube URL classification.
│   ├── storage/                                    # Where a video's bytes and its records are kept.
│   │   ├── __init__.py                             # What the storage layer holds, split between Blob Storage and PostgreSQL.
│   │   ├── transcript_store.py                     # Saves and loads a video's normalized transcript as JSON under the download root.
│   │   ├── blob/                                   # Video files stored in an Azure Blob Storage container.
│   │   │   ├── __init__.py                         # Public interface of the Azure Blob Storage video module.
│   │   │   ├── settings.py                         # Reads the storage connection string and container from the environment.
│   │   │   ├── client.py                           # Builds the Blob Storage client the container is addressed through.
│   │   │   └── video_storage.py                    # Uploads, fetches, links and deletes the video blobs in the container.
│   │   └── postgres/                               # Video metadata, transcripts and comments in Azure Database for PostgreSQL.
│   │       ├── __init__.py                         # Public interface of the Azure Database for PostgreSQL module.
│   │       ├── settings.py                         # Reads the database connection URL from the environment.
│   │       ├── connection.py                       # Builds the connection pool, and reads a timestamp column back as text.
│   │       ├── migrate.py                          # Applies the migrations in order, once each, recording them as it goes.
│   │       ├── users.py                            # Reads and writes the users table accounts sign in through.
│   │       ├── video_records.py                    # Reads and writes the videos table, keyed on the blob it describes.
│   │       ├── transcript_segments.py              # Reads and writes a video's transcript as timed segment rows.
│   │       ├── comments.py                         # Reads and writes a YouTube video's top comments.
│   │       ├── memories.py                         # Reads one memory of a video, and a run of memories inside one chapter.
│   │       ├── chapters.py                         # Reads one chapter with the memories grouped into it, and a chapter's neighbours.
│   │       ├── chapter_embeddings.py               # Reads a video's chapters and writes their embedding vectors.
│   │       ├── memory_embeddings.py                # Writes a video's memory embeddings and searches them by vector distance.
│   │       └── migrations/                         # SQL applied by the runner, in filename order.
│   │           ├── 0001_extensions.sql             # Enables pgcrypto and pgvector.
│   │           ├── 0002_videos.sql                 # Creates the videos table, its indexes and its updated_at trigger.
│   │           ├── 0003_transcript_segments.sql    # Creates the transcript_segments table linked to a video.
│   │           ├── 0004_comments.sql               # Creates the comments table linked to a video.
│   │           ├── 0005_chapters.sql               # Creates the chapters table linked to a video.
│   │           ├── 0006_memories.sql               # Creates the memories table linked to a video and a chapter.
│   │           ├── 0007_embeddings.sql             # Creates the memory_embeddings and chapter_embeddings tables.
│   │           ├── 0008_users.sql                  # Creates the users table, its email index and its updated_at trigger.
│   │           ├── 0009_videos_user_id.sql         # Adds videos.user_id, linking a video to the account that requested it.
│   │           ├── 0010_memory_embeddings_video_chapter.sql  # Adds memory_embeddings.video_id/chapter_id and fixes its vector dimension.
│   │           └── 0011_chapter_embeddings_video_times.sql  # Adds video_id/start/end to chapter_embeddings and fixes its vector dimension.
│   ├── services/                                   # Business logic, grouped by domain; imports no web framework.
│   │   ├── __init__.py                             # Public interface of the service layer.
│   │   ├── transcription/                          # Speech-to-text services.
│   │   │   ├── __init__.py                         # Groups the transcription services.
│   │   │   ├── elevenlabs/                         # Speech transcription of a video file in one hosted call.
│   │   │   │   ├── __init__.py                     # Public interface of the ElevenLabs transcription module.
│   │   │   │   ├── transcript.py                   # Transcript data model: words, audio events and speakers.
│   │   │   │   └── transcriber.py                  # Transcribes a video via the ElevenLabs Scribe v2 API.
│   │   │   └── openai_pipeline/                    # OpenAI transcription plus local word alignment, grouped together.
│   │   │       ├── __init__.py                     # Groups the transcription, alignment and combined modules.
│   │   │       ├── transcription/                  # Speech transcription over a video file.
│   │   │       │   ├── __init__.py                 # Public interface of the OpenAI transcription module.
│   │   │       │   ├── audio_extractor.py          # Extracts, probes and cuts a video's audio as 16 kHz mono MP3 via ffmpeg.
│   │   │       │   ├── chunk_planner.py            # Plans split points in silence for audio too long for one request.
│   │   │       │   ├── transcriber.py              # Transcribes audio through OpenAI's gpt-transcribe model.
│   │   │       │   └── transcript.py               # Transcript data model shared by the transcription module.
│   │   │       ├── word_alignment/                 # Word-level timestamps for a transcript, aligned locally.
│   │   │       │   ├── __init__.py                 # Public interface of the word alignment module.
│   │   │       │   ├── aligner.py                  # Times each word against the audio using torchaudio's MMS forced aligner.
│   │   │       │   ├── audio_loader.py             # Decodes a media file to 16 kHz mono float samples via ffmpeg.
│   │   │       │   └── text_normalizer.py          # Romanizes mixed Hebrew/English text and spells out digits for the aligner.
│   │   │       └── word_timed/                     # Transcription and word alignment run together as one pipeline.
│   │   │           ├── __init__.py                 # Public interface of the word-timed transcription pipeline.
│   │   │           └── transcription_aligner.py    # Transcribes a video and fills each chunk's words in by alignment.
│   │   ├── forced_alignment/                       # Times an already-known transcript against a video via ElevenLabs' hosted forced aligner.
│   │   │   ├── __init__.py                         # Public interface of the forced alignment module.
│   │   │   ├── aligner.py                          # Aligns supplied text to a video's audio via the ElevenLabs forced-alignment API.
│   │   │   ├── language.py                         # Checks whether a transcript's text is English before it is aligned.
│   │   │   └── transcript.py                       # Forced alignment data model: aligned words and the whole result.
│   │   ├── transcripts/                            # The normalized timestamped transcript every source is converted into.
│   │   │   ├── __init__.py                         # Public interface of the transcript normalization package.
│   │   │   ├── transcript.py                       # Normalized transcript data model: ordered segments and their timing fidelity.
│   │   │   ├── normalizer.py                       # Gathers a source's timed words or caption cues into readable segments.
│   │   │   └── formatting.py                       # Renders segments as the `[MM:SS-MM:SS] text` transcript.
│   │   ├── embeddings/                             # Shared sentence-transformers embedding model, loaded once per process.
│   │   │   ├── __init__.py                         # Public interface of the shared embeddings module.
│   │   │   ├── model.py                            # Loads and caches the all-MiniLM-L6-v2 model; embeds text into vectors.
│   │   │   ├── chapter_embedding/                  # Embeds a video's chapters and stores the vectors in chapter_embeddings.
│   │   │   │   ├── __init__.py                     # Public interface of the chapter embedding pipeline.
│   │   │   │   ├── text.py                         # Renders a chapter's title and summary as the text passed to embed_text.
│   │   │   │   └── pipeline.py                     # Reads a video's chapters, embeds each and writes the vectors back.
│   │   │   └── memory_embedding/                   # Embeds a video's memories and stores the vectors in memory_embeddings.
│   │   │       ├── __init__.py                     # Public interface of the memory embedding pipeline.
│   │   │       ├── text.py                         # Renders a memory's chapter title and summary as embeddable text.
│   │   │       └── pipeline.py                     # Reads a video's memories, embeds each one and stores the result.
│   │   ├── shot_detection/                         # Shot boundary detection services.
│   │   │   ├── __init__.py                         # Groups the shot detection services.
│   │   │   ├── omni/                               # Shot boundary detection over a video file, on a GPU.
│   │   │   │   ├── __init__.py                     # Public interface of the shot detection module.
│   │   │   │   ├── shot_detector.py                # Detects each shot's frame range and timecode using OmniShotCut.
│   │   │   │   └── video_decoder.py                # Decodes a video into RGB frames via ffmpeg and reads its frame rate.
│   │   │   └── pyscenedetect/                      # Shot boundary detection over a video file, without a GPU.
│   │   │       ├── __init__.py                     # Public interface of the PySceneDetect shot detection module.
│   │   │       └── shot_detector.py                # Detects each shot's frame range and timecode using PySceneDetect.
│   │   └── video_download/                         # Video acquisition, one package per source, plus shared orchestration.
│   │       ├── __init__.py                         # Groups the download services.
│   │       ├── jobs.py                             # Single-worker job lifecycle, cancellation and pipeline routing.
│   │       ├── youtube_job.py                      # Adapts a YouTube result into the shared pipeline result shape.
│   │       ├── video_upload.py                     # Uploads a finished job's video to the Blob Storage container.
│   │       ├── video_record.py                     # Records a finished job's video and transcript in PostgreSQL.
│   │       ├── web/                                # Authenticated non-YouTube download and transcript pipeline.
│   │       │   ├── __init__.py                     # Public interface of the web video download module.
│   │       │   ├── downloader.py                   # Cookie-aware yt-dlp and FFmpeg video acquisition.
│   │       │   ├── headers.py                      # Chooses which browser request headers may be replayed.
│   │       │   ├── pipeline.py                     # Download and transcript orchestration, and the shared result type.
│   │       │   ├── transcript.py                   # Caption parsing, Firecrawl lookup, forced alignment and ElevenLabs fallback.
│   │       │   └── README.md                       # Local companion setup and security notes.
│   │       └── youtube/                            # Downloads a YouTube video, its transcript and its top comments.
│   │           ├── __init__.py                     # Public interface of the YouTube download module.
│   │           ├── downloader.py                   # Downloads a YouTube video locally via yt-dlp.
│   │           ├── captions.py                     # Reads YouTube's own caption track via yt-dlp and parses it into timed segments.
│   │           ├── comments.py                     # Fetches a video's top comments from the YouTube Data API, ranked by likes.
│   │           ├── transcript.py                   # Transcript data model: caption segments or a wrapped ElevenLabs result.
│   │           ├── pipeline.py                     # Downloads a video, its transcript and its top comments, falling back to ElevenLabs.
│   │           └── downloads/                      # Local output folder for CLI downloads (gitignored).
│   ├── semantic_segmentation/                       # What a transcript becomes once transcription is done.
│   │   ├── __init__.py                             # Public interface of the semantic segmentation package.
│   │   ├── chapters/                               # Pipeline stage three: semantic memories grouped into higher-level chapters by an LLM.
│   │   │   ├── __init__.py                         # Public interface of the chapter grouping stage.
│   │   │   ├── prompt.py                           # The grouping instruction sent to the model, as a docstring.
│   │   │   ├── memory_ids.py                       # Names each memory `memory_N` and renders the summaries and resolves those IDs.
│   │   │   ├── boundaries.py                       # Pydantic structured-output schema of the model's response.
│   │   │   ├── validation.py                       # Checks the returned boundaries partition the memories exactly once.
│   │   │   ├── chapter.py                          # Chapter data model, deriving its times from the original memories.
│   │   │   └── grouper.py                          # Runs the stage: renders, requests, validates and builds the chapters.
│   │   └── memories/                               # Pipeline stage two: a transcript divided into semantic memories by an LLM.
│   │       ├── __init__.py                         # Public interface of the memory creation stage.
│   │       ├── prompt.py                           # The segmentation instruction sent to the model, as a docstring.
│   │       ├── segment_ids.py                      # Names each transcript segment `segment_N` and renders and resolves those IDs.
│   │       ├── boundaries.py                       # Pydantic structured-output schema of the model's response.
│   │       ├── validation.py                       # Checks the returned boundaries partition the transcript exactly once.
│   │       ├── memory.py                           # Memory data model, deriving its times and text from the original segments.
│   │       └── segmenter.py                        # Runs the stage: renders, requests, validates and builds the memories.
│   └── tests/                                      # Automated backend companion tests.
│       ├── conftest.py                             # Keeps the developer's download root and backend/.env out of the test run.
│       ├── test_transcript_normalization.py        # Transcript format, segment timing and transcript store tests.
│       ├── test_memory_segmentation.py             # Segment ID rendering, boundary validation and memory construction tests.
│       ├── test_chapter_grouping.py                # Memory ID rendering, boundary validation and chapter construction tests.
│       ├── test_web_video_api.py                   # Loopback API authentication tests.
│       ├── test_health.py                          # /health download-root reporting tests.
│       ├── test_auth_routes.py                     # Signup, login, /v1/auth/me and logout route tests.
│       ├── test_web_video_downloader.py            # Download policy and cookie-jar tests.
│       ├── test_web_video_jobs.py                  # Job lifecycle tests.
│       ├── test_web_video_pipeline.py              # Transcript precedence, transcript-failure and cancellation pipeline tests.
│       ├── test_web_video_security.py              # Security boundary tests.
│       ├── test_core_auth.py                       # Password hashing and user auth token registry tests.
│       ├── test_web_video_transcript.py            # Transcript parsing and precedence tests.
│       ├── test_youtube_routing.py                 # YouTube hostname classification and pipeline selection tests.
│       ├── test_youtube_job_adapter.py             # YouTube result to pipeline result mapping tests.
│       ├── test_youtube_cancellation.py            # YouTube download progress and cancellation tests.
│       ├── test_youtube_transcript_fallback.py     # YouTube untimed-caption-to-ElevenLabs fallback tests.
│       ├── fake_postgres.py                        # A connection pool that records SQL instead of reaching a database.
│       ├── test_blob_video_storage.py              # Blob Storage settings, blob name and container operation tests.
│       ├── test_video_upload.py                    # Job video upload, progress and skip-when-unconfigured tests.
│       ├── test_postgres_video_records.py          # Database settings and videos table read/write tests.
│       ├── test_postgres_users.py                  # Users table read/write and duplicate-email tests.
│       ├── test_postgres_transcript_segments.py    # Transcript segment batching and replacement tests.
│       ├── test_postgres_comments.py               # Comment batching and replacement tests.
│       ├── test_postgres_memory_embeddings.py      # Memory embedding read/write, replacement and nearest-memory search tests.
│       ├── test_postgres_chapters.py               # Chapter and memory read, neighbour lookup, video scoping and empty chapter tests.
│       ├── test_postgres_memories.py               # Single memory read, video scoping and chapter window range tests.
│       ├── test_memories_semantic_search.py       # Query embedding, video scoping and hit mapping tests for the search tool.
│       ├── test_get_chapter_context.py             # Video scoping, memory ordering and missing chapter tests for the chapter tool.
│       ├── test_get_memory_context.py              # Window, boundary, range clamping and unknown id tests for the memory context tool.
│       ├── test_memory_embedding.py                # Embedding text rendering and embed-and-store pipeline tests.
│       ├── test_postgres_migrations.py             # Migration ordering, one-time application and failure reporting tests.
│       └── test_video_record.py                    # Job video and transcript recording tests.
├── chrome-extension/                               # Internal Manifest V3 video download extension.
    ├── public/                                     # Static files copied into the extension build.
    │   └── manifest.json                           # Chrome permissions and service-worker manifest.
    ├── src/                                        # Extension discovery, API, background and popup source.
    │   ├── api.ts                                  # Typed companion HTTP client, session handling, and signup/login/me/logout.
    │   ├── background.ts                           # Service worker: job tracking, Chrome downloads and debugger capture.
    │   ├── discovery.ts                            # Media and caption discovery injected into the active tab.
    │   ├── popup.css                               # Popup styling.
    │   ├── popup.ts                                # Popup controller: login/signup, inspect, download, cancel and capture.
    │   ├── texture.ts                              # Generates the ASCII field drawn behind the login screen.
    │   └── types.ts                                # Shared wire types mirroring the companion API models.
    ├── tests/                                      # Extension helper unit tests.
    │   ├── discovery.test.ts                       # Media classification and origin pattern tests.
    │   └── texture.test.ts                         # Login backdrop grid, alphabet and row density tests.
    ├── package.json                                # Extension build and test dependencies.
    ├── popup.html                                  # User interface entrypoint.
    ├── README.md                                   # Build, load and capture instructions.
    ├── tsconfig.json                               # Strict TypeScript configuration.
    └── vite.config.ts                              # Deterministic extension bundle configuration.
└── frontend/                                       # Reserved for future web frontend applications.
    └── README.md                                   # Notes that this folder is a placeholder.
```
