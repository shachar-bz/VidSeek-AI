# VidSeek AI — technical walkthrough visual plan

Duration: 03:51.97. Original narration preserved. Local Whisper word timestamps align editorial cues; provided transcript is the authority for wording. Cues are rounded to the 30 fps edit grid for export.

## Visual approach

1920 × 1080, 30 fps. Warm white background, dark navy text, blue text pathway, teal visual pathway, purple agent pathway. Use the VidSeek icon, Avenir headings and Menlo code. One persistent architecture map with matching detail panels. Static holds and progressive highlights; clean cuts at changes of topic. No music, sound effects, marketing CTA, or ornamental transitions.

Product inserts reuse authentic recordings from this project and are recut for this narration; no UI or backend activity is fabricated. Illustrative frames and citation examples are explicitly labeled. The processing timeline expresses order, not measured elapsed time.

## Scene-by-scene plan

### 01-intro · 00:00.00–00:23.40 · VidSeek AI · Under the hood

**Narration:** Hi everyone, I’m Shachar Ben Zur, and this is VidSeek AI. In my first video, I introduced the features. Today, I’ll walk through the architecture and the decisions behind it. The goal of VidSeek AI is to turn videos into searchable, interactive knowledge: what was said, what was shown, and when it happened — all through one conversation.

**Visual:** Title + architecture preview. Logo, presenter credit and a restrained preview of acquisition → processing → retrieval.

**Direction:** Hold; no logo animation.

**Implementation evidence:** `Architecture and implementation`

### 02-architecture · 00:23.40–00:33.44 · Clients, orchestration and storage

**Narration:** The system combines a web app, a Chrome extension, and a FastAPI backend. Azure stores the structured data, embeddings, and video files.

**Visual:** Architecture diagram. Web app and Chrome extension connect to FastAPI. Azure PostgreSQL + pgvector stores records and vectors; Blob Storage stores media.

**Direction:** Same map establishes stable component positions.

**Implementation evidence:** `backend/storage/postgres; backend/storage/blob`

### 03-discovery · 00:33.44–00:51.66 · Acquire the right media

**Narration:** The first challenge is acquiring the right media. The extension identifies the video through page elements, embedded players, and network activity in the user’s browser session. When needed, playback reveals the stream and helps distinguish the main content from ads or other videos.

**Visual:** Screen recording + diagram. Actual Coursera extension Find / Scan recording next to DOM, embedded-player and network inputs. Main media is selected; ad candidates are rejected.

**Direction:** Play the six-second recording once, then hold its final frame. Highlight browser → acquisition.

**Implementation evidence:** `chrome-extension/src/discovery.ts; page-discovery.ts; background.ts`

### 04-parsing · 00:51.66–01:01.70 · Parse first. Validate the fallback.

**Narration:** Known structures are parsed deterministically. Unfamiliar structured data goes through an LLM fallback, with its selections validated against the captured data.

**Visual:** Data-flow diagram. Known payload → deterministic parser. Unfamiliar payload → LLM selects references → validate against captured payload → accepted resource.

**Direction:** Highlight the alternate route; keep acquisition mini-map.

**Implementation evidence:** `backend/services/video_download/web/structured.py`

### 05-transcription · 01:01.70–01:08.02 · Build a timestamped transcript

**Narration:** The system uses existing timestamped captions or transcribes the audio with ElevenLabs.

**Visual:** Data-flow diagram. Existing timestamped captions OR audio → ElevenLabs transcription → timestamped transcript.

**Direction:** Show both alternatives converging; no simulated API response.

**Implementation evidence:** `backend/services/video_download/web/transcript.py; transcription/elevenlabs`

### 06-reuse · 01:08.02–01:17.44 · Reuse before downloading

**Narration:** Videos and their analysis are saved. Before downloading, the system checks for a matching source and reuses existing results to save time and resources.

**Visual:** Decision diagram. Normalized source identity → lookup → hit: reuse saved media and analysis; miss: acquire and persist. Azure database and Blob Storage are separate.

**Direction:** Emphasize the cache-hit branch; hold through the pause.

**Implementation evidence:** `backend/services/video_download/jobs.py:create; _create_deduplicated_job`

