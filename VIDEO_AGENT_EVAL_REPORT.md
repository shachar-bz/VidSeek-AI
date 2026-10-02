# Video Agent Evaluation Report

- **Date:** 2026-10-02.
- **Agent under test:** `backend/video_agent` at `main` 81cb46f, model `gpt-6.1-sol` on the OpenAI Responses API, image model `gpt-6-luna`.
- **Scope:** a re-run of the 16 tests from 2026-09-30, plus two new visual "where and how long" tests (T17, T18). It checks tool choice, tool order, how tool results are used, grounding, and latency.
- **What changed since 2026-09-30:**
  - Scored search.
  - The outline paired with search for "where" questions.
  - The multi-part answer sections in the prompt.
  - The caption cue repair on `bdeac510` and `55705079`.
  - The model preload at startup.
  - Streaming answers with per-citation checks.
  - Retrieved spans persisted per message.

  The 2026-09-30 report and its follow-up notes are in git history.
- **Method:** each test ran once in the full suite. T17 and T18 also ran once earlier the same day, and both runs are reported. Every claim in every answer was checked against the database, and the visual answers against frames extracted every 1–3 s.
- **Code changes:** none. The agent implementation was not modified.
- **Follow-up, same day:** prompt fixes for issues 2–5 below were applied on `fix/video-agent-prompt-eval-issues` (ccdc9de), and T2, T3, T14, T15 and T17 were re-run twice each. T2, T3, T14 and T15 now pass in both runs; T17 is closer but still Partial. See §9.

## 1. Summary

| | |
|---|---|
| Tests | 18, on 6 videos |
| Pass | 13 |
| Partial (grounded, but incomplete or imprecise) | 3: T2, T15, T17 |
| Tool-path deviation (answer correct, tools unexpected and costly) | 1: T14 |
| Fail | 1: T18 |
| Hallucinated facts | 0 |
| Tool names or internals leaked in answers | 0 |
| Latency, all tests | median 9.7 s, mean 13.7 s, range 2.9–49.6 s |
| Latency, transcript-only tests | median 8.6 s, max 16.0 s |

Compared with 2026-09-30:

| | Better | Worse |
|---|---|---|
| Grades | T11 Partial → Pass. T14's answer is now complete, including the meringue session. T15 answers instead of asking. | T2 Pass (10-01 re-run) → Partial again. T15 Pass (10-01 re-run) → Partial, 3 of 4 desserts. |
| Data | T8 now cites the GPU line in its own moment [08:26–09:13], not 80 s early. | – |
| Rounds | T10 needed no rephrase: scored search found the padding note at once, 5 → 4 model requests. | T3 now reads all 5 chapters for a plain outline request, 8.7 → 14.8 s. |
| Cold starts | Gone. The first picture search took 0.99 s, where it took 12.7 s cold. | – |
| Streaming | Answer text now reaches the user as it is written. In T11 it is visible at 9.3 s of 16.0. | – |

What went well:

- **Grounding stayed sound,** including the bait questions.
  - T12, ray tracing: declined, and pointed to the nearest real content.
  - T13, a visual question on a video without a visual index: the prescribed message, with no tools.
  - T6, on-screen text: the years read from the slide, not from the speech.
- **The "where" pairing works.** Search and outline ran in the same first round in T2, T11, T12, T14, T15 and T17.
  - In T14, the outline recovered the meringue session that the search missed.
  - In T17, it recovered the custard chapter.
- **The section rule works.** T11 read all 3 seam-carving chapters in one round and covered each of them.
- **The visual recipe was followed.** T9 used one close-up and no search. T16 used a contact sheet, then sequences. T17 used its last look to narrow a window.

What to fix (details in §6–§8):

1. **"Visual analysis isn't available" now blocks questions that speech can answer.** In its second run, T18 ("where can we find an example of how image details look like") called no tools and answered only with the message. In its first run it did search, but it pointed to the wrong slide. The example is at 17:08, and the word "details" appears only on screen. The video's visual index is `failed` (`visual_indexing_interrupted`), although its file is stored and readable.
2. **The multi-candidate rule is not applied reliably.**
   - T2 is the prompt's own example ("who coined the term?"). Both terms were in the tool results, and the agent answered only one.
   - T15 left out the meringue.
   - Both passed on 2026-10-01, so this is run-to-run variance in following the rule, not missing retrieval.
3. **The visual routing is still too broad (T14).** The picture search and a contact sheet ran for a speech-answerable "where do they work on X". They cost about 9 s and supplied no citation.
4. **Outline requests over-read (T3).** The agent read all 5 chapters for a question the outline answers by itself. That is one extra round and 6 s.
5. **Duration answers come out at the lower bound (T17).** With frames 6–8 s apart, both runs understated the custard whisking: 7 s and "at least 8 s", against about 12 s.
6. **Scored search can mark irrelevant hits as standing out (T12).** For a topic the video lacks, 2 off-target moments came back not marked `weak`. The score is relative to the video's own moments. The agent judged them correctly anyway.

## 2. Setup

- **Harness:** each test ran through the production `PydanticConversationAgentRunner.stream()` around `build_agent()`. A proxy wrapped the agent to timestamp every pydantic-ai event and keep the raw tool results.
  - Citations went through the production streaming `CitationFilter`.
  - The HTTP/SSE layer was not exercised.
- **Per-run setup:** `has_comments` and `visual_availability` were computed the same way as in `api/routes/conversations.py`. The viewer position was set where a test needs it:
  - T4: playing at 11:00.
  - T9: paused at 37:12.
