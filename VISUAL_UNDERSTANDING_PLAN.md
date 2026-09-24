# Visual Understanding Layer — Plan

Status: ingestion, storage and the query-time services are implemented (branch
`feat/visual-index-ingestion-and-search`), keyframe OCR with Surya (§3.2 step 5, branch
`feat/visual-keyframe-ocr`), and the two search services of §5 (branch
`feat/visual-search-tools`), none of it run on real footage yet. The insights re-run that depends
on OCR (step 6), the visual sub-agent, its tools (including the wrappers around the two searches)
and `investigate_visual` are not implemented yet. §12 lists where the implementation departs from
this design and why.

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

 video file ──► ffmpeg 0.5 fps ─┬─► SigLIP 2 embeddings ──► search index      website ── message + current_time ──►
                                │                                                          main agent (gpt-6-sol)
                                ├─► content-change detection ──► segments        investigate_visual(question, current_time, range?)
                                │                                                               │
                                └─► keyframes (timestamps only)                                ▼
                                               └─► OCR (if text) ─► text + e5         visual sub-agent (cheap VLM)
                                                                                     list_segments / search_visual_moments /
 after both pipelines finish: re-run insights with OCR text                          search_visual_text / read_frame_text /
                                                                                     view_frames /
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
  or is skipped. *(Resolved: it was deleted by `upload_job_video` right after the upload.)*
* A failure in visual indexing never fails the job: it becomes a problem code and
  `visual_status = failed`, like stages 3–5 today.

### 3.2 Steps

1. **Frame sampling — 0.5 fps.** ffmpeg decodes the local file once and samples **one frame
   every 2 seconds**, at ~384 px on the long side. For a 1-hour video that is **~1,800 frames**.
   This is the only decode pass in indexing.
2. **Image embeddings.** Every sampled frame is embedded with **SigLIP 2 (multilingual, base)**,
   so both Hebrew and English text queries can search it. That is ~1,800 × 768-dim vectors per
   hour, about 5.5 MB. These vectors are the searchable layer for "when does Y appear".
3. **Segments — the sub-agent's map.** No shot detection model is used; segments come from the
   0.5 fps stream itself. Walking it in order, a new segment starts when either
   * the SigLIP embedding differs enough from the segment's first frame (a new scene, a camera
     cut or a new view), or
   * the perceptual hash (phash) changes enough (a new slide or new text on a board; SigLIP can
     see two slides as near-identical, so this check matters).

   To keep camera motion, people walking or a brief flash from splitting a segment, a change
   must hold for **2 consecutive samples**, and segments have a **minimum length of ~6 s**.
   Each segment records `boundary_kind`: `scene_change` (embedding) or `text_change` (phash).
4. **Keyframes.** Each segment gets one keyframe (the first stable frame, a sample or two after
   the boundary), plus one more every ~60 s for long static segments such as a board being
   written on slowly (~100–300 per hour).

   **Frames are processed in place and never stored.** Every decoded frame is used in memory
   (embedding, phash, text check, OCR) and then discarded. Only what came out of it is kept:
   embeddings, segment boundaries, and each keyframe's timestamp, OCR text and OCR embedding.
   When pixels are needed at query time, they are extracted again from the Blob video (§4.2);
   the keyframe timestamp is enough to get the same frame back.
