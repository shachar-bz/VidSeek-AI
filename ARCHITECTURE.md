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
│   │       ├── health.py                           # Liveness probe.
│   │       ├── sessions.py                         # Issues short-lived extension session tokens.
│   │       └── video_jobs.py                       # Video job create, poll, download-complete, capture and cancel.
│   ├── schemas/                                    # The Pydantic contract shared with the Chrome extension.
│   │   ├── __init__.py                             # Public interface of the schema layer.
│   │   ├── browser.py                              # Cookies, headers and the media and caption sources found in a tab.
│   │   └── video_jobs.py                           # Job request, lifecycle enums and the response the extension polls.
│   ├── core/                                       # Cross-cutting foundations, depending on nothing above them.
│   │   ├── __init__.py                             # Public interface of the core layer.
│   │   ├── captions.py                              # Shared CaptionSegment type and generic WebVTT/SRT/TTML parsing.
│   │   ├── config.py                               # The only reader of backend/.env, and the derived settings.
│   │   ├── errors.py                               # Named exceptions inheriting the builtins they replace.
│   │   └── security.py                             # Session tokens, URL/path guards and YouTube URL classification.
│   ├── storage/                                    # Where a video's bytes and its records are kept.
│   │   ├── __init__.py                             # What the storage layer holds today, and what Supabase will add to it.
│   │   ├── transcript_store.py                     # Saves and loads a video's normalized transcript as JSON under the download root.
│   │   ├── r2/                                     # Video files stored in a Cloudflare R2 bucket.
│   │   │   ├── __init__.py                         # Public interface of the R2 video storage module.
│   │   │   ├── settings.py                         # Reads the R2 credentials, endpoint and bucket from the environment.
│   │   │   ├── client.py                           # Builds the S3-compatible boto3 client R2 is addressed through.
│   │   │   └── video_storage.py                    # Uploads, fetches, links and deletes the video objects in the bucket.
│   │   └── supabase/                               # Video metadata and transcripts in a Supabase Postgres database.
│   │       ├── __init__.py                         # Public interface of the Supabase database module.
│   │       ├── settings.py                         # Reads the Supabase project URL and API key from the environment.
│   │       ├── client.py                           # Builds the Supabase client the tables are reached through.
│   │       ├── video_records.py                    # Reads and writes the videos table, keyed on the R2 object it describes.
│   │       ├── transcript_segments.py              # Reads and writes a video's transcript as timed segment rows.
│   │       └── migrations/                         # SQL applied by hand to the Supabase project, in order.
│   │           ├── 0001_videos.sql                 # Creates the videos table, its indexes and its row level security.
│   │           └── 0002_transcript_segments.sql    # Creates the transcript_segments table linked to a video.
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
│   │       ├── video_upload.py                     # Uploads a finished job's video to the R2 bucket.
│   │       ├── video_record.py                     # Records a finished job's video and transcript in Supabase.
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
│   ├── semantic_processing/                        # What a transcript becomes once transcription is done.
│   │   ├── __init__.py                             # Public interface of the semantic processing package.
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
│       ├── test_web_video_api.py                   # Loopback API authentication tests.
│       ├── test_web_video_downloader.py            # Download policy and cookie-jar tests.
│       ├── test_web_video_jobs.py                  # Job lifecycle tests.
│       ├── test_web_video_pipeline.py              # Transcript precedence, transcript-failure and cancellation pipeline tests.
│       ├── test_web_video_security.py              # Security boundary tests.
│       ├── test_web_video_transcript.py            # Transcript parsing and precedence tests.
│       ├── test_youtube_routing.py                 # YouTube hostname classification and pipeline selection tests.
│       ├── test_youtube_job_adapter.py             # YouTube result to pipeline result mapping tests.
│       ├── test_youtube_cancellation.py            # YouTube download progress and cancellation tests.
│       ├── test_youtube_transcript_fallback.py     # YouTube untimed-caption-to-ElevenLabs fallback tests.
│       ├── test_r2_video_storage.py                # R2 settings, object key and bucket operation tests.
│       ├── test_video_upload.py                    # Job video upload, progress and skip-when-unconfigured tests.
│       ├── test_supabase_video_records.py          # Supabase settings and videos table read/write tests.
│       ├── test_supabase_transcript_segments.py    # Transcript segment batching, paging and replacement tests.
│       └── test_video_record.py                    # Job video and transcript recording tests.
├── chrome-extension/                               # Internal Manifest V3 video download extension.
    ├── public/                                     # Static files copied into the extension build.
    │   └── manifest.json                           # Chrome permissions and service-worker manifest.
    ├── src/                                        # Extension discovery, API, background and popup source.
    │   ├── api.ts                                  # Typed companion HTTP client and session handling.
    │   ├── background.ts                           # Service worker: job tracking, Chrome downloads and debugger capture.
    │   ├── discovery.ts                            # Media and caption discovery injected into the active tab.
    │   ├── popup.css                               # Popup styling.
    │   ├── popup.ts                                # Popup controller: inspect, download, cancel and capture.
    │   └── types.ts                                # Shared wire types mirroring the companion API models.
    ├── tests/                                      # Extension helper unit tests.
    │   └── discovery.test.ts                       # Media classification and origin pattern tests.
    ├── package.json                                # Extension build and test dependencies.
    ├── popup.html                                  # User interface entrypoint.
    ├── README.md                                   # Build, load and capture instructions.
    ├── tsconfig.json                               # Strict TypeScript configuration.
    └── vite.config.ts                              # Deterministic extension bundle configuration.
└── frontend/                                       # Reserved for future web frontend applications.
    └── README.md                                   # Notes that this folder is a placeholder.
```