- **Conversation state:** every test started with empty history. Nothing was written to the database.
- **Order and warm-up:** the tests ran one after another in a single process. Before timing, both embedding models were loaded the way the API's startup preload does (`api/model_preload._load_models`), and the DB pool was opened. That took 6.8 s.
- **Environment:** a macOS (Apple Silicon) dev machine, the remote Azure Postgres and the OpenAI API. The 2026-09-30 run was on a Windows machine, so small latency differences are not meaningful.
- **Limits:**
  - Each test ran once (T17 and T18 twice), so a single failure is a lead, not a rate.
  - All videos are English.
  - `get_viewer_comments`, untimed transcripts and multi-turn follow-ups were not tested.
  - Citations the filter dropped were not counted: the harness saw only the filtered answer text.

### Videos

| id | Content | Length | Visual index | Tests |
|---|---|---|---|---|
| `3b03286e` | Talk "Goodbye Tokenmaxxing" (has YouTube comments) | 8 min | skipped | T1, T2 |
| `0d4377ef` | Nand to Tetris Part II, course overview lecture | 21 min | skipped | T3, T4 |
| `bdeac510` | TED talk on climate innovation (Xu Hao), titled "Video" | 13 min | ready, OCR now complete (78 of 78 keyframes) | T5, T6 |
| `55705079` | TED interview, Chris Anderson and Sam Altman, titled "Prismic Toolbar iFrame" | 47 min | ready, with on-screen text | T7, T8, T9 |
| `75c17869` | Introduction to Computer Graphics 14:15–15:15 (Ofir), TA recitation | 61 min | failed (`visual_indexing_interrupted`) | T10–T13, T18 |
| `6aa8f5ad` | 2004 Food Network broadcast with ads (Internet Archive) | 34 min | ready, with on-screen text | T14–T17 |

`bdeac510` and `55705079` were re-segmented by the caption repair on 2026-10-01. Their expected answers were re-checked against the new data before grading.

## 3. Results at a glance

Tools separated by `+` ran in the same round, in parallel. Tools separated by `→` ran in sequence.

| Test | Behavior | Tools called | Expected | Grade | Latency (09-30 → now) |
|---|---|---|---|---|---|
| T1 | Basic info | `get_video_info` | same | Pass | 4.7 → 5.5 s |
| T2 | Ambiguous ("the term") | search + outline | search + outline, answer both terms | Partial | 4.6 → 8.1 s |
| T3 | Outline | outline → 5 × chapter | outline | Pass, over-read | 8.7 → 14.8 s |
| T4 | Viewer position, speech | outline → chapter → memory | same | Pass | 10.7 → 9.7 s |
| T5 | Specific fact | search | same | Pass | 4.4 → 4.9 s |
| T6 | On-screen text | screen text + search | same | Pass | 5.5 → 6.1 s |
| T7 | Basic info, misleading title | info → search | info → search or outline | Pass | 7.1 → 8.3 s |
| T8 | Context within a chapter | search → memory context | same | Pass | 8.5 → 8.6 s |
| T9 | Viewer position, visual (paused) | `view_frames_closeup` | same | Pass | 7.7 → 6.9 s |
| T10 | Context across a chapter boundary | search → memory context → chapter | same | Pass | 11.6 → 10.1 s |
| T11 | Larger section (3 chapters) | search + outline → 3 × chapter | same | Pass | 15.7 → 16.0 s |
| T12 | Not in the video | search + outline → search + chapter | search ×1–2 | Pass | 7.3 → 11.4 s |
| T13 | Visual question, index unavailable | none | none | Pass | 2.2 → 2.9 s |
| T14 | Finding when | search + outline + picture search → 2 × chapter + contact sheet | search + outline → chapters | Deviation | 28.1 → 25.3 s |
| T15 | Ambiguous (several candidates) | search + outline → 2 × chapter + search | same, answer all 4 | Partial | 6.1 → 12.5 s |
| T16 | Action or sequence (visual) | picture search + search → contact sheet → 3 × sequence | same | Pass | 44.9 → 39.0 s |
| T17 | Where and how long (visual) | picture search + search + outline → contact sheet + chapter → 2 × sequence + memory → sequence | same, with sequences on the real sessions only | Partial | new, 49.6 s (earlier run 40.7 s) |
| T18 | Where on screen, index unavailable | none (earlier run: search + outline) | search + outline → chapter, answer from speech | Fail | new, 6.6 s (earlier run 9.4 s) |

## 4. Per-test detail

Times are in seconds from the start of the run.

### T1: Basic info (Pass)
- **Query:** "What's this video's title, and which site is it from?"
- **Calls:** `get_video_info` at 3.4 s.
- **Answer:** "titled 'Goodbye Tokenmaxxing: From AI Usage to Agentic AI Outcomes' and is from YouTube."
- **Check:** matches the tool's cleaned title, and no channel was invented. The comments tool was offered and not called.

### T2: Ambiguous term (Partial)
- **Query:** "Who coined the term?"
- **Calls:** `memories_semantic_search` ("Who coined a term or introduced a name, and which term was it?") and `get_video_outline` together.
  - The search returned 3 moments, all marked `weak`. They included valuemaxxing [04:24–05:16] and tokenmaxxing [00:43–01:49].
  - The outline has a chapter titled "From Tokenmaxxing to Valuemaxxing".
- **Answer:** "If you mean 'valuemaxxing,' the video credits Mark Boroditsky, CRO of Nebus, with coining the term. [04:24–05:16]"
- **Check:**
  - The fact and the citation are correct.
  - It does not say that tokenmaxxing, the other candidate in its own results, is credited to no one. The prompt's "Questions With More Than One Possible Meaning" uses this very question as its example, and the 2026-10-01 re-run passed it.
  - This is a lapse in following the rule. Retrieval did its part.