### 07-parallel · 01:17.44–01:26.58 · Two parallel processing paths

**Narration:** Now, let’s talk about how the video is processed. Processing follows two parallel paths: text and visuals.

**Visual:** Architecture diagram. Return to the original map, expanded around processing. Transcript branch and visual branch run side by side.

**Direction:** One deliberate detail cut. Text remains blue; visuals remain teal.

**Implementation evidence:** `backend/services/video_download/jobs.py; backend/services/visual_indexing`

### 08-memories · 01:26.58–01:42.08 · Transcript → memories → chapters

**Narration:** An LLM divides the transcript into memories — short passages, each focused on one idea — and groups them into chapters with titles and summaries. We then create embeddings for these passages, enabling search based on semantic similarity.

**Visual:** Diagram + code view. Timestamped passages become one-idea memories and chapter groups with titles/summaries. E5 creates 384-dimensional passage vectors for pgvector semantic retrieval.

**Direction:** Highlight text lane. Small exact code excerpt shows query: / passage: role prefixes.

**Implementation evidence:** `semantic_segmentation/memories; chapters; embeddings/multilingual_text_embedding/model.py`

### 09-frames · 01:42.08–01:49.74 · Sample once every two seconds

**Narration:** The visual pipeline samples a frame every two seconds and creates visual embeddings for natural-language search.

**Visual:** Frame-strip diagram. Illustrative video frames at 0, 2, 4, 6, 8 seconds → SigLIP 2 → 768-dimensional vectors; natural-language query enters the same embedding space.

**Direction:** Highlight visual lane and sampling interval; frames remain still.

**Implementation evidence:** `visual_indexing/sampling/frame_stream.py; embeddings/image_embedding/model.py`

### 10-ocr · 01:49.74–02:01.98 · Stable changes → keyframes → OCR

**Narration:** It detects lasting changes in scenes or on-screen content, filtering out brief movement. Selected keyframes then pass through local OCR to make on-screen text searchable.

**Visual:** Diagram + implementation view. Contrast transient movement with a lasting slide/content change. Embedding distance + perceptual hash; two stable changed samples confirm a boundary. Selected full-resolution keyframes → local Surya OCR → searchable text.

**Direction:** Reuse frame strip; emphasize retained keyframes and OCR route.

**Implementation evidence:** `visual_indexing/segments/segmenter.py; sampling/keyframes.py; ocr/configured.py`

### 11-progressive · 02:01.98–02:18.88 · Availability grows progressively

**Narration:** Because this takes time, capabilities become available progressively. Users can start chatting about the transcript while visual processing continues. Visual search becomes available next, and OCR coverage expands as more keyframes are processed.

**Visual:** Capability timeline. Transcript chat ready first; frame search ready next; OCR coverage continues expanding. Timings are schematic, not performance measurements.

**Direction:** Hold the same timeline. Highlight transcript first, visual search at 02:11.40, and OCR at 02:13.90; no measured percentages.

**Implementation evidence:** `video_agent/tools/visual_tools.py; services/visual_search.py`

### 12-agent · 02:18.88–02:32.90 · Retrieve focused evidence

**Narration:** So, how does the agent use all this information? It calls tools to search the video and inspect specific moments, retrieving focused evidence without loading the entire transcript and every image into its context.

**Visual:** Agent data-flow diagram. Question → main agent → tools → relevant text / moments → evidence → answer. Full transcript and image archive stay in storage.

**Direction:** Rejoin original map at agent; highlight retrieval edges.

**Implementation evidence:** `backend/video_agent/runner.py; tools`

### 13-texttools · 02:32.90–02:49.18 · Find the passage, then expand context

**Narration:** For questions about spoken content, the agent can explore chapter titles and summaries to identify relevant sections, or use semantic search to find specific passages. It can then retrieve a full chapter or a memory with its surrounding passages for context.

**Visual:** Tool diagram. get_video_outline or memories_semantic_search → relevant chapter/memory → get_chapter_context or get_memory_context → evidence with timestamp ranges.

**Direction:** Follow one path at a time with blue outlines; show exact tool names.

