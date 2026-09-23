# Visual Understanding Layer — Plan

Status: agreed design, not yet implemented. Branch: `feat/visual-understanding-layer`.

## 1. Goal

Today the video agent understands a video only through what is said in it. This layer lets it
answer questions about what is **shown**, for mixed content (lectures and talks as well as
general footage), in English and Hebrew:

| Question type | Example |
|---|---|
| What is on screen now | "What is this diagram?" / "What does the slide say?" |
| When something appears | "When do they show the architecture diagram?" |
| Where something is when something else happens | "Where is the cup when the man enters?" → place in the scene + chapter + approximate time |
| Actions and events | "When does he pick up the cup?" / "What happens after the door opens?" |
| On-screen text | Slides, boards, code, captions burned into the video |

### Constraints

* **Near-zero cost until asked.** Ingestion uses only local models; no paid API call per video.
  A VLM is paid only when a user asks a visual question.
* **"Now" is instant; the rest can lag.** A question about the current frame works as soon as
  the video is stored. Whole-video visual search becomes available when background indexing
  finishes.
* **The main agent's context stays clean.** It never receives images; a visual sub-agent does
  the looking and hands back text.
* **Runs on the developer machine only for now** (GTX 1650, 4 GB VRAM). Portability to users'
  machines or a hosted server is out of scope for v1.

## 2. Overview

```
                        INGESTION (background)                          QUERY (per question)

 video file ──► TransNetV2 ──► shot cuts ─┐                 website ── message + current_time ──►
            │                             ├─► segments                                         main agent (gpt-6-sol)
            └─► ffmpeg 0.5 fps ─┬─► SigLIP 2 embeddings ──► search index         investigate_visual(question, current_time, range?)
                                ├─► content-change detection ┘                              │
                                └─► keyframes (timestamps only)                            ▼
                                               └─► OCR (if text) ─► trigram + e5      visual sub-agent (cheap VLM)
                                                                                     list_segments / search_visual_moments /
 after both pipelines finish: re-run insights with OCR text                          read_frame_text / view_frames /
                                                                                     view_sequence / get_transcript_window
                                                                                              │
                                                                                     structured findings (text only)
                                                                                              ▼
                                                                                     main agent answers with citations
```

## 3. Ingestion: building the visual index

### 3.1 Where it runs

* A new **visual executor** (`ThreadPoolExecutor(max_workers=1)`) owned by `JobManager`, next to
  the existing single-worker text executor.
* The text pipeline hands the video over right after the **Store** stage, through a
  `schedule_visual_indexing(video_id, local_path)` callback that `jobs.py` passes in. The text
  stages (segment → embed → insights) continue as today, in parallel.
* **The job slot is freed when the text stages finish.** The job reports done; visual progress
  is tracked separately as `visual_status`. The next video's text stages may overlap this
  video's visual indexing, but two visual indexing runs never share the GPU at once.
* **The visual task owns the local video file.** Deleting it moves from the end of the text run
  to the end of the visual task, in a `finally`, so the file is also removed when indexing fails
  or is skipped. *(Open item: trace where the local file is deleted today before moving it.)*
* A failure in visual indexing never fails the job: it becomes a problem code and
  `visual_status = failed`, like stages 3–5 today.

### 3.2 Steps

1. **Shot cuts — TransNetV2.** It runs on the local file and gives hard cut boundaries. It is
   trained to ignore motion inside a shot (pans, people walking), so on general footage it gives
   clean boundaries. For v1 it decodes the file itself; sharing one decode pass with step 2 is a
   later optimisation, since this work is off the critical path.
2. **Frame sampling — 0.5 fps.** ffmpeg samples **one frame every 2 seconds**, at ~384 px on the
   long side. For a 1-hour video that is **~1,800 frames**.
3. **Image embeddings.** Every sampled frame is embedded with **SigLIP 2 (multilingual, base)**,
   so both Hebrew and English text queries can search it. That is ~1,800 × 768-dim vectors per
   hour, about 5.5 MB. These vectors are the searchable layer for "when does Y appear".