### T3: Outline (Pass, over-read)
- **Query:** "Outline this video's sections with timestamps."
- **Calls:** `get_video_outline`, then `get_chapter_context` on all 5 chapters in one round.
- **Answer:** all 5 chapters as a table, with ranges identical to the outline's: [00:10–04:21], [04:23–12:03], [12:04–15:18], [15:19–17:59], [18:01–20:54]. The one-line descriptions are more detailed than on 09-30, and all match the summaries.
- **Check:**
  - The answer is correct.
  - The chapter reads added a round, 479 output tokens and 6 s, for detail the outline's summaries already carried.
  - No prompt section covers "outline the video", and the model treated it like "Questions About a Part of the Video".

### T4: Viewer position, spoken content (Pass)
- **Query:** "What's being talked about right now?" The player was playing at 11:00.
- **Calls:**
  1. `get_video_outline` at 1.8 s.
  2. `get_chapter_context` on ch1.
  3. `get_memory_context` on the moment covering 11:00.

  This is the prompt's timestamp recipe, now written down; on 09-30 the model added the third step on its own.
- **Answer:** "the VM translator project … build this translator during the first two weeks, exploring ideas similar to those behind Java's JVM and Microsoft's CLR. [09:27–11:14]"
- **Check:** correct, and it avoids the operating-system section that starts at 11:15.

### T5: Specific fact (Pass)
- **Query:** "How much solar radiation does Moguang's cooling material reflect?"
- **Calls:** `memories_semantic_search`.
- **Answer:** "reflects 93% of solar radiation back. [09:00–10:28]"
- **Check:**
  - Correct. The line is at 09:16 inside moment 6 [09:00–10:28] of the repaired data.
  - It did not fall for the "80 percent" distractor at 09:44.
  - The visual tools were offered and not used.

### T6: On-screen text (Pass)
- **Query:** "The timeline slide about ethanol shows two years. Which years?"
- **Calls:** `search_screen_text` and `memories_semantic_search` in the same round.
- **Answer:** "The two years are 1784 and 1875. [01:10-01:22]"
- **Check:** correct. The keyframe OCR at 01:10 reads "1784 | 1875 | … more than 200 years", while the speech says only "the 1700s". The tool no longer reports unread keyframes.

### T7: Basic info with a misleading title (Pass)
- **Query:** "What is this video, and who is talking?"
- **Calls:** `get_video_info`, then `memories_semantic_search`.
- **Answer:** "a TED interview with Sam Altman, hosted by Chris Anderson … The two people speaking are Chris Anderson, asking the questions, and Sam Altman, answering them. [00:00–00:52]"
- **Check:**
  - Correct. The names come from the transcript's speaker labels.
  - Unlike on 09-30, it no longer remarks that "Prismic Toolbar iFrame" is a technical label. The question didn't ask for that, so nothing is lost.

### T8: Context within a chapter (Pass)
- **Query:** "Right before Anderson asks about ChatGPT's growth, what was Altman describing, and why?"
- **Calls:** `memories_semantic_search`, which returned the growth moment [09:13–10:04]. Then `get_memory_context` on it with `context_range=2`.
- **Answer:** Altman described spending "all day" begging for GPUs because OpenAI was severely compute-constrained. He was responding to Anderson's question about whether expensive scaling could keep OpenAI's lead against DeepSeek, and noted that DeepSeek's launch hadn't dented their growth. [08:26–09:13]
- **Check:**
  - Correct. The transcript has the DeepSeek question at 08:41–08:58, the GPU line and "so incredibly constrained" at 09:00–09:13, and "Tell us about the growth" at 09:13.
  - **The data fix shows:** the citation now covers the GPU line (09:00). On 09-30 the only citation available landed 80 s early.

### T9: Viewer position, visual, paused (Pass)
- **Query:** "What is this?" The player was paused at 37:12.
- **Calls:** `view_frames_closeup` (0.7 s), with no search.
- **Answer:** "a post from Sam Altman announcing the birth of his baby boy, with a close-up photo of the newborn holding an adult's finger … in the NICU, but is doing well … 'I have never felt such love.' Below the screen, two speakers are seated onstage. [37:12]"
- **Check:** matches the keyframe OCR at 37:08 and 37:18 ("welcome to the world, little guy! … nicu … i have never felt such love").

### T10: Context across a chapter boundary (Pass)
- **Query:** "Right after the note about padding the image with zeros, what does the recitation move on to, and how important does the TA say the padding note is?"
- **Calls:**
  1. `memories_semantic_search` with the same kind of overloaded query as on 09-30. This time the padding moment [34:21–35:00] came back as a hit, not marked `weak`.
  2. `get_memory_context` with `context_range=1`.
  3. `get_chapter_context` on "Seam-carving basics".
- **Answer:** seam carving [35:02–37:25]. The TA treats the padding as "a minor side note … 'I don't think it should concern you too much'", and calls it an edge case [34:21–35:00].
- **Check:** the quote is verbatim. It took one round fewer than on 09-30, because scored search made the rephrase unnecessary.

### T11: Larger section (Pass)
- **Query:** "Summarize the seam carving part of the lecture."
- **Calls:** `memories_semantic_search` + `get_video_outline`, then `get_chapter_context` on all 3 seam-carving chapters (ch3, ch4, ch5) in one round.
- **Answer:** six bullets in video order, covering:
  - why seam carving;
  - what a seam is;
  - the DP cost matrix and pixel energy;
  - forward-looking costs;
  - backtracking, versus the greedy mistake;
  - implementation: the reference matrix, the output image, NumPy/Jupyter and the optional Numba [56:03–58:14] [58:15–59:30].
- **Check:** every claim matches the moment summaries. The part it missed on 09-30, the NumPy/Numba material, is covered.