**Implementation evidence:** `video_agent/tools/get_video_outline; memories_semantic_search; get_chapter_context; get_memory_context`

### 14-candidates · 02:49.18–03:01.34 · Search candidates, then inspect

**Narration:** For visual questions, a search tool finds candidate moments. The agent then uses inspection tools. One combines frames from different moments into a single image for comparison. Another presents frames in chronological order to examine how an action unfolds.

**Visual:** Illustrative inspection diagram. search_visual_moments returns candidate times; view_candidates composes a single contact sheet from different moments for comparison.

**Direction:** Use timestamped illustrative cells, explicitly labeled as examples.

**Implementation evidence:** `video_agent/tools/search_visual_moments; view_candidates`

### 15-sequence · 03:01.34–03:07.32 · Inspect actions in chronological order

**Narration:** Another presents frames…

**Visual:** Illustrative sequence diagram. view_sequence arranges frames from a time window in chronological order. Show a simple object moving across three frames.

**Direction:** Reuse inspection panel; ordered timestamps and one arrow, no looping animation.

**Implementation evidence:** `video_agent/tools/view_sequence`

### 16-vision · 03:07.32–03:17.48 · Vision observations + transcript evidence

**Narration:** A separate vision model analyzes these images and returns focused observations, which the main agent combines with transcript evidence to answer.

**Visual:** Agent data-flow diagram. Inspection grid → separate vision model → focused observations → main agent. Transcript evidence joins the same synthesis step.

**Direction:** Reuse agent map; highlight the vision handoff, then the merge.

**Implementation evidence:** `backend/video_agent/image_analysis.py; runner.py`

### 17-budget · 03:17.48–03:27.80 · Bound the work per answer

**Narration:** A fixed visual budget limits searches and inspections per answer. Once exhausted, the agent must use the evidence collected and acknowledge what it could not confirm.

**Visual:** Diagram + exact code view. At most 6 visual tool calls and 4 looks per answer. Once spent, later visual tools do no work; answer with collected evidence and state uncertainty.

**Direction:** Static budget counters and exact constants; avoid a fabricated execution trace.

**Implementation evidence:** `backend/video_agent/visual_budget.py`

### 18-citations · 03:27.80–03:38.42 · Validate timestamp support

**Narration:** Finally, a streaming filter removes timestamp citations outside the ranges returned by tools. This validates timestamp support.

**Visual:** Streaming-filter diagram. Retrieved span 02:10–02:40 accepts [02:18], drops [07:50]. Text streams through; only citation support is validated. ±1 second endpoint tolerance shown as implementation note.

**Direction:** One example before/after; a brief exact-code excerpt.

**Implementation evidence:** `backend/video_agent/citations.py`

### 19-workspace · 03:38.42–03:43.76 · One workspace around the video

**Narration:** The website brings the video, conversations, transcript, and chapters into one workspace. A personal library keeps saved videos accessible, so users can return to a video and continue exploring without starting over.

**Visual:** UI view from real recording. Actual website: video, transcript, chat and saved conversations, framed with restrained callouts. Chapter/summary access is annotated only where visible.

**Direction:** Clean cut to actual workspace; hold, no feature montage.

**Implementation evidence:** `promo-video/public/clips/v3/library_chats_pins.mp4, source 7.6s`

### 20-library · 03:43.76–03:51.97 · Persist knowledge. Resume exploration.

**Narration:** A personal library…

**Visual:** Screen recording. Actual personal library search → open saved video → reopen existing conversation.

**Direction:** Use source 0–11.3s, muted, with a held final frame if needed. End on workspace; no sales CTA.

**Implementation evidence:** `promo-video/public/clips/v3/library_chats_pins.mp4, source 0–11.3s`

## Source and accuracy notes

The visual-budget limits are current code defaults, not narrated numerical claims. The citation filter checks support for timestamp endpoints against retrieved spans (with one-second slack); it does not fact-check the answer text. Vision inspection grids go to a separate image-analysis model. The optional close-up tool can send images directly to the main agent; this video covers the two grid tools named in the narration. Azure is shown as storage, without implying that every model or the FastAPI runtime is hosted there. OCR is local and conditional on configuration.
