# VidSeek AI — technical architecture walkthrough

A 3:51.97 technical explanation using the supplied narration. The visual design uses quiet static diagrams, a persistent architecture rail, focused implementation panels, and two authentic product recordings. The capability timeline progressively highlights transcript chat, visual search and OCR availability.

## Deliverables

- `VISUAL_PLAN.md`: 20 sections with narration, exact cue times, screen content, visual type, transition instructions and implementation references.
- `STORYBOARD.html`: local visual review page with the final narrated video and individual diagrams.
- `out/vidseek-architecture.mp4`: 1920×1080, 30 fps, H.264 + AAC mono 48 kHz. Original narration content and pauses, with loudness normalization; no music or sound effects.
- `out/vidseek-visual-layer.mp4`: identical edit without audio, for use with the original MP3 in an editor.
- `out/storyboard.jpg`: planned diagram contact sheet.
- `out/video-contact-sheet.jpg`: frames extracted from all 20 sections of the encoded video.
- `out/verification.json` and `out/audio-verification.txt`: export and audio checks.
- `assets/scenes/`: 20 base scenes plus 2 progressive-highlight states, each as an editable SVG and full-resolution PNG. Product frames embedded in the SVGs are raster screenshots; diagram elements are vectors.
- `assets/timeline.json`: machine-readable timing and editorial plan. Export rounds cue times to the nearest 30 fps frame.
- `recordings/extension-discovery.mp4`: Coursera extension Find / Scan, cropped for readable controls; plays once and then holds.
- `recordings/library-resume.mp4`: existing library search, open video, reopen saved conversation; shortened idle intervals.
- `recordings/provenance.json`: source takes, source ranges, crop and speed changes.

The product inserts are new edits of authentic recordings from `promo-video/public/clips/v3/`. They are not new live captures. Illustrative frame-grid examples and citation ranges are explicitly labeled as examples. The capability timeline shows availability order rather than measured processing time. No invented backend logs, benchmark numbers or UI responses are used.

## Narration timing

The supplied written transcript is the authority for the wording. A local Whisper base.en model recognized the MP3 and supplied word timestamps. All 20 editorial cue phrases matched exactly. Recognition of the presenter's name and some technical brand names is imperfect, so recognized text is never used as on-screen captions. The audio and transcript were not uploaded to a third-party service.

The citation panel reflects the code's endpoint checks with one-second tolerance. It demonstrates timestamp support, not factual verification of answer prose. The per-answer visual limits of 6 calls and 4 looks are the defaults in `backend/video_agent/visual_budget.py`.

## Rebuild

Source work is on branch `explain-video-architecture`, in the dedicated `.claude/worktrees/explain-video-architecture` worktree. Generated deliverables are also copied into the main checkout's `explain-video` folder for easy access.

Requires FFmpeg, FFprobe, Pillow, and the project Python environment. Narration analysis additionally uses Torch and Transformers and expects the downloaded Whisper model at `/private/tmp/vidseek-explain-whisper`; the cached word timing JSON already allows rebuilding without recognition or any network access.

From the explanation folder in the worktree:

```sh
PROJECT_PYTHON=/Users/shachar/Documents/VidSeek-AI/.venv/bin/python
MEDIA_ROOT=/Users/shachar/Documents/VidSeek-AI
$PROJECT_PYTHON scripts/prepare_media.py --media-root "$MEDIA_ROOT"
$PROJECT_PYTHON scripts/plan_scenes.py
$PROJECT_PYTHON scripts/build_assets.py
$PROJECT_PYTHON scripts/render_video.py --media-root "$MEDIA_ROOT"
```

To redo local recognition before planning:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 $PROJECT_PYTHON scripts/analyze_audio_local.py
```

The PNG builder uses macOS Avenir Next, Menlo and Arial Unicode fonts. SVGs declare system font fallbacks. Videos, source stills and PNG renders are ignored by Git; scene SVGs, timeline, narration timing and build scripts are retained for reproducibility.
