# Architecture

```
VidSeek-AI/
├── backend/                                # Python backend.
│   ├── requirements.txt                    # Python dependencies for the backend.
│   ├── ElevenLabs_transcription/           # Speech transcription of a video file.
│   │   ├── __init__.py                     # Public interface of the ElevenLabs transcription module.
│   │   ├── transcript.py                   # Transcript data model: words, audio events and speakers.
│   │   └── transcriber.py                  # Transcribes a video via the ElevenLabs Scribe v2 API.
│   ├── Omni_shot_detection/                # Shot boundary detection over a video file.
│   │   ├── __init__.py                     # Public interface of the shot detection module.
│   │   ├── shot_detector.py                # Detects each shot's frame range and timecode using OmniShotCut.
│   │   └── video_decoder.py                # Decodes a video into RGB frames via ffmpeg and reads its frame rate.
│   └── PySceneDetect_shot_detection/       # Shot boundary detection over a video file, without a GPU.
│       ├── __init__.py                     # Public interface of the PySceneDetect shot detection module.
│       └── shot_detector.py                # Detects each shot's frame range and timecode using PySceneDetect.
└── frontend/                               # Frontend application.
```