### T12: Answer not in the video (Pass)
- **Query:** "How does the lecture explain ray tracing?"
- **Calls:**
  1. `memories_semantic_search` + `get_video_outline`. The search returned 2 moments **not** marked `weak`: a student asking for lecture PDFs [06:34–07:49] and the recitation's opening [00:43–02:44]. Neither is about ray tracing.
  2. A rephrased search, whose 3 hits were all marked `weak`, plus `get_chapter_context` on "Computer graphics and digital images".
- **Answer:** "I couldn't find an explanation of ray tracing in this video after searching both for the term and for tracing light through a 3D scene. The closest related discussion is the general explanation of rendering … It doesn't explain a ray-tracing algorithm in that discussion. [09:45–12:05]"
- **Check:**
  - Correct: the transcript never mentions it.
  - It now points to the nearest content (rendering, [09:46–12:05]), which 09-30 left out. It stopped after the two searches the prompt allows.
  - The first search shows scored search's blind spot: on an absent topic, some moments still stand out against the rest of the video.

### T13: Visual question, index unavailable (Pass)
- **Query:** "What's written on the slide when he explains convolution?"
- **Calls:** none, in a single model request.
- **Answer:** "Visual analysis isn't available for this video, so I can't read the slide. I can help you find or summarize what he says about convolution instead."
- **Check:** the prescribed message, with no guessing from the transcript.

### T14: Finding when a topic is discussed (Deviation: answer correct, tool path costly)
- **Query:** "Where in the video do they work on the pumpkin pies?"
- **Calls:**
  1. `memories_semantic_search` + `get_video_outline` + `search_visual_moments` (0.99 s, warm). The search hits were the finale display, the baking explanation and the menu intro.
  2. `get_chapter_context` on "Pumpkin Pie in Acorn Squash Shells" and on "Meringue for the Squash Pumpkin Pies", plus `view_candidates` on 6 frames (8.3 s).
- **Answer:** "two main sections", followed by four items:
  - hollowing the squash [13:31–14:41];
  - the filling [14:42–16:52];
  - the baking explanation [17:03–17:22];
  - the meringue [20:54–22:36].

  Then "Start at 13:31".
- **Check:**
  - **Locations: all correct and complete.** The meringue session, which the 09-30 search missed, came from the outline's chapter title.
  - **The answer contradicts itself:** "two main sections", then four items.
  - **Tool path:** every citation is a moment span from the chapter reads. The picture search and the contact sheet added about 9 s and supplied nothing.
  - The prompt's visual routing ("where, when, or what happens (… an action)") still sends this question to the visual tools. That is §8.4 of 09-30, still open.

### T15: Ambiguous question with several candidates (Partial)
- **Query:** "How long does it bake?"
- **Calls:** `memories_semantic_search` + `get_video_outline`, then 2 × `get_chapter_context` + a second search.
- **Answer:**
  - The fruit crisp cooks 45 min in all: 30 over coals, then 15 with coals on the lid [05:21–06:18].
  - The bread pudding and crème caramel "bake during the break", with no time given [09:14–09:55].
  - The pumpkin pies "also bake during a break, with no specific duration" [20:54–22:36].
- **Check:**
  - **True as far as it goes.** It answers without asking, as the prompt now says.
  - **It leaves out the meringue:** "I'm going to let that cook for few minutes" (22:46). The 10-01 re-run included it.
  - **It also leaves out the oven setting the video gives for the pies:** about 215° with water in the tray [17:03–17:18].
  - It covers 3 of the 4 candidates.

### T16: An action or sequence (Pass)
- **Query:** "Show me how the acorn squash gets hollowed out: what happens on screen, step by step?"
- **Calls:**
  1. `search_visual_moments` + `memories_semantic_search`.
  2. `view_candidates` on 4 times (4.6 s).
  3. Three `view_sequence` calls in one round: 13:38–13:56 (6 frames), 13:56–14:24 (9 frames) and 14:24–14:36 (4 frames). They took 11.1 s together.

  That used 5 of 6 visual calls and 4 of 4 looks.
- **Answer:** five steps:
  1. Cut off an end with a large knife, leaving a scalloped cap [13:38–13:52].
  2. Push the spoon into the opening.
  3. Scrape around the walls.
  4. Show the hollow shell [13:56–14:20].
  5. Place it in the roasting pan and arrange the shells [14:24–14:32].
- **Check:** frames every 3 s match each step:
  - knife at 13:38–13:53;
  - spoon in the opening at 14:05–14:08;
  - hollow shell held up with its cap at 14:14;
  - into the pan at 14:17;
  - the tray arranged at 14:23–14:35.

  Every citation came from a look. It was 6 s faster than on 09-30, because the sequences ran in one round instead of two.

### T17: Where he whisks the eggs, and for how long (Partial) — new
- **Query:** "where in the video we see the man whisk the eggs and how much time he do it?"
- **Ground truth** (frames every 1 s):
  - **Custard for the crème caramel and bread pudding:**
    - The whisk goes into the egg bowl at 08:30, and the sugar is poured at 08:32–08:33. At 08:34 he turns to the stove.
    - He whisks the eggs and sugar from 08:37 to 08:49, about 12 s, with a wide shot at 08:42–08:44.
    - He whisks again briefly as the hot milk goes in, at 08:54–08:58.
    - Speech: "I have here some yolks, eggs, and sugar. I mix all that together" (08:20–08:35).
  - **Pumpkin filling for the squash shells:**
    - "some eggs. I have a whisk around here" (14:43).
    - He whisks the eggs from 14:48, then keeps whisking with pauses as the sugar, spices, milk, cream and pumpkin go in, until about 16:00.
    - That spans about 70 s, of which roughly 45–55 s is active whisking.