5. **OCR.** Each keyframe is decoded again from the local file at its own resolution (at most
   2048 px; the 384 px samples are too small to read) and read through a pluggable `OcrEngine`
   interface:
   * v1: **Surya 2** (`surya-ocr` 0.22), Hebrew and English. Its text detector runs first, on
     the CPU, and is the cheap "does this frame contain text?" check: a frame with no text line
     never reaches the OCR model. Frames with text are read whole-page by Surya's ~650M VLM
     under llama.cpp's `llama-server` on the GPU, which returns blocks in reading order with a
     confidence each.
   * Surya cannot share the backend's environment (it needs torch >= 2.7 and Pillow < 11), so
     it runs in a worker process of its own environment (`VIDSEEK_OCR_PYTHON`), one JSON message
     per line over stdin/stdout. Without that setting OCR is off and keyframes stay unread.
   * The candidate to compare in the eval: PaddleOCR detection + Tesseract recognition for
     Hebrew crops, the lighter pipeline weighed before Surya was chosen.

   Text runs **after** the index is stored and `ready`, batch by batch, so a video is searchable
   by its frames while its text is still being read. An OCR failure never fails the index.

   The OCR text is kept two ways: as plain text, searched for the words the sub-agent asks for
   (§5.2), and as a **multilingual-e5-small** (384-dim) vector for meaning (§5.1). The existing
   MiniLM is English-only, so it is not used for OCR text.
6. **Insights enrichment.** When indexing is done, the visual task waits for this video's text
   run to finish (it holds that run's future), then re-runs **only the insights stage** (summary,
   takeaways, suggested questions) with the segments' OCR text added. Chapters and memories stay
   transcript-only. Waiting on the future gives the right order with no race and no database
   flag.

### 3.3 Status

`videos.visual_status`: `pending` → `indexing` → `ready` | `failed` | `skipped`, plus
`visual_error` and `visual_index_version`.

`visual_index_version` records the models used (SigLIP, sampling rate); the OCR engine is
recorded per keyframe instead (§12).
Vectors from different models can't be compared, so search refuses to mix versions, and the
version shows which videos need re-indexing after a model change.

## 4. Query time: the visual sub-agent

### 4.1 How the main agent uses it

* The website sends **`current_time_seconds`** with every message. It is added to the
  conversation request schema and to `ConversationDeps`.
* The main agent gets **one new tool**, `investigate_visual(question, current_time, time_range?)`.
  It calls it **only for visual questions the user asked**:
  * explicit visual questions ("what's on the slide", "when do they show the diagram"),
  * and deictic questions ("what is this?", "here").

  It does not call it on its own initiative for questions about what was said.
* **`time_range` is optional, and the main agent passes it only when it is sure** which part of
  the video the question is about (the user named a chapter, or "this" points at the current
  moment). When it is not sure, it leaves it out and the whole video is searched. A range that
  is too narrow hides the answer; no range costs nothing but a longer list.
* The main agent never sees pixels, and has no visual search of its own: searching is the
  sub-agent's work (§5). It receives a short structured result.

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
| `list_segments(t0, t1)` | Text-only map: each segment's start/end, `boundary_kind`, chapter, OCR snippet and transcript snippet | No |
| `search_visual_moments(query, range?)` | Search by what is shown and by what on-screen text means (§5.1). Up to 10 moments | No |
| `search_visual_text(words, range?)` | Search on-screen text for up to 5 given words (§5.2). Up to 5 moments | No |
| `read_frame_text(timestamps)` | Stored OCR text of keyframes, or OCR of any other timestamp on demand | No |
| `view_frames(timestamps)` | Frames, downscaled (~512 px long side) | Yes, 1 per frame |
| `view_sequence(t0, t1, n)` | n frames across a window as **one grid image**. Defaults to the segment's range and never crosses a `scene_change` boundary | Yes, 1 per grid |
| `get_transcript_window(t0, t1)` | What was said in that window | No |

* **Tool choice by question type** (in the prompt):
  * on-screen text → `search_visual_text` to find it, `read_frame_text` to read it;
  * objects, places, people → `view_frames`;
  * actions → `view_sequence`.

  Metadata first, pixels last. The stored metadata (embeddings, OCR text, segment boundaries,
  transcript) answers text questions and most "when does Y appear" questions by itself. The
  image embedding is only a vector for similarity search and says nothing an LLM can read about
  what is in the frame. So for what a frame *shows* (objects, where things are, what a diagram
  means, actions), the sub-agent looks at the frame.
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
* **Before the index is ready:** `search_visual_moments`, `search_visual_text` and
  `list_segments` reply "index not ready, use `view_frames` at current_time". `view_frames`, `read_frame_text` and
  `get_transcript_window` still work, so "what's on screen now" always does.