4. **Segments — the sub-agent's map.** A segment is a TransNetV2 shot, split further wherever
   the screen content changes. This matters for lectures, where one "shot" can run ~3 minutes
   and cover many slides. Walking the 0.5 fps stream inside each shot, a new segment starts when
   either
   * the SigLIP embedding differs enough from the segment's first frame (a new scene or view), or
   * the perceptual hash (phash) changes enough (a new slide or new text on a board; SigLIP can
     see two slides as near-identical, so this check matters).

   Each segment records `boundary_kind`: `shot_cut` or `content_change`.
5. **Keyframes.** Each segment gets one keyframe (the first stable frame, a sample or two after
   the boundary), plus one more every ~60 s for long static segments such as a board being
   written on slowly (~100–300 per hour).

   **Frames are processed in place and never stored.** Every decoded frame is used in memory
   (embedding, phash, text check, OCR) and then discarded. Only what came out of it is kept:
   embeddings, segment boundaries, and each keyframe's timestamp, OCR text and OCR embedding.
   When pixels are needed at query time, they are extracted again from the Blob video (§4.2);
   the keyframe timestamp is enough to get the same frame back.
6. **OCR.** Each keyframe first goes through a cheap "does this frame contain text?" check,
   since general footage has many frames without any. Frames that pass get OCR through a
   pluggable `OcrEngine` interface:
   * v1: **Tesseract** `eng+heb` (CPU).
   * The candidate to compare in the eval: **Surya** (GPU, more accurate on Hebrew and messy
     text).

   The OCR text is indexed two ways: **pg_trgm** for exact words, and **multilingual-e5-small**
   (384-dim) for meaning. The existing MiniLM is English-only, so it is not used for OCR text.
7. **Insights enrichment.** When indexing is done, the visual task waits for this video's text
   run to finish (it holds that run's future), then re-runs **only the insights stage** (summary,
   takeaways, suggested questions) with the segments' OCR text added. Chapters and memories stay
   transcript-only. Waiting on the future gives the right order with no race and no database
   flag.

### 3.3 Status

`videos.visual_status`: `pending` → `indexing` → `ready` | `failed` | `skipped`, plus
`visual_error` and `visual_index_version`.

`visual_index_version` records the models used (SigLIP, e5, OCR engine, sampling rate).
Vectors from different models can't be compared, so search refuses to mix versions, and the
version shows which videos need re-indexing after a model change.

## 4. Query time: the visual sub-agent

### 4.1 How the main agent uses it

* The website sends **`current_time_seconds`** with every message. It is added to the
  conversation request schema and to `ConversationDeps`.
* The main agent gets **one new tool**, `investigate_visual(question, current_time, time_range?)`.
  It calls it for
  * explicit visual questions ("what's on the slide"),
  * deictic questions ("what is this?", "here"),
  * and questions the transcript tools could not answer that the video likely showed.
* The main agent never sees pixels. It receives a short structured result.

### 4.2 The sub-agent

* A separate Pydantic AI agent in a new package, `backend/visual_agent/`.
* **Model:** read from env and configurable.
  * Default: the cheapest vision-capable OpenAI model.
  * Candidate to compare in the eval: DeepSeek `deepseek-v4-flash-vision-exp`, through Pydantic
    AI's OpenAI-compatible provider.
* **Stateless per call.** Follow-up context lives in the main agent's history.
* **Tools** (one directory per tool, like `video_agent/tools/`):

| Tool | What it does | Costs an image? |
|---|---|---|
| `list_segments(t0, t1)` | Text-only map: each segment's start/end, `boundary_kind`, chapter, OCR snippet, transcript snippet, and saved frame captions (§4.4) | No |
| `search_visual_moments(query, range?)` | Hybrid search (§5). Returns time ranges, each with the segment it falls in | No |
| `read_frame_text(timestamps)` | Stored OCR text of keyframes, or OCR of any other timestamp on demand | No |
| `view_frames(timestamps)` | Frames, downscaled (~512 px long side) | Yes, 1 per frame |
| `view_sequence(t0, t1, n)` | n frames across a window as **one grid image**. Defaults to the segment's range and never crosses a shot cut | Yes, 1 per grid |
| `get_transcript_window(t0, t1)` | What was said in that window | No |