- **Calls (suite run):**
  1. `search_visual_moments` + `memories_semantic_search` + `get_video_outline`.
     - The picture search led with 14:58 and 14:48, then 09:06, a false lead at 17:14, 08:44 and 09:48.
     - The transcript search missed the custard moment: the query packed in "how long", and 3 of the 4 hits were the sugar corn and the meringue.
  2. `view_candidates` on 6 frames (8.3 s) + `get_chapter_context` on the custard chapter, which the outline had named.
  3. `view_sequence` over 08:18–09:12 and over 14:40–15:56, each with 9 frames, + `get_memory_context` on the custard moment.
  4. A narrower `view_sequence` over 08:30–08:46 with 9 frames.

  That used 5 of 6 visual calls and 4 of 4 looks.
- **Answer (suite run):**
  > - **Eggs for the custard:** Jump to **08:38**. He visibly whisks through **08:46**—at least **8 seconds**, though he is still whisking at the end of that interval. [08:38–08:44] [08:46]
  > - **Egg mixture for the pumpkin pies:** He whisks around **14:49–15:18**, pauses, then resumes at **15:46–15:56**. That's roughly **40 seconds across those stretches**, not one continuous whisk. [14:40–14:49] [14:59] [15:08–15:27] [15:46–15:56]
- **Check:**
  - **Where: correct.** Both sessions were found, each with its dish. Every citation came from a look.
  - **How long: understated, but hedged.**
    - Custard: "at least 8 s" against about 12 s. Its last window ended at 08:46, so it couldn't see the whisking continue to 08:49.
    - Pumpkin: "roughly 40 s" against about 45–55 s of active whisking. It missed the stretch from about 15:30 to 15:42, which fell between frames.
- **Earlier run (40.7 s):** the same first two rounds, then three parallel sequences. One of them went to the 17:14 false lead (a stand mixer), which the contact sheet had marked `present: yes`. That left no look to narrow the custard, which it put at "about 7 seconds". The suite run skipped 17:14 and used the fourth look on the custard, and its estimate was closer.
- **Latency:** 49.6 s, with the first answer text at 45.5 s. Tool time was 22.3 s: the contact sheet (8.3 s), the parallel sequences (about 10 s) and the narrow sequence (6 s). Model time was 27.3 s over 5 requests.

### T18: Where there is an example of what image details look like (Fail) — new
- **Query:** "where in the video we can find an exampe of how image details looks like"
- **Ground truth:**
  - **The slide:** "Image Filtering": original − smoothed = ?. It is up from about 15:40.
  - **The "details" image:** at 17:08 the "?" is replaced by the result, labelled **"details"**: an edge image of the woman in the hat. It stays on screen until 19:27.
  - **The speech:** "this is what I get. I get the edges" (17:09). "We can still see the woman, the hat, the actual content of the image" (17:21–17:43).
  - **The memory:** 9, [16:15–19:30]. Its summary reads "edges as large changes between neighboring pixels … extracting them by subtracting a blurred image".
  - **The word "details":** spoken nowhere in the recitation. It appears only on the slide.
- **Calls (suite run):** none, in a single model request.
- **Answer (suite run):** "Visual analysis isn't available for this video, so I can't verify where an example of what image details look like is shown. I can help find where the speaker **discusses image details** instead."
- **Earlier run (9.4 s):**
  - It called `memories_semantic_search` + `get_video_outline`. The 2 search hits were the vertical-derivative example [19:31–23:37] and the averaging-filter exercise; memory 9 was not among them.
  - Its answer, "try 19:31 … horizontal edges, bright and dark lines", points to the next slide (a brick wall and its vertical derivative). That is an edge example, but not the "details" one.
- **Check:**
  - Neither run reached 17:08.
  - The suite run is the worse of the two. The visual-unavailable section says: "When the user asks about what is shown … tell them … Never answer such a question from the transcript." Read literally, "where can we find an example of …" is about what is shown, so the agent stopped without searching. That section also says "Answer any part of the question about what was said as usual", yet the agent only offered to.
  - The earlier run searched but ranked the wrong moment first. The speech never says "details", and it did not scan the chapter the outline matched ("Image filters and convolution … blur and edge detection"). One `get_chapter_context` would have listed memory 9's "subtracting a blurred image".
  - **With a ready visual index, `search_screen_text` for "details" would have found the slide directly.** The index is `failed` with `visual_indexing_interrupted`, yet the video's file is in Blob Storage and its frames extract fine (they were used for the ground truth above).

## 5. Latency

### Per test

