# Architecture

```
VidSeek-AI/
├── backend/                           # Python backend.
│   ├── requirements.txt               # Python dependencies for the backend.
│   ├── shot_detection/                # Shot boundary detection over a video file.
│   │   ├── __init__.py                # Public interface of the shot detection module.
│   │   ├── shot_detector.py           # Detects each shot's frame range and timecode using OmniShotCut.
│   │   └── video_decoder.py           # Decodes a video into RGB frames via ffmpeg and reads its frame rate.
│   └── scenedetect_shot_detection/    # Shot boundary detection over a video file, without a GPU.
│       ├── __init__.py                # Public interface of the PySceneDetect shot detection module.
│       └── shot_detector.py           # Detects each shot's frame range and timecode using PySceneDetect.
└── frontend/                          # Frontend application.
```