### 4.3 What it returns

```
VisualInvestigation {
  answer: str
  findings: [{ start_seconds, end_seconds, chapter, observation, evidence: ocr | image | transcript }]
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

## 5. Search: two tools, no fusion

The sub-agent searches with two tools. Their lists are never combined by score: each list has
its own rule for what counts as a match, and returns at most 5 moments.

### 5.1 `search_visual_moments(query, start_seconds?, end_seconds?)`

`query` describes what is shown, in natural language and in any language ("a diagram of
servers and a queue", "כוס על השולחן"). Two lists are read:

1. **Picture.** SigLIP 2's text encoder scores the query against every 0.5 fps frame of the
   video (~1,800 per hour, an exact scan with no ANN index). A frame is a hit when its z-score
   against **that video's own scores** is at least **1.5**, or when its raw similarity is at
   least **0.15**: something on screen for most of the video stands out nowhere, so the z-score
   alone would never find it. There is no minimum similarity beside the z-score.
2. **On-screen text by meaning.** multilingual-e5-small scores the query against the OCR text of
   every keyframe that has any. A keyframe is a hit when its z-score against the video's
   keyframe-text scores is at least **1.5**. With fewer than **20** keyframes with text, a
   z-score over so few scores means little, so the 5 closest are returned with no z filter.

Each list is merged into moments (§5.3) and cut to its best 5: picture moments by their peak
z-score, text moments by their best similarity. The two lists are then joined into **one list
of up to 10 unique moments**. A moment both lists found appears once, with
`found_by: [image, text_meaning]`, and those come first; the rest follow, alternating between
the lists by rank, picture first.

### 5.2 `search_visual_text(words, start_seconds?, end_seconds?)`

`words` is a list of **1 to 5** strings the sub-agent expects to be written on screen
("kafka", "partitions", "כוס"). Each one is looked for in every keyframe's OCR text as a
**sequence of characters**, not as a whole word:

* case is ignored;
* **whitespace is ignored on both sides**: every space, tab and newline is removed from the
  word and from the OCR text before comparing, so "kafka partitions" also matches
  "Kafka" and "Partitions" on two lines, or an OCR line split as "Kaf ka partitions";
* so "כוס" finds "הכוס" and "בכוס", and "cup" also finds "cupboard" and "hiccup". That is
  accepted; the sub-agent reads the text and can tell.

A keyframe matches when at least one word is found in it. There is no score and no threshold.
Moments (§5.3) are ordered by how many **different** words were found in them, then by time,
and the first **5** are returned. Each says which words it matched.

An OCR misreading ("Partitons") is not found. That is the price of exact matching, and the
text-by-meaning list of `search_visual_moments` is there for it.

### 5.3 Moments, not frames

A slide on screen for 40 s is 20 sampled frames, and a top 5 of frames could be one slide five
times. So hits become moments, and the visual segments (§3.2 step 3) say where one thing ends:

* **Picture:** consecutive hit frames (no sample between them) merge into one range, **but never
  across a segment boundary**: a range that crosses one is cut there into two moments. A cut
  from one shot with a cup to another shot with a cup is two moments.
* **Text:** a keyframe's text stands for the stretch from that keyframe to the next keyframe of
  its segment, or to the segment's end. Keyframes of **the same segment** that match in the same
  list merge into one moment (a long slide has a keyframe every ~60 s with the same text).
* **Across the two lists of §5.1:** a picture moment and a text moment are the same moment when
  they are in the same segment and their ranges overlap. The joined moment spans both ranges.

### 5.4 What every moment carries

* `start_seconds`, `end_seconds`;
* its segment (index, `boundary_kind`, start and end) and its chapter (id and title);
* `found_by`;
* **on-screen text**: the OCR text of the keyframe that covers the moment, if it has any,
  capped at ~400 characters;
* **transcript**: what is said while it is on screen, read by time: the transcript segments that
  overlap the moment, widened to ±5 s when the moment is shorter than 10 s, capped at ~600
  characters;
* the peak z-score for a picture match; the matched words for `search_visual_text`.

The sub-agent sees pixels itself, so every moment uses plain `start_seconds`/`end_seconds`; its
own output validator (§4.3) checks that each finding falls inside one of them.

### 5.5 Time window

Both tools take an optional `start_seconds`/`end_seconds`. Moments outside it are dropped and
moments crossing it are clipped. **The z-scores are still computed against the whole video**: in
six minutes of kitchen footage a cup is on screen most of the time and would stand out nowhere.
The prompt tells the sub-agent what the main agent is told (§4.1): narrow the search only when
sure which part of the video is meant.

### 5.6 When the index cannot answer

An index that is not `ready`, or was built with other models than the current ones, returns a
status and no moments, rather than mixing vectors that cannot be compared. While OCR is still
reading a video's keyframes, both text searches say so, so an empty result is not read as "not
on screen".

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
│       ├── search_visual_text/
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
│   │   ├── segments/                   # content-change segmentation, keyframe choice
│   │   └── ocr/                        # OcrEngine protocol, the text a keyframe keeps; surya/ worker
│   ├── visual_search/                  # NEW: per-video scoring, moments by segment, transcript by time
│   ├── video_frames/                   # NEW: frame at time t from Blob, grid building
│   ├── embeddings/
│   │   ├── image_embedding/            # NEW: SigLIP 2 multilingual (image + text encoders)
│   │   └── ocr_text_embedding/         # NEW: multilingual-e5-small
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
and MiniLM all stay resident in 4 GB of VRAM.

## 7. Storage

| Table | Rows per hour of video | Columns / notes |
|---|---|---|
| `video_frame_embeddings` | ~1,800 | `video_id`, `time_seconds`, `embedding vector(768)`. B-tree on `video_id`, **no ANN index**: queries are always for one video and need every score for the per-video scoring |
| `video_visual_segments` | ~20–300 | `video_id`, `start_seconds`, `end_seconds`, `boundary_kind` (`scene_change` / `text_change`), `chapter_id` |
| `video_keyframes` | ~100–300 | `segment_id`, `time_seconds`, `ocr_text`, `ocr_language`, `ocr_confidence`, `ocr_embedding vector(384)`, `ocr_engine` |
| `videos` (new columns) | 1 | `visual_status`, `visual_error`, `visual_index_version` |

No images are stored: Blob keeps only the video, as today.

## 8. Evaluation

A small eval set of **~15 real questions over 2–3 videos**, mixing lectures and general footage
and covering every question type in §1. It is used to:

* pick the VLM (OpenAI cheap vision vs DeepSeek vision-exp);
* check the OCR engine (Surya vs PaddleOCR + Tesseract), with Hebrew included: accuracy and
  seconds per keyframe on the GTX 1650. With no stored frames, the comparison re-reads keyframe
  timestamps from local copies of the eval videos;
* tune the z-score cutoffs (1.5 to start), the 0.15 picture level, the 20-keyframe fallback of
  the text-by-meaning list, and the content-change thresholds (embedding distance, phash
  distance);
* tune the grid layout of `view_sequence`. DeepSeek's 384-token image cap may make grids
  unreadable;
* check that segments catch real cuts and slide changes without over-splitting on motion. The
  shot-detection comparison in `services/shot_detection/results/` already lists the cuts on two
  test videos and serves as ground truth for the cuts;
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
   * 0.5 fps sampling, SigLIP embeddings, segments, keyframe choice, OCR, and
     migrations.
3. **Search and navigate.** `search_visual_moments` and `search_visual_text` (§5), `list_segments`
   and `view_sequence`.
4. **Enrich and evaluate.** Insights re-run with OCR text, and the eval set to set the models
   and thresholds.

## 10. Risks to verify early

1. **DeepSeek vision is experimental.** It caps each image at 384 tokens and accepts images only
   in user messages. Verify image delivery through Pydantic AI's `ToolReturn` in step 1.
2. **Seeking in a WebM file over HTTP can be slow** when it has no seek cues, and every frame the
   sub-agent looks at is a seek. Measure it; if it is slow, remux at Store time, and if it is
   still slow, add the keyframe JPEG cache.
3. **Surya is built for documents.** Boards, handwriting and text over footage are less proven
   than slides, and a VLM decode per frame with text may make OCR the slowest part of indexing
   (minutes per hour of a slide-heavy video). Its weights are free only for research, personal
   use and startups under $5M in funding or revenue. PaddleOCR + Tesseract is the fallback.
4. **One frame can't show an action,** so single-frame embeddings only find candidate moments
   for "picks up the cup". `view_sequence` has to confirm them.
5. **The segment map is thin on general footage.** A segment of footage with no speech or text
   carries little besides its times. If the eval shows the sub-agent spending images on the
   wrong segments, caption segments at ingestion (v2).
6. **Segmentation without a shot detector can be off.** On general footage, a camera pan or a
   person crossing the frame may still split a segment, and two similar-looking shots in a row
   may merge. The 2-sample and ~6 s rules limit this. The eval checks it against the known cuts;
   if it fails, TransNetV2 comes back for the boundaries only.

## 11. Out of scope for v1

* Exact positions in the frame (bounding boxes) and grouping segments into scenes.
* Thumbnails next to visual citations in the website (v1 keeps today's clickable timestamps).
* Backfilling videos ingested before this ships.
* VLM captions of frames, whether for every segment at ingestion or saved from what the
  sub-agent viewed so a moment's pixels are paid for once. The saved kind was designed and then
  removed before the sub-agent existed (migration 0025 drops its table); bring it back if the
  eval shows the sub-agent paying again and again to look at the same moments.
* Chapters or memories that use visual signals (only insights are enriched).
* Moving transcript and memory search from MiniLM (English-only) to a multilingual model.
* Shot detection (TransNetV2). It was dropped for the time it takes (~5 min of GPU per hour of
  video on the GTX 1650, the slowest part of indexing) and because its value over content-change segmentation is
  unproven. Bring it back only if the eval shows segments missing real cuts or splitting on
  motion; `services/shot_detection/` stays in the repo untouched.
* Storing keyframe images (added only if the step 1 latency measurement calls for it).
* Running on machines other than the developer's (no GPU, CPU-only) or a hosted deployment.

## 12. Implementation notes

Where the code departs from the sections above, and why. Measurements are from the developer
machine (GTX 1650).

* **No `chapter_id` on `video_visual_segments`** (§7). Indexing runs in parallel with the
  transcript stages, so the chapters usually do not exist when segments are written, and a
  chapter's times change when the transcript is re-segmented. The chapter is read by time
  instead (`services/visual_search/video_map.py`).
* **OCR columns arrive in 0024** (§7). `video_keyframes` gains `ocr_text`, `ocr_language`,
  `ocr_confidence`, `ocr_embedding` and `ocr_engine`. An earlier design of the word search used
  pg_trgm (0023) and a GIN trigram index on `ocr_text` (0024); `search_visual_text` matches
  character sequences in Python over a video's few hundred keyframes instead, so 0026 drops the
  index and the extension. 0023 still runs on a new database, so `pg_trgm` must stay allowed in
  `azure.extensions` for that.
* **The OCR engine is recorded per keyframe, not in `visual_index_version`** (§3.3). The frame
  vectors do not depend on it, so turning OCR on or off, or changing engine, must not make an
  index unsearchable. `ocr_engine` null means unread; set with `ocr_text` null, read and blank.
* **OCR runs after the index is `ready`,** not before, and stores each batch as it is read.
  Readings the engine was less than 0.5 sure of are dropped block by block, and the language is
  decided by script (`he`, `en`, `mixed`, `other`). A keyframe with no `ocr_engine` is unread, and
  that is how both searches tell OCR is still reading (§5.6). On a machine where OCR is not set
  up, keyframes stay unread, and the searches keep saying so.
* **Surya's worker is tuned for the 4 GB card:** llama.cpp rather than vLLM (which needs Docker
  and claims most of the GPU), two parallel slots, the text detector on the CPU. Starting it the
  first time downloads the models; after that one worker serves every video of the process.
* **`embeddings/multilingual_text_embedding/`** instead of `ocr_text_embedding/` (§6): a name for
  the model rather than for one use of it.
* **A text change must be stable** (§3.2 step 3). On moving footage the pHash of consecutive
  samples differs by 20-30 of 64 bits while the embedding moves ~0.015, so a hash change counts
  only when the new picture then holds still across the confirming samples (≤ 6 bits), the way a
  slide does. The boundary is placed on the first stable frame after the change, which is also
  the reference and the keyframe. On a synthetic clip (moving pattern, two slides, a 4 s shot,
  a moving scene) this finds every cut and slide change exactly; on an 8.5-minute fixed-camera
  padel match it keeps one segment.
* **One absolute level beside the z-score, and no floor** (§5.1). SigLIP scores within a video
  are tightly bunched (std ~0.005), so chance standouts appear in any video: "a dog" on the
  padel match stood out at z 4.3 with a similarity of 0.03, where real matches score 0.12+. An
  earlier design dropped those with a floor (0.08). It was removed on purpose: the sub-agent
  looks at every moment it is handed, and that look is the acceptance step, so the search
  favours catching a match over precision. Something on screen the whole time ("a padel court",
  0.18 in every frame) stands out nowhere, so a frame at or above 0.15 is a hit whatever its
  z-score. Hebrew queries score lower than English ones (the same court: 0.11); the eval should
  tune the level and the z threshold.
* **On-screen text by meaning is judged by its z-score, not by a floor** (§5.1). e5-small's
  scores bunch up: for the same queries, right short descriptions of frames scored 0.81-0.94
  and wrong ones up to 0.815, so no fixed number separates them. A text must stand out from the
  video's other keyframe texts instead. With fewer than 20 of them, every text is a candidate
  and the list keeps its 5 closest moments; that cut is made after the window, so the 5 are the
  closest inside it. A Hebrew question against English text scores low (0.75 for "איפה הכוס"
  against an English description of the cup), which is worth checking in the eval.
* **The window is applied to picture frames, not to ranges** (§5.5). Frames are judged against
  the whole video, then those outside the window are dropped before consecutive hits merge. A
  range crossing the window's edge therefore starts or ends on the first or last frame seen inside
  it rather than exactly on the edge, and its peak z-score is one seen inside it. A keyframe's
  text stretch is clipped to the edge exactly.
* **The transcript is context, not a search list** (§5.4). An earlier design ranked memories by
  MiniLM as a fourth list and fused all the lists per segment by rank. Now a moment only carries
  the transcript segments that overlap it, read by time.
* **SigLIP runs in fp32, not fp16.** On the GTX 1650 fp16 measured 2.6x slower (32 frames in
  4.8 s vs 1.8 s). Peak VRAM at batch 32 is ~1.8 GB. Indexing an hour of 1080p video costs
  ~85 s of decode and ~105 s of embedding, about 3 minutes.
* **Frame extraction latency** (§4.2, risk 2): 6 frames from a local 1080p MP4 in 0.65 s.
  Over a Blob SAS link it is not measured yet; `python -m backend.services.video_frames.measure_latency
  <video_id>` measures it against a stored video.
* **`VIDSEEK_VISUAL_INDEXING=false`** turns ingestion off on a machine without a GPU; its videos
  are marked `skipped`. Videos recorded before migration 0022 are marked `skipped` with
  `ingested_before_visual_indexing`.