| Test | Total s | 1st tool s | 1st answer text s | Tool time s | Model time s | Model requests | Tool calls | Input tok | Cached tok | Output tok |
|---|---|---|---|---|---|---|---|---|---|---|
| T1 | 5.5 | 3.4 | 4.8 | 0.0 | 5.5 | 2 | 1 | 5662 | 2788 | 49 |
| T2 | 8.1 | 2.6 | 7.3 | 0.2 | 7.9 | 2 | 2 | 6798 | 5553 | 203 |
| T3 | 14.8 | 2.8 | 10.9 | 0.1 | 14.7 | 3 | 6 | 10143 | 7647 | 479 |
| T4 | 9.7 | 1.8 | 8.0 | 0.1 | 9.6 | 4 | 3 | 13434 | 8777 | 173 |
| T5 | 4.9 | 2.0 | 4.0 | 0.1 | 4.8 | 2 | 1 | 9363 | 8923 | 62 |
| T6 | 6.1 | 3.4 | 5.4 | 0.3 | 5.8 | 2 | 2 | 9763 | 8922 | 112 |
| T7 | 8.3 | 2.3 | 6.3 | 0.2 | 8.1 | 3 | 2 | 14595 | 13459 | 134 |
| T8 | 8.6 | 2.4 | 6.2 | 0.1 | 8.4 | 3 | 2 | 15363 | 13811 | 167 |
| T9 | 6.9 | 2.1 | 4.8 | 0.7 | 6.2 | 2 | 1 | 9821 | 4505 | 103 |
| T10 | 10.1 | 2.3 | 8.9 | 0.2 | 9.9 | 4 | 3 | 15538 | 12892 | 210 |
| T11 | 16.0 | 3.9 | 9.3 | 0.1 | 15.9 | 3 | 5 | 11174 | 8563 | 586 |
| T12 | 11.4 | 3.6 | 9.2 | 0.2 | 11.1 | 3 | 4 | 12351 | 8639 | 256 |
| T13 | 2.9 | – | 2.0 | 0.0 | 2.9 | 1 | 0 | 2402 | 2385 | 34 |
| T14 | 25.3 | 4.3 | 22.1 | 9.3 | 15.9 | 3 | 6 | 18744 | 15488 | 405 |
| T15 | 12.5 | 3.1 | 9.5 | 0.3 | 12.2 | 3 | 5 | 20228 | 15795 | 316 |
| T16 | 39.0 | 3.7 | 32.5 | 15.9 | 23.1 | 4 | 6 | 25783 | 21309 | 602 |
| T17 | 49.6 | 4.0 | 45.5 | 22.3 | 27.3 | 5 | 9 | 45113 | 37008 | 690 |
| T18 | 6.6 | – | 5.6 | 0.0 | 6.6 | 1 | 0 | 2408 | 2405 | 176 |

- **Model time** is the total minus the time any tool was running.
- **"1st answer text"** is when the first answer text reached the caller. Since the streaming change, this is when the user starts reading. On 09-30 the answer was buffered, and the user saw nothing before **Total**.

### Per tool

| Tool | Calls | Median | Max |
|---|---|---|---|
| `get_video_info` | 2 | 0.03 s | 0.03 s |
| `get_video_outline` | 8 | 0.03 s | 0.04 s |
| `get_chapter_context` | 16 | 0.03 s | 0.08 s |
| `get_memory_context` | 4 | 0.07 s | 0.08 s |
| `memories_semantic_search` | 14 | 0.09 s | 0.19 s |
| `search_screen_text` | 1 | 0.31 s | 0.31 s |
| `search_visual_moments` | 3 | 0.19 s | 0.99 s (first call, warm) |
| `view_frames_closeup` | 1 | 0.7 s | 0.7 s |
| `view_candidates` | 3 | 5.8 s | 8.3 s |
| `view_sequence` | 6 | 10.4 s | 11.1 s |

### Observations

1. **Model round trips still dominate.**
   - Model time is 80% of the wall time across the suite.
   - It averages 3.9 s per model request, answer writing included.
   - The first tool call arrives after a median of 3.0 s, against 2.2 s on 09-30. Every first request now carries a longer system prompt.
2. **Streaming hides part of the writing.** For long answers, the text now starts well before the end. In T11 it starts at 9.3 s of 16.0, and in T3 at 10.9 of 14.8.
3. **The cold starts are gone.** The first picture search of the process (T14) took 0.99 s, where it took 12.7 s cold on 09-30. The preload took 6.8 s at startup, off the request path.
4. **The multi-part rules cost rounds.** T2 (+3.5 s), T3 (+6 s), T12 (+4 s) and T15 (+6 s) got slower than on 09-30 through the extra outline and chapter round. In T11 and T15 that round buys completeness; in T3 it buys nothing.
5. **Visual answers cost 25–50 s.** A sequence takes about 10 s and a contact sheet about 6–8 s, all image-model time. T16 and T17 spent 16–22 s in tools. T14 spent 9 s on visual tools it didn't need.

## 6. Tool-call behavior

| Check | Result |
|---|---|
| Correct tools chosen | 15 of 18 as expected. T14 took the visual path, T3 over-read the chapters, and T18 called nothing. |
| Correct order | Yes in all 18. Independent calls were batched (T2, T6, T11, T12, T14–T17), and dependent calls were sequential. |
| Unnecessary calls | T3's 5 chapter reads. T14's picture search and contact sheet. In T17's earlier run, the sequence on the 17:14 false lead. |
| Correct use of tool results | Mostly. T8 and T10 read the neighbouring moment and the chapter boundary correctly. T12 rejected 2 off-target hits that were not marked `weak`. T6 took the answer from the screen text. **But** T2 and T15 had every candidate in their results and answered only some. |
| Grounded final answers | All 18. No outside facts, and no invented timestamps. |
| Citations | Every citation in the final answers is inside a span a tool returned, and was correct by hand. Dropped citations were not counted (§2). |
| Offered-tool restraint | The comments tool was not called in T1 or T2. The visual tools were not used for speech questions in T5 or T7. They were used for one in T14. |
| Internal leakage | None. |

Problems found in the data (not the agent):

- **`75c17869`'s visual index is `failed` (`visual_indexing_interrupted`).** The video file is stored and its frames extract fine. This one state cost T13 (correctly declined) and T18 (failed), and it hides every slide of a slide-based lecture from the agent.
- **The caption repair held.** T5 and T8 cite the repaired moments correctly. Their memories and chapters were rebuilt, and nothing in the re-run contradicts them.

## 7. Prompt and tool behavior against what they claim

