# Repository structure

A map of where each part of VidSeek AI lives. For the architecture itself, see the [README](README.md).

```text
VidSeek-AI/
├── backend/                     Python · FastAPI backend
│   ├── app.py                   ASGI entry point (uvicorn backend.app:app)
│   ├── api/                     App factory, auth dependencies, model preloading
│   │   └── routes/              auth · sessions · account · library (+ SSE events) · video_jobs · videos · conversations (SSE chat)
│   ├── core/                    Config, security (SSRF guard, origin checks), auth, source-URL canonicalisation, caption parsing
│   ├── schemas/                 Pydantic request/response models, readiness stages
│   ├── download_pipeline/       Ingestion orchestration: acquire → store → segment → embed → insights, plus visual indexing
│   │                            and maintenance CLIs (reembed_stale_videos, reindex_visually, resume_keyframe_text, …)
│   ├── services/
│   │   ├── video_download/      Job manager and the YouTube, web (yt-dlp/FFmpeg) and browser-download routes
│   │   │   └── web/structured.py   Privacy-preserving LLM fallback for unfamiliar player/caption JSON
│   │   ├── transcription/elevenlabs/   ElevenLabs Scribe v2 speech-to-text
│   │   ├── forced_alignment/    ElevenLabs forced alignment for untimed English text
│   │   ├── transcripts/         Transcript normalisation into ~8 s segments
│   │   ├── semantic_segmentation/   LLM memories and chapters (Structured Outputs + coverage validation)
│   │   ├── embeddings/          multilingual-e5-small (text) and SigLIP 2 (image–text) encoders
│   │   ├── video_insights.py    Summary, takeaways and starter questions
│   │   ├── visual_indexing/     Frame sampling, content-change segmentation (SigLIP + pHash), keyframe OCR
│   │   ├── ocr/                 Surya OCR worker-process client and text post-processing
│   │   ├── visual_search/       Picture search, screen-text search, visual map of the video
│   │   ├── video_frames/        On-demand frame extraction from Blob Storage and contact-sheet grids
│   │   ├── memory_search.py     Semantic search over memories with per-video z-score filtering
│   │   └── library_changes.py   In-process notifier behind the library SSE stream
│   ├── video_agent/             The conversational agent
│   │   ├── runner.py            Pydantic AI agent on the OpenAI Responses API, event streaming
│   │   ├── prompt.py            System prompt and state-dependent sections (visual availability, player position)
│   │   ├── tools/               The 11 agent tools, one package each
│   │   ├── image_analysis.py    Vision sub-agent with structured per-frame output
│   │   ├── visual_budget.py     Per-answer limits on visual calls and looks
│   │   ├── citations.py         Streaming timestamp-citation filter
│   │   └── generation.py        One active answer per conversation, stop handling
│   ├── storage/
│   │   ├── postgres/            Repositories and 29 ordered SQL migrations (pgvector)
│   │   └── blob/                Azure Blob Storage upload, SAS URLs
│   └── tests/                   pytest suite (1,017 tests)
│
├── chrome-extension/            TypeScript · Manifest V3 side panel
│   ├── src/
│   │   ├── popup.ts             Side-panel flow: sign-in, Find → Scan → progress → chat
│   │   ├── background.ts        Service worker: job polling, CDP capture during playback checks, DRM decision
│   │   ├── page-discovery.ts    In-page media, caption and player-JSON discovery
│   │   ├── frame-discovery.ts   Per-frame injection across embedded players
│   │   ├── discovery.ts         Stream classification, ad filtering, DRM signals, main-video ranking
│   │   ├── hls-renditions.ts    Folding HLS renditions into their master playlist
│   │   ├── caption-fetch.ts     Caption fetching inside the owning frame
│   │   ├── dom-transcript.ts    Generic reader for open transcript panels
│   │   ├── chat.ts, answer-stream.ts, citations.ts, tab-player.ts   Chat, SSE answers, click-to-seek in the tab
│   │   └── scanned-video.ts     Per-user persistence of an in-progress scan
│   └── tests/                   Vitest suite (120 tests)
│
├── frontend/                    TypeScript · React 18 web app
│   ├── src/
│   │   ├── api/                 Typed API client, SSE readers for chat and library events
│   │   ├── auth/                Account context and route guards
│   │   └── pages/               library · video (player, transcript, summary, chat, pins) · account · setup · auth
│   └── tests/                   Vitest + Testing Library suite (87 tests)
│
└── images/                      Logos and README images
```

## Experiments outside the live path

These modules are kept for reference. The running product does not import them:

| Path | What it is |
|---|---|
| `backend/services/shot_detection/` | Offline comparison of three shot detectors (TransNetV2, PySceneDetect, OmniShotCut), with sample results. Production segmentation uses SigLIP + perceptual-hash content change instead. |
| `backend/services/transcription/openai_pipeline/` | An alternative transcription path: OpenAI speech-to-text with torchaudio MMS word alignment. Production uses captions or ElevenLabs. |
