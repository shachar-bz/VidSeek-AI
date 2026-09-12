# Architecture

```
VidSeek-AI/
├── backend/                                # Python backend.
│   ├── requirements.txt                    # Python dependencies for the backend.
│   ├── Omni_shot_detection/                # Shot boundary detection over a video file.
│   │   ├── __init__.py                     # Public interface of the shot detection module.
│   │   ├── shot_detector.py                # Detects each shot's frame range and timecode using OmniShotCut.
│   │   └── video_decoder.py                # Decodes a video into RGB frames via ffmpeg and reads its frame rate.
│   ├── PySceneDetect_shot_detection/       # Shot boundary detection over a video file, without a GPU.
│   │   ├── __init__.py                     # Public interface of the PySceneDetect shot detection module.
│   │   └── shot_detector.py                # Detects each shot's frame range and timecode using PySceneDetect.
│   ├── OpenAI_transcription/               # Speech transcription over a video file.
│   │   ├── __init__.py                     # Public interface of the OpenAI transcription module.
│   │   ├── audio_extractor.py              # Extracts, probes and cuts a video's audio as 16 kHz mono MP3 via ffmpeg.
│   │   ├── chunk_planner.py                # Plans split points in silence for audio too long for one request.
│   │   ├── transcriber.py                  # Transcribes audio through OpenAI's gpt-transcribe model.
│   │   └── transcript.py                   # Transcript data model shared by the transcription module.
│   └── MMS_word_alignment/                 # Word-level timestamps for a transcript, aligned locally.
│       ├── __init__.py                     # Public interface of the MMS word alignment module.
│       ├── aligner.py                      # Times each word against the audio using torchaudio's MMS forced aligner.
│       ├── audio_loader.py                 # Decodes a media file to 16 kHz mono float samples via ffmpeg.
│       └── text_normalizer.py              # Romanizes mixed Hebrew/English text and spells out digits for the aligner.
└── frontend/                               # Frontend application.
```