| # | Issue | Where | Seen in the runs |
|---|---|---|---|
| 1 | **The visual-unavailable section reads as "don't search" for "where is X shown".** "Never answer such a question from the transcript" covers what the screen shows, but the model applied it to locating an example that the speech also describes. | `prompt.py`, `_visual_not_ready_prompt` | T18, suite run: no tools; the answer only offered to search. |
| 2 | **The multi-candidate rule is followed unevenly.** The rule and its example match T2 word for word. | `prompt.py`, "Questions With More Than One Possible Meaning" | T2: both terms retrieved, one answered. T15: 3 of 4 desserts. Both passed on 10-01. |
| 3 | **The visual routing is broader than intended** (09-30 §7 issue 5, still open). | `prompt.py`, visual section | T14: 9 s of visual tools, none of them cited. |
| 4 | **No rule covers "outline the video".** The model fell back on the part-of-the-video recipe and read every chapter. | `prompt.py` | T3: one extra round, 6 s. |
| 5 | **Scored search is relative only.** The z-score is computed against the video's own moments, so on an absent topic the least-bad moments still pass z >= 1.5 and come back not marked `weak`. | `backend/services/memory_search.py` | T12: 2 off-target hits not marked `weak`. The model judged them correctly, but the `weak` flag can't be relied on for "not in the video". |
| 6 | **A sequence can't measure a duration finer than its frame spacing.** With 9 frames over a 54–78 s window, the frames are 6–8 s apart. | `view_sequence`, visual prompt | T17: both runs reported the lower bound. The narrower last look in the suite run helped. |
| 7 | **The citation check is still loose** (09-30 §7 issue 4). Any time inside any retrieved span passes, chapters included. | `citations.py` | Not triggered: every citation was also correct by hand. |

## 8. Recommendations

Ordered by expected impact.

1. **Re-index `75c17869`, and make an interrupted visual index recover.**
   - Re-run its visual indexing, then re-run T13 and T18. With screen text, T18 should find "details" at 17:08.
   - Make `visual_indexing_interrupted` retry or resume instead of staying `failed`. An interrupted OCR pass already has `resume_keyframe_text`; the index build needs the same.
2. **Narrow the visual-unavailable rule (issue 1).** When the picture can't be searched and the user asks *where* something is shown, still search the speech and the chapters, and answer where it is discussed, after the prescribed message. Keep the ban on describing the picture from the transcript.
Recommendations 3–6 were applied after this report; their re-run is in §9.

3. **Make the multi-candidate answers reliable (issue 2).**
   - Before answering, name each candidate found, and say for each one what the video states or that it states nothing.
   - Re-run T2 and T15 several times, since a single run can't tell a 50% rule from a 90% one.
4. **Narrow the visual routing (issue 3; 09-30 §8.4).** A "where do they do X" question that the speech narrates should go to search plus outline first, and to the visual tools only when speech can't place it. This saves about 9 s on T14 and 20–40 s on similar questions.
5. **Answer outline requests from the outline (issue 4).** Add one line: "outline the video" or "list the sections" is answered from `get_video_outline` alone. This saves a round on T3.
6. **For "how long" questions (issue 6):**
   - Measure the strongest lead first, with a narrow `view_sequence` over the action's own window.
   - Keep one look to tighten a boundary.
   - Don't spend a sequence on a lead the transcript doesn't support, such as 17:14 in T17.
   - Give the answer as a range bounded by the frame spacing ("about 8–14 s"), not as the lower bound alone.
7. **Add an absolute floor to scored search (issue 5).** Mark a hit `weak` when its similarity is below a fixed floor, even if it stands out within the video. Then "nothing relevant" stops depending on the model's judgment alone.
8. **Tighten the citation check (issue 7; 09-30 §8.6).** Accept citations only inside moment-level or look-level spans, not chapter ranges.

## 9. Re-run after the prompt fixes

- **Code under test:** `fix/video-agent-prompt-eval-issues` at ccdc9de, the same model, harness and warm-up as §2.
- **Tests:** T2, T3, T14, T15 and T17, each run twice (runs A and B), one process per run.
- **What changed** (recommendations 3–6):
  - **Multi-candidate questions:** after listing the chapters, read every listed chapter that no search hit falls in; answer with one line per candidate, saying what the video states about it or that it states nothing; never answer only one with "if you mean X".
  - **Visual routing:** a where/when question about an activity the speaker narrates is a "Where Is This Discussed?" question, answered without the visual tools. The picture is searched only when the first round lists no chapter it can be in.
  - **Outline:** the `get_video_outline` docstring now says it shows the video's structure, and that it is used to understand how the video is organized, locate a topic or identify its sections. The prompt is unchanged for this.
  - **How long:** a new "How to investigate" bullet. Leads the transcript supports come first. The last look brackets the action, from the frame before it to the frame after it. Durations are given as a range from the frame spacing, or as a rough estimate when the looks run out.
  - **Search wording:** "Search for the thing itself ("whisking eggs"), not for what the user asks about it ("how long", "who")."

### Results

| Test | Before (§3) | Run A | Run B | Grade |
|---|---|---|---|---|
| T2 | Partial, 8.1 s | Pass, 11.8 s | Pass, 22.5 s | Partial → **Pass** |
| T3 | Pass, over-read, 14.8 s | Pass, outline only, 7.4 s | Pass, outline only, 7.1 s | Pass → **Pass**, one round saved |
| T14 | Deviation, 25.3 s | Pass, no visual tools, 11.5 s | Pass, no visual tools, 12.9 s | Deviation → **Pass** |
| T15 | Partial, 3 of 4, 12.5 s | Pass, 4 of 4, 16.0 s | Pass, 4 of 4, 16.1 s | Partial → **Pass** |
| T17 | Partial, 49.6 s | Partial, 44.2 s | Partial, closer, 48.6 s | Partial → Partial |

