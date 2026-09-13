# Architecture

```
VidSeek-AI/
├── pytest.ini                              # Backend test discovery and import path.
├── backend/                                # Python backend.
│   ├── app.py                              # FastAPI entrypoint for the loopback Chrome companion.
│   ├── .env.example                        # Local companion and hosted API configuration template.
│   ├── requirements.txt                    # Python dependencies for the backend.
│   ├── requirements-dev.txt                # Development-only backend test dependencies.
│   ├── ElevenLabs_transcription/           # Speech transcription of a video file.
│   │   ├── __init__.py                     # Public interface of the ElevenLabs transcription module.
│   │   ├── transcript.py                   # Transcript data model: words, audio events and speakers.
│   │   └── transcriber.py                  # Transcribes a video via the ElevenLabs Scribe v2 API.
│   ├── Omni_shot_detection/                # Shot boundary detection over a video file.
│   │   ├── __init__.py                     # Public interface of the shot detection module.
│   │   ├── shot_detector.py                # Detects each shot's frame range and timecode using OmniShotCut.
│   │   └── video_decoder.py                # Decodes a video into RGB frames via ffmpeg and reads its frame rate.
│   ├── PySceneDetect_shot_detection/       # Shot boundary detection over a video file, without a GPU.
│   │   ├── __init__.py                     # Public interface of the PySceneDetect shot detection module.
│   │   └── shot_detector.py                # Detects each shot's frame range and timecode using PySceneDetect.
│   ├── OpenAI_transcription_pipeline/      # OpenAI transcription plus local word alignment, grouped together.
│   │   ├── __init__.py                     # Groups the OpenAI transcription, alignment and pipeline modules.
│   │   ├── OpenAI_transcription/           # Speech transcription over a video file.
│   │   │   ├── __init__.py                 # Public interface of the OpenAI transcription module.
│   │   │   ├── audio_extractor.py          # Extracts, probes and cuts a video's audio as 16 kHz mono MP3 via ffmpeg.
│   │   │   ├── chunk_planner.py            # Plans split points in silence for audio too long for one request.
│   │   │   ├── transcriber.py              # Transcribes audio through OpenAI's gpt-transcribe model.
│   │   │   └── transcript.py               # Transcript data model shared by the transcription module.
│   │   ├── MMS_word_alignment/             # Word-level timestamps for a transcript, aligned locally.
│   │   │   ├── __init__.py                 # Public interface of the MMS word alignment module.
│   │   │   ├── aligner.py                  # Times each word against the audio using torchaudio's MMS forced aligner.
│   │   │   ├── audio_loader.py             # Decodes a media file to 16 kHz mono float samples via ffmpeg.
│   │   │   └── text_normalizer.py          # Romanizes mixed Hebrew/English text and spells out digits for the aligner.
│   │   └── word_timed_transcription/       # Transcription and word alignment run together as one pipeline.
│   │       ├── __init__.py                 # Public interface of the word-timed transcription pipeline.
│   │       └── transcription_aligner.py    # Transcribes a video and fills each chunk's words in by alignment.
│   ├── YouTube_download/                   # Downloads a YouTube video, its transcript and its top comments.
│   │   ├── __init__.py                     # Public interface of the YouTube download module.
│   │   ├── downloader.py                   # Downloads a YouTube video locally via yt-dlp.
│   │   ├── captions.py                     # Reads YouTube's own caption track via yt-dlp and parses it into timed segments.
│   │   ├── comments.py                     # Fetches a video's top comments from the YouTube Data API, ranked by likes.
│   │   ├── transcript.py                   # Transcript data model: caption segments or a wrapped ElevenLabs result.
│   │   ├── pipeline.py                     # Downloads a video, its transcript and its top comments, falling back to ElevenLabs.
│   │   └── downloads/                      # Local output folder for downloaded videos, transcripts and comments (gitignored).
│   ├── Web_video_download/                 # Authenticated non-YouTube download and transcript companion.
│   │   ├── __init__.py                     # Public interface of the web video download module.
│   │   ├── api.py                          # Loopback FastAPI routes and extension authentication.
│   │   ├── downloader.py                   # Cookie-aware yt-dlp and FFmpeg video acquisition.
│   │   ├── jobs.py                         # Single-worker job lifecycle and cancellation.
│   │   ├── models.py                       # Validated request, response and browser-context models.
│   │   ├── pipeline.py                     # Download and transcript orchestration.
│   │   ├── security.py                     # URL, path, header and session boundaries.
│   │   ├── transcript.py                   # Caption parsing, Firecrawl lookup and ElevenLabs fallback.
│   │   └── README.md                       # Local companion setup and security notes.
│   └── tests/                              # Automated backend companion tests.
│       ├── test_web_video_api.py           # Loopback API authentication tests.
│       ├── test_web_video_downloader.py    # Download policy and cookie-jar tests.
│       ├── test_web_video_jobs.py          # Job lifecycle tests.
│       ├── test_web_video_pipeline.py      # Transcript-failure and cancellation pipeline tests.
│       ├── test_web_video_security.py      # Security boundary tests.
│       └── test_web_video_transcript.py    # Transcript parsing and precedence tests.
└── frontend/                               # Frontend applications.
    └── chrome-extension/                   # Internal Manifest V3 video download extension.
        ├── public/                         # Static files copied into the extension build.
        │   └── manifest.json               # Chrome permissions and service-worker manifest.
        ├── src/                            # Extension discovery, API, background and popup source.
        │   ├── api.ts                      # Typed companion HTTP client and session handling.
        │   ├── background.ts               # Service worker: job tracking, Chrome downloads and debugger capture.
        │   ├── discovery.ts                # Media and caption discovery injected into the active tab.
        │   ├── popup.css                   # Popup styling.
        │   ├── popup.ts                    # Popup controller: inspect, download, cancel and capture.
        │   └── types.ts                    # Shared wire types mirroring the companion API models.
        ├── tests/                          # Extension helper unit tests.
        │   └── discovery.test.ts           # Media classification and origin pattern tests.
        ├── package.json                    # Extension build and test dependencies.
        ├── popup.html                      # User interface entrypoint.
        ├── README.md                       # Build, load and capture instructions.
        ├── tsconfig.json                   # Strict TypeScript configuration.
        └── vite.config.ts                  # Deterministic extension bundle configuration.
```