* **Tool choice by question type** (in the prompt):
  * on-screen text → `read_frame_text` first;
  * objects, places, people → `view_frames`;
  * actions → `view_sequence`.

  Metadata first, pixels last. The stored metadata (embeddings, OCR text, segment boundaries,
  transcript, saved captions) answers text questions and most "when does Y appear" questions by
  itself. The image embedding is only a vector for similarity search and says nothing an LLM can
  read about what is in the frame. So for what a frame *shows* (objects, where things are, what
  a diagram means, actions), the sub-agent looks at the frame, unless a saved caption (§4.4)
  already answers it.
* **Budget per investigation:** at most **6 tool calls** and at most **8 images** (a grid counts
  as one).
  * Enforced by Pydantic AI `UsageLimits` plus an image counter in deps.
  * When the budget is spent, the tool says so and the agent must answer with what it has,
    including "not found" or "low confidence".
* **Where frames come from:** always extracted on demand. ffmpeg seeks the Blob video through a
  read (SAS) URL; the frames of one tool call are extracted in parallel. There is no frame cache
  in v1. Step 1 of the build measures the latency, and a keyframe JPEG cache is added only if a
  batch of frames takes more than ~1–2 s (an isolated change inside `services/video_frames/`).
* **How images reach the VLM:** tools return
  `ToolReturn(return_value=..., content=[BinaryContent(...)])`, and Pydantic AI delivers the
  image as a user message. DeepSeek accepts images only in user messages, so this must be tested
  first.
* **Before the index is ready:** `search_visual_moments` and `list_segments` reply "index not
  ready, use `view_frames` at current_time". `view_frames`, `read_frame_text` and
  `get_transcript_window` still work, so "what's on screen now" always does.

### 4.3 What it returns

```
VisualInvestigation {
  answer: str
  findings: [{ start_seconds, end_seconds, chapter, observation, evidence: ocr | image | transcript | caption }]
  frame_captions: [{ time_seconds, caption }]   # saved (§4.4), stripped before the main agent sees the result
}
```

* **Citations work with no change to `citations.py`.** `spans_of` in
  `video_agent/citations.py` collects every `start_seconds`/`end_seconds` pair in a tool result,
  so the main agent's existing check accepts visual timestamps.
* **The sub-agent checks its own findings.** Its output validator makes sure every finding falls
  inside a span its own tools returned. It is written inside `visual_agent/`, not imported from
  `video_agent/`.
* **"Where is X when Y appears"** is answered as a place in the scene, plus the segment range and
  the chapter it falls in, e.g. "on the kitchen table — 04:12–04:30, chapter 'Preparing the
  sauce'". No bounding boxes.

### 4.4 Saved captions: pay for pixels at most once

No image is ever stored. When the sub-agent has to see pixels, the frame is extracted on
demand. Whatever it learned from them is kept as metadata, so the next question about that
part of the video reads text instead of pixels.

* **What is saved.** For every frame it viewed (`view_frames`) or grid (`view_sequence`), the
  sub-agent writes a short **general** caption in `frame_captions`: what is visible, where things
  are, what is happening. It is not an answer to the current question, because a caption biased
  toward one question is useless for the next. This costs only output tokens: no extra call and
  no extra image.
* **Where it goes.** After the run, `investigate_visual` stores each caption against its segment
  and timestamp, with the VLM model name, and embeds it with multilingual-e5-small.
* **How it is used.**
  * `list_segments` shows the saved captions, so the map gets richer the more a video is asked
    about. This softens the "thin map on general footage" risk (§10).
  * `search_visual_moments` includes caption hits in the rank fusion (§5).
  * The prompt tells the sub-agent to use a saved caption that answers the question before
    looking at pixels again.
* **Cost model.** Each part of a video is paid for at most once, and only if someone asks about
  it. Captioning every segment at ingestion stays out of scope for v1.

## 5. Search and score thresholds

**No fixed minimum score.** Every model scores on its own scale: SigLIP text-to-image cosines
are low, e5 scores bunch up high, MiniLM sits in between. The same number would mean different
things in each list. Instead:

1. **Score against the whole video.** Every query scores every 0.5 fps embedding of that one
   video (~1,800 per hour, an exact scan with no ANN index). A frame counts as a hit when it
   stands out from that video's own score distribution (z-score ≳ 2.5–3; the exact value comes
   from the eval).