| Test, run | Path | Total s | 1st tool s | 1st answer text s | Tool time s | Model requests | Tool calls | Output tok |
|---|---|---|---|---|---|---|---|---|
| T2 A | search + outline → chapter | 11.8 | 3.8 | 10.3 | 0.2 | 3 | 3 | 221 |
| T2 B | search + outline → 2 × chapter + search | 22.5 | 6.6 | 21.0 | 0.3 | 3 | 5 | 316 |
| T3 A | outline | 7.4 | 1.9 | 3.7 | 0.0 | 2 | 1 | 277 |
| T3 B | outline | 7.1 | 1.7 | 3.9 | 0.0 | 2 | 1 | 223 |
| T14 A | search + outline → chapter | 11.5 | 2.7 | 8.1 | 0.2 | 3 | 3 | 314 |
| T14 B | search + outline → chapter | 12.9 | 3.4 | 9.1 | 0.1 | 3 | 3 | 317 |
| T15 A | search + outline → 4 × chapter → 2 × memory | 16.0 | 3.5 | 13.1 | 0.2 | 4 | 8 | 474 |
| T15 B | search + outline → 3 × chapter → 3 × memory | 16.1 | 3.5 | 13.1 | 0.2 | 4 | 8 | 478 |
| T17 A | picture search + search → contact sheet → 3 × sequence + search | 44.2 | 2.8 | 39.2 | 19.1 | 4 | 7 | 605 |
| T17 B | picture search + search → contact sheet → 2 × sequence + search → sequence | 48.6 | 3.3 | 45.3 | 25.0 | 5 | 7 | 611 |

### Per test

- **T2, "Who coined the term?" (Pass, both runs).**
  - Both answers give one line per term: valuemaxxing is credited to Mark Boroditsky [04:24–05:16]; for tokenmaxxing the video names no originator [00:42–01:48]. Neither uses "if you mean".
  - **Cost:** the read step adds a round. Run B is the slowest at 22.5 s, but its tools took 0.3 s: the model's responses were slow, and its first tool call alone came at 6.6 s against 2.6 s before.
- **T3, outline (Pass, both runs).** One `get_video_outline` call and nothing else. The answer has all 5 chapters with the same ranges as before, in half the time (14.8 → 7.1–7.4 s).
- **T14, "Where … do they work on the pumpkin pies?" (Pass, both runs).**
  - No visual tools in either run. Every location is found: the squash [13:31–14:41], the filling [14:42–16:52], the baking explanation [17:03–17:22], the meringue [20:54–22:36], plus the finale [30:15–30:38]. 25.3 → 11.5–12.9 s.
  - Run A still opens with "two main sections" and lists five items (out of scope here); run B does not.
- **T15, "How long does it bake?" (Pass, both runs).**
  - All 4 candidates are now covered, the meringue included: the fruit crisp, 45 min in all [05:21–06:18]; the custard desserts, "bake during the break" [09:14–09:55]; the pumpkin pies and their meringue, no exact time [17:03–17:22] [20:54–22:36].
  - **A minor miss remains:** the meringue's "let that cook for few minutes" (22:46) sits in the next chapter, "Making Pulled-Sugar Corn and Leaves", which starts at 22:43. The meringue chapter ends at 22:36, so reading it can't reach that line. This is a chapter boundary in the data, not the rule.
  - The pies' oven setting is not counted: the question asks how long.
  - **Cost:** one more round than before, to read words with `get_memory_context` (12.5 → 16.0 s).
- **T17, whisking the eggs, and for how long (Partial, both runs).**
  - **Run A did not follow the new rule.**
    - After the contact sheet it spent all 3 remaining looks in one round, one of them on the 17:14 lead, which the transcript doesn't support. That left nothing to narrow.
    - Custard: "at least 7 seconds" (truth about 12 s), with no range.
    - It also reported "a brief hand-whisking moment around 17:13–17:16". Frames every 1 s show him talking with a whisk standing in a bowl, touching it at about 17:15, before turning to the stand mixer.
  - **Run B followed it, and the custard answer is now right.**
    - It skipped 17:14, ran coarse sequences on the two supported sessions, then bracketed the custard with 08:32–09:02.
    - Custard: "about 11–19 seconds, allowing for the gaps between checked frames". The truth, 08:37–08:49, about 12 s, is inside the range.
    - Pumpkin: "at least 19 seconds, still whisking at 15:06". The truth is about 45–55 s of active whisking up to about 16:00. Its coarse sequence was 14:36–15:06, the end of a camera shot, and no look was left to extend it. The answer is honest but well short.

### What is left

1. **The how-long rule does not reserve the narrowing look** (T17 A). "With a look left, narrow" lets the agent spend every look on coarse sequences, a sheet-only lead included. The rule should say to keep one look for narrowing, and that a sheet-only lead comes after it.
2. **"A sequence over its own shot" stops at a camera cut** (T17 B). The pumpkin whisking runs across several cuts, so a one-shot coarse window covers only its start. The coarse sequence should span where the transcript places the action (its moment, here 14:42–16:52), not one shot.
3. **The multi-candidate read step costs a round.** T2 needed one more round in both runs and T15 one more round for words. That is about 3–4 s, the price of the completeness.
4. **Still a single pair of runs.** T2, T15 and T17 varied between runs before; two passes each is a good sign, not a rate.

## 10. Not covered

- **`get_viewer_comments`:** `comment_embeddings` has 0 rows.
- **Untimed transcripts and non-English transcripts:** none exist in the DB.
- **Multi-turn follow-ups,** including reuse of an earlier turn's citations through `messages.retrieved_spans`.
- **Run-to-run variance,** beyond the two runs each of T17 and T18. T2, T15 and T18 changed between runs, so variance is clearly material.
- **The HTTP/SSE layer, the web client and the extension.**
- **Dropped-citation counts:** the harness saw the answer after the citation filter.
