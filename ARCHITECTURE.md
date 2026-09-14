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
│   │   ├── config.py                               # The only reader of backend/.env, and the derived settings.
│   │   ├── errors.py                               # Named exceptions inheriting the builtins they replace.
│   │   └── security.py                             # Session tokens, URL/path guards and YouTube URL classification.
│   ├── db/                                         # Placeholder for future persistence; empty today.
│   │   └── __init__.py                             # Explains why there is no database yet.
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
│   │       ├── web/                                # Authenticated non-YouTube download and transcript pipeline.
│   │       │   ├── __init__.py                     # Public interface of the web video download module.
│   │       │   ├── downloader.py                   # Cookie-aware yt-dlp and FFmpeg video acquisition.
│   │       │   ├── headers.py                      # Chooses which browser request headers may be replayed.
│   │       │   ├── pipeline.py                     # Download and transcript orchestration, and the shared result type.
│   │       │   ├── transcript.py                   # Caption parsing, Firecrawl lookup and ElevenLabs fallback.
│   │       │   └── README.md                       # Local companion setup and security notes.
│   │       └── youtube/                            # Downloads a YouTube video, its transcript and its top comments.
│   │           ├── __init__.py                     # Public interface of the YouTube download module.
│   │           ├── downloader.py                   # Downloads a YouTube video locally via yt-dlp.
│   │           ├── captions.py                     # Reads YouTube's own caption track via yt-dlp and parses it into timed segments.
│   │           ├── comments.py                     # Fetches a video's top comments from the YouTube Data API, ranked by likes.
│   │           ├── transcript.py                   # Transcript data model: caption segments or a wrapped ElevenLabs result.
│   │           ├── pipeline.py                     # Downloads a video, its transcript and its top comments, falling back to ElevenLabs.
│   │           └── downloads/                      # Local output folder for CLI downloads (gitignored).
│   └── tests/                                      # Automated backend companion tests.
│       ├── test_web_video_api.py                   # Loopback API authentication tests.
│       ├── test_web_video_downloader.py            # Download policy and cookie-jar tests.
│       ├── test_web_video_jobs.py                  # Job lifecycle tests.
│       ├── test_web_video_pipeline.py              # Transcript-failure and cancellation pipeline tests.
│       ├── test_web_video_security.py              # Security boundary tests.
│       ├── test_web_video_transcript.py            # Transcript parsing and precedence tests.
│       ├── test_youtube_routing.py                 # YouTube hostname classification and pipeline selection tests.
│       ├── test_youtube_job_adapter.py             # YouTube result to pipeline result mapping tests.
│       └── test_youtube_cancellation.py            # YouTube download progress and cancellation tests.
└── frontend/                                       # Frontend applications.
    └── chrome-extension/                           # Internal Manifest V3 video download extension.
        ├── public/                                 # Static files copied into the extension build.
        │   └── manifest.json                       # Chrome permissions and service-worker manifest.
        ├── src/                                    # Extension discovery, API, background and popup source.
        │   ├── api.ts                              # Typed companion HTTP client and session handling.
        │   ├── background.ts                       # Service worker: job tracking, Chrome downloads and debugger capture.
        │   ├── discovery.ts                        # Media and caption discovery injected into the active tab.
        │   ├── popup.css                           # Popup styling.
        │   ├── popup.ts                            # Popup controller: inspect, download, cancel and capture.
        │   └── types.ts                            # Shared wire types mirroring the companion API models.
        ├── tests/                                  # Extension helper unit tests.
        │   └── discovery.test.ts                   # Media classification and origin pattern tests.
        ├── package.json                            # Extension build and test dependencies.
        ├── popup.html                              # User interface entrypoint.
        ├── README.md                               # Build, load and capture instructions.
        ├── tsconfig.json                           # Strict TypeScript configuration.
        └── vite.config.ts                          # Deterministic extension bundle configuration.
```