2. **"Not in the video."** If even the best frame doesn't stand out, the tool says so, rather than
   returning the least-bad frames. Without this the sub-agent tends to invent a match.
3. **Hits become time ranges.** Consecutive hit samples merge into ranges ("03:10–03:24,
   12:40–12:44"). Each range is tagged with the segment and chapter it falls in.
4. **Combine by rank.** Image-embedding hits, OCR trigram hits, OCR e5 hits, saved-caption e5
   hits (§4.4) and transcript hits are combined with **reciprocal rank fusion**. It uses only rank, so the lists' different score
   scales never have to be compared.
5. **A low floor per model** drops obvious junk. It is tuned on the eval set to favour catching
   matches, not precision: the sub-agent's look is the real acceptance step.

Resolution note: at 0.5 fps, search is accurate to about ±2 s. Something visible for less than
~2 s can fall between samples. The sub-agent can refine around a hit with `view_frames`.

## 6. Code layout

Follows the rules in `ARCHITECTURE.md`. Update that file when these directories are added.

```
backend/
├── visual_agent/                       # NEW: the visual sub-agent, a sibling of video_agent/
│   ├── runner.py                       # run_investigation(question, current_time, range) -> VisualInvestigation
│   ├── prompt.py                       # tool choice by question type, budget behaviour
│   ├── budget.py                       # tool call and image limits
│   ├── result.py                       # VisualInvestigation, findings
│   └── tools/                          # one directory per tool
│       ├── list_segments/
│       ├── search_visual_moments/
│       ├── read_frame_text/
│       ├── view_frames/
│       ├── view_sequence/
│       └── get_transcript_window/
├── video_agent/
│   ├── tools/deps.py                   # CHANGED: + current_time_seconds
│   └── tools/investigate_visual/       # NEW: the main agent's only visual tool; calls visual_agent
├── services/
│   ├── visual_indexing/                # NEW: builds one video's index from its local file
│   │   ├── sampling/                   # ffmpeg 0.5 fps frame stream
│   │   ├── segments/                   # shot cuts + content-change split, keyframe choice
│   │   └── ocr/                        # OcrEngine protocol; tesseract/ now, surya/ later
│   ├── visual_search/                  # NEW: per-video scoring, time ranges, RRF, segment/chapter tagging
│   ├── video_frames/                   # NEW: frame at time t from Blob, grid building
│   ├── embeddings/
│   │   ├── image_embedding/            # NEW: SigLIP 2 multilingual (image + text encoders)
│   │   └── ocr_text_embedding/         # NEW: multilingual-e5-small
│   └── shot_detection/transnetv2/      # REUSED as is for v1
├── download_pipeline/
│   ├── visual_indexing.py              # NEW stage: calls services/visual_indexing, returns problem codes
│   └── pipeline.py                     # CHANGED: schedules visual indexing after Store
├── services/video_download/jobs.py     # CHANGED: second (visual) executor; the local file's lifetime moves
├── storage/
│   ├── postgres/                       # NEW stores + migrations 0022+
│   └── blob/                           # CHANGED: read (SAS) URLs so ffmpeg can seek the video
└── schemas/                            # CHANGED: current_time_seconds on the conversation request; visual_status on the video
frontend/src/api/types.ts               # CHANGED: mirrors the schema changes
frontend/src/pages/video/               # CHANGED: the player's currentTime goes out with each message
```

**Import direction:** `video_agent` → `visual_agent` → `services` → `storage`. `visual_agent`
never imports `video_agent`. `services/video_frames/` is used only at query time; indexing reads
the local file.

**Models in one process.** Each model is loaded once per process (like
`services/embeddings/model.py`) and inference runs behind a lock. The SigLIP text encoder serves
chat queries while the indexing thread may be using the image encoder. SigLIP-base, e5-small,
MiniLM and TransNetV2 all stay resident in 4 GB of VRAM.

## 7. Storage

| Table | Rows per hour of video | Columns / notes |
|---|---|---|
| `video_frame_embeddings` | ~1,800 | `video_id`, `time_seconds`, `embedding vector(768)`. B-tree on `video_id`, **no ANN index**: queries are always for one video and need every score for the per-video scoring |
| `video_visual_segments` | ~20–300 | `video_id`, `start_seconds`, `end_seconds`, `boundary_kind` (`shot_cut` / `content_change`), `chapter_id` |
| `video_keyframes` | ~100–300 | `segment_id`, `time_seconds`, `ocr_text` (GIN trigram index), `ocr_language`, `ocr_embedding vector(384)` |
| `video_frame_captions` | grows with use (0 at ingestion) | `segment_id`, `time_seconds`, `caption`, `caption_embedding vector(384)`, `model`, `created_at` |
| `videos` (new columns) | 1 | `visual_status`, `visual_error`, `visual_index_version` |

No images are stored: Blob keeps only the video, as today.

## 8. Evaluation

A small eval set of **~15 real questions over 2–3 videos**, mixing lectures and general footage
and covering every question type in §1. It is used to:

* pick the VLM (OpenAI cheap vision vs DeepSeek vision-exp);
* pick the OCR engine (Tesseract vs Surya), with Hebrew included. With no stored frames, the
  comparison re-reads keyframe timestamps from local copies of the eval videos;
* tune the z-score cutoff, the per-model floors, and the content-change thresholds (embedding
  distance, phash distance);
* tune the grid layout of `view_sequence`. DeepSeek's 384-token image cap may make grids
  unreadable;
* check that segments catch real cuts and slide changes on the shot-detection test videos;
* confirm the 6-call / 8-image budget answers most questions.

## 9. Build order

Each step ships something usable. The riskiest assumption is tested first.

1. **See the current frame.**
   * `services/video_frames/` (frame from Blob), and `current_time_seconds` from the website to
     `ConversationDeps`.
   * `visual_agent/` with `view_frames`, `read_frame_text` (on-demand OCR) and
     `get_transcript_window`, plus the main agent's `investigate_visual`.
   * This already answers "what's on screen now" with no index. Test image delivery to both VLM
     candidates here, and measure Blob seek latency to decide whether a frame cache is needed.
2. **Build the index.**
   * The visual executor, the local-file lifetime change and `visual_status`.
   * TransNetV2, 0.5 fps sampling, SigLIP embeddings, segments, keyframe choice, OCR, and
     migrations.
3. **Search and navigate.** `search_visual_moments` (§5), `list_segments`, `view_sequence`, and
   saved captions (§4.4).
4. **Enrich and evaluate.** Insights re-run with OCR text, and the eval set to set the models
   and thresholds.

## 10. Risks to verify early

1. **DeepSeek vision is experimental.** It caps each image at 384 tokens and accepts images only
   in user messages. Verify image delivery through Pydantic AI's `ToolReturn` in step 1.
2. **Seeking in a WebM file over HTTP can be slow** when it has no seek cues, and every frame the
   sub-agent looks at is a seek. Measure it; if it is slow, remux at Store time, and if it is
   still slow, add the keyframe JPEG cache.
3. **Tesseract may be weak on Hebrew** that isn't clean slide text, such as boards or text over
   footage. Surya is the fallback.
4. **One frame can't show an action,** so single-frame embeddings only find candidate moments
   for "picks up the cup". `view_sequence` has to confirm them.
5. **The segment map is thin on general footage.** Until someone asks about it, a segment of
   footage with no speech or text carries little besides its times. Saved captions (§4.4) fill
   the map in as the video is used. If the eval shows the sub-agent still spending images on the
   wrong segments of fresh videos, caption segments at ingestion (v2).
6. **Saved captions can be wrong or incomplete.** A later question may trust a caption that
   missed a detail. The sub-agent treats a caption as a lead and looks at the pixels when the
   answer depends on a detail the caption doesn't state.

## 11. Out of scope for v1

* Exact positions in the frame (bounding boxes) and grouping shots into scenes.
* Thumbnails next to visual citations in the website (v1 keeps today's clickable timestamps).
* Backfilling videos ingested before this ships.
* VLM captions for every segment at ingestion (v1 saves captions only when a frame is viewed,
  §4.4).
* Chapters or memories that use visual signals (only insights are enriched).
* Moving transcript and memory search from MiniLM (English-only) to a multilingual model.
* Sharing one decode pass between TransNetV2 and the 0.5 fps sampling.
* Storing keyframe images (added only if the step 1 latency measurement calls for it).
* Running on machines other than the developer's (no GPU, CPU-only) or a hosted deployment.
