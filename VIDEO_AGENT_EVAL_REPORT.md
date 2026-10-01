# Video Agent Evaluation Report

- **Date:** 2026-09-30.
- **Agent under test:** `backend/video_agent`, model `gpt-6.1-sol` on the OpenAI Responses API, image model `gpt-6-luna`.
- **Scope:** a one-off check of tool choice, tool order, how tool results are used, grounding, tool descriptions, and latency.
- **Method:** each test ran once. Every claim in every answer was checked against the database, and the visual answers against extracted frames.
- **Code changes:** none during the evaluation itself. The agent implementation was not modified. Follow-up fixes, including the model preload and the multi-part answer fix, are described in §10.

## 1. Summary

| | |
|---|---|
| Tests | 16, on 6 videos |
| Pass | 12 |
| Partial (grounded, but incomplete or weaker than expected) | 3: T2, T11, T15 |
| Tool-path deviation (answer correct, tools unexpected and costly) | 1: T14 |
| Hallucinated facts | 0 |
| Citations rejected by the citation check / output retries | 0 / 0 |
| Tool names or internals leaked in answers | 0 |
| Latency, all tests | median 7.5 s, mean 11.1 s, range 2.2–44.9 s |
| Latency, transcript-only tests | median 7.2 s, max 15.7 s |

What went well:

- **Grounding was sound throughout.** No answer stated anything the video doesn't support, including the strong-bait questions.
  - T12, ray tracing in a computer-graphics lecture: correctly declined.
  - T7, misleading title "Prismic Toolbar iFrame": correctly treated as a technical label.
  - T13, visual index unavailable: returned the exact prescribed message, without calling any tools.
- **The prompt's recipes were followed.** The run-by-run evidence:
  - T4 used the timestamp recipe, going from outline to chapter to memory.
  - T6 ran the on-screen-text round, calling screen text and transcript search in parallel.
  - T9 handled "paused, pointing at the screen" with a single close-up and no search.
  - T10 did "rephrase after an off-target search".
  - T10 and T8 followed the thread across the memory-context boundary.
- **Offered but irrelevant tools were left alone.** The comments tool was not called in T1 or T2. The visual tools were not called for speech questions in T5 or T7.

What to fix (details in §6–§7):

1. **Some multi-part answers are incomplete.**
   - T11 read 1 of the 3 seam-carving chapters and missed the NumPy/Numba part.
   - T15 asked which dessert was meant but offered only 2 of the 4.
   - T2 did not say that "tokenmaxxing" is credited to no one.
   - **Addressed after the evaluation:** a prompt change made T2, T11 and T15 pass on a re-run, at a latency cost (see §10).
2. **T14 took the visual path for a "where do they work on X" question.** It used picture search and a contact sheet, taking 28 s where about 6 s was expected. The transcript search's top 5 hits missed one of the two work sessions. The picture search recovered it by chance; the agent never checked the outline, which would have shown it in about 20 ms.
3. **Latency depends on the number of model round trips, not on the tools.**
   - Model time is 74% of the total, at about 2.7 s per round trip.
   - Transcript tools take 20–70 ms each.
   - Two cold starts (~12 s and ~10 s) fell on the first queries of an API process, because nothing preloaded the embedding models. **Addressed after the evaluation:** the API now preloads both models in the background at startup (see §8 item 5). Not yet re-measured.
   - The answer is sent only after it is fully generated, so the user sees no answer text until the very end.
4. **The tool descriptions have accuracy gaps.**
   - Result field descriptions are never sent to the model.
   - The prompt misdescribes `get_chapter_context`.
   - Search always returns 5 unscored hits.
   - The citation check accepts any time inside any retrieved chapter.

   None of these produced a wrong answer in this run. §7 shows where each one showed up.

## 2. Setup

- **Harness:** each test ran through the production `PydanticConversationAgentRunner.stream()` around `build_agent()`, with a proxy that timestamps every pydantic-ai event and keeps the raw tool results. This reproduces what production adds in the runner:
  - the conditional prompt sections (visual, comments, viewer position);
  - citation-span recording;
  - the citation fallback.

  The HTTP/SSE layer was not exercised.
- **Per-run setup:** dependencies were computed the same way as in `api/routes/conversations.py:238-240`, covering timing reliability, whether comments exist, and visual availability. The viewer position was set where a test needs it.
- **Conversation state:** every test started with empty history. Nothing was written to the database.
- **Order and warm-up:** the tests ran one after another in a single process. Before timing, the text-embedding model and the DB pool were warmed up, which took 12.4 s.
  - The SigLIP image-embedding encoder was not preloaded, so its roughly 10 s cold start is included in T14.
- **Environment:** a Windows dev machine, remote Azure Postgres and the OpenAI API. This DB is a dev database holding 8 videos.
- **Limits:**
  - Each test ran once, so a single failure is a lead, not a rate.
  - All videos are English.
  - `get_viewer_comments`, untimed transcripts and multi-turn follow-ups were not tested.

### Videos

| id | Content | Length | Visual index | Tests |
|---|---|---|---|---|
| `3b03286e` | Talk "Goodbye Tokenmaxxing" (has YouTube comments) | 8 min | none | T1, T2 |
| `0d4377ef` | Nand to Tetris Part II, course overview lecture | 21 min | none | T3, T4 |
| `bdeac510` | TED talk on climate innovation (Xu Hao), titled "Video" | 13 min | ready (OCR only partly done) | T5, T6 |
| `55705079` | TED interview, Chris Anderson and Sam Altman, titled "Prismic Toolbar iFrame" | 47 min | ready, with on-screen text | T7, T8, T9 |
| `75c17869` | Computer graphics TA recitation (noisy speech recognition) | 61 min | failed | T10–T13 |
| `6aa8f5ad` | 2004 Food Network broadcast with ads | 34 min | ready, with on-screen text | T14–T16 |

## 3. Results at a glance

Tools separated by `+` ran in the same round, in parallel. Tools separated by `→` ran in sequence.

| Test | Behavior | Tools called | Expected | Grade | Latency |
|---|---|---|---|---|---|
| T1 | Basic info | `get_video_info` | same | Pass | 4.7 s |
| T2 | Ambiguous ("the term") | `memories_semantic_search` | search ×1–2 | Partial | 4.6 s |
| T3 | Outline | `get_video_outline` | same | Pass | 8.7 s |
| T4 | Viewer position, speech | outline → chapter → memory (range 0) | same | Pass | 10.7 s |
| T5 | Specific fact | `memories_semantic_search` | same | Pass | 4.4 s |
| T6 | On-screen text | `search_screen_text` + `memories_semantic_search` | same | Pass | 5.5 s |
| T7 | Basic info, misleading title | info → search | info → search or outline | Pass | 7.1 s |
| T8 | Context within a chapter | search → memory context | same | Pass | 8.5 s |
| T9 | Viewer position, visual (paused) | `view_frames_closeup` | same | Pass | 7.7 s |
| T10 | Context across a chapter boundary | search → search → memory context → chapter | search → memory context (→ chapter) | Pass | 11.6 s |
| T11 | Larger section (3 chapters) | search → outline → chapter (ch4 only) | outline → 3 chapters | Partial | 15.7 s |
| T12 | Not in the video | search → search + outline | search ×1–3 | Pass | 7.3 s |
| T13 | Visual question, index unavailable | none | none | Pass | 2.2 s |
| T14 | Finding when | visual search + transcript search → contact sheet | transcript search + outline | Deviation | 28.1 s |
| T15 | Ambiguous (several candidates) | `memories_semantic_search` | search ×1–3 | Partial | 6.1 s |
| T16 | Action or sequence (visual) | visual search + transcript search → contact sheet → sequence → sequence | same, or skip the sheet | Pass | 44.9 s |

## 4. Per-test detail

Times are in seconds from the start of the run. The number after each tool is its duration.

### T1: Basic info (Pass)
- **Query:** "What's this video's title, and which site is it from?"
- **Calls:** `get_video_info` at 2.4 s (0.02 s).
- **Answer:** "titled 'Goodbye Tokenmaxxing: From AI Usage to Agentic AI Outcomes' and is from YouTube."
- **Check:** the title matches the tool's cleaned title; the stored title carries a "(67) … – YouTube" browser-tab wrapper. No channel or publisher was invented, and there was no extra retrieval.

### T2: Ambiguous term (Partial)
- **Query:** "Who coined the term?"
- **Calls:** `memories_semantic_search` with "Who coined the term, and what term was coined?"
- **Answer:** "If you mean 'valuemaxxing,' the video credits Mark Boroditsky, CRO of Nebus, with coining the term. [04:24–05:16]"
- **Check:** the fact and citation are correct; the caption spells Nebius as "Nebus". The answer hedges about the ambiguity, but it does not name the other candidate, "tokenmaxxing", or say that the video credits it to no one [01:19–01:33].
- **Comments tool:** it was offered on this video and correctly not called.

### T3: Outline (Pass)
- **Query:** "Outline this video's sections with timestamps."
- **Calls:** `get_video_outline` (0.02 s).
- **Answer:** all 5 chapters, with ranges identical to the tool's: [00:10–04:21], [04:23–12:03], [12:04–15:18], [15:19–17:59], [18:01–20:54]. The one-line descriptions match the chapter summaries.

### T4: Viewer position, spoken content (Pass)
- **Query:** "What's being talked about right now?" The player was playing at 660 s (11:00).
- **Calls:**
  1. `get_video_outline` at 2.4 s.
  2. `get_chapter_context` on ch1 at 4.2 s.
  3. `get_memory_context` on the memory covering 11:00, with `context_range=0`, at 6.8 s.
- **Answer:** "the VM translator project … build this translator during the first two weeks, comparing it to Java's JVM and Microsoft's CLR. [09:27–11:14]"
- **Check:**
  - The answer is correct and avoids the trap of the operating-system section, which starts at 11:15.
  - The prompt's recipe stops at `get_chapter_context`, which returns summaries only. The model added the memory-context step by itself to get the words.
  - The three calls were sequential, needing four model requests, which explains the 10.7 s.

### T5: Specific fact (Pass)
- **Query:** "How much solar radiation does Moguang's cooling material reflect?"
- **Calls:** `memories_semantic_search` (0.07 s).
- **Answer:** "reflects 93% of solar radiation back. [09:07–10:28]"
- **Check:**
  - The answer is correct and did not fall for the "80%" distractor in the same memory.
  - The citation is the whole 81-second memory, though the sentence is at 09:16–09:31. Memories are the finest unit the tools return, so this is expected.
  - Visual tools were offered and correctly not used.

### T6: On-screen text (Pass)
- **Query:** "The timeline slide about ethanol shows two years. Which years?"
- **Calls:** `search_screen_text` and `memories_semantic_search` in the same round.
- **Answer:** "1784 and 1875. [01:10–01:22]"
- **Check:** correct. The years are only on screen, and the speech says "the 1700s". The citation is the screen-text moment.
- **OCR coverage:** the tool reported that OCR had not yet read 70 of this video's 78 keyframes, although its `visual_status` is `ready`.

### T7: Basic info with a misleading title (Pass)
- **Query:** "What is this video, and who is talking?"
- **Calls:** `get_video_info`, then `memories_semantic_search`.
- **Answer:** "a TED interview with Sam Altman, conducted by Chris Anderson … [00:00–00:52]". It adds that "Prismic Toolbar iFrame" "appears to be a technical label rather than the actual talk title."
- **Check:** correct. The names come from the transcript's opening speaker labels. No visual tools were used.

### T8: Context within a chapter (Pass)
- **Query:** "Right before Anderson asks about ChatGPT's growth, what was Altman describing, and why?"
- **Calls:** `memories_semantic_search`, then `get_memory_context` on the growth memory with `context_range=1`. That returned the previous memory, and a boundary on the following side.
- **Answer:** Altman described OpenAI's compute shortage: "all day long" calling people and begging for GPUs. This was a response to Anderson's question about DeepSeek and massive investment. Then came "incredibly constrained" while growth surged, which prompted the growth question. [07:39–08:58] [09:05–10:26]
- **Check:** correct, and it read the "why" properly. The transcript shows Anderson asking whether DeepSeek's cheaper model is "life-threatening" to "massive scale, tens of billions of dollars of investment" (08:41–08:58). That is followed by the GPU line, then "We are so incredibly constrained" (09:05) and "Tell us about the growth" (09:13).
- **Data issue:** the GPU line is spoken at about 09:00–09:04, but its text sits in the memory stored as 07:39–08:58. So the only citation available to the agent lands about 80 s early; see §6. **Fixed since:** the line is now timed 09:00.4 and sits in a memory spanning 08:26.8–09:13.5; see §10, "Caption cue repair". T8 was not re-run.

### T9: Viewer position, visual, paused (Pass)
- **Query:** "What is this?" The player was paused at 37:12.
- **Calls:** `view_frames_closeup` at 2232 s (1.8 s, one look), with no search.
- **Answer:** "a post by Sam Altman announcing the birth of his son, with a close-up photo of a newborn holding an adult's finger … baby arrived early … NICU … 'I have never felt such love.' Two speakers are seated beneath the projection. [37:12]"
- **Check:** matches the extracted frame and its OCR text.

### T10: Context across a chapter boundary (Pass)
- **Query:** "Right after the note about padding the image with zeros, what does the recitation move on to, and how important does the TA say the padding note is?"
- **Calls:**
  1. `memories_semantic_search` with an overloaded query: "padding … next topic recitation TA". The hits were off-target.
  2. A rephrased search, which found the padding memory [34:21–35:00].
  3. `get_memory_context`. The following side was empty, with a boundary naming "Seam-carving basics".
  4. `get_chapter_context` on that chapter, to cite its start.
- **Answer:** seam carving [35:02–37:25]. The TA calls the padding "just a side note" and "an edge case", and says "I don't think it should concern you too much" [34:21–35:00].
- **Check:** the quotes are verbatim. The prompt's "rephrase after a weak search" rule and the boundary object both worked as designed.
- **Cost:** the first query packed several concepts into one embedding, which cost a round. That is 5 model requests, 11.6 s.

### T11: Larger section (Partial)
- **Query:** "Summarize the seam carving part of the lecture."
- **Calls:**
  1. `memories_semantic_search`. It hit both memories of ch3 and 2 of the 4 memories of ch5.
  2. `get_video_outline`.
  3. `get_chapter_context` on ch4 only.
- **Answer:** six accurate bullets, each with correct citations:
  - content-aware resizing;
  - the definition of a seam;
  - the dynamic-programming cost matrix and pixel energy;
  - forward-looking costs;
  - backtracking, versus the greedy mistake;
  - reference-matrix bookkeeping.
- **Check:**
  - Every claim matches the memory summaries.
  - The answer misses ch5's last two memories [56:03–59:30]: the NumPy/Jupyter tools and the optional Numba speed-up.
  - It never read ch5 as a whole. It reused search hits instead, which was efficient but incomplete.
- **Latency:** the slowest transcript-only test at 15.7 s. That includes about 8 s of writing 477 output tokens.

### T12: Answer not in the video (Pass)
- **Query:** "How does the lecture explain ray tracing?"
- **Calls:** `memories_semantic_search`, then a rephrased search ("tracing rays of light … rendering") and `get_video_outline` in parallel.
- **Answer:** "I couldn't find an explanation of ray tracing in this video. The instructor introduces the session as covering image processing and seam carving. [00:42–02:43]"
- **Check:**
  - Correct: there are zero mentions in the transcript. The framing claim is in that memory ("intro for image processing … the seam carving algorithm").
  - It correctly judged 10 irrelevant hits as irrelevant and stopped after 2 searches.
  - It did not mention the nearest content, a brief rendering intro at 11:15. That was optional.

### T13: Visual question, index unavailable (Pass)
- **Query:** "What's written on the slide when he explains convolution?"
- **Calls:** none, in a single model request.
- **Answer:** "Visual analysis isn't available for this video, so I can't read what's written on the slide. I can help you find or summarize his spoken explanation of convolution."
- **Check:** the exact prescribed message, with no guessing from the transcript.

### T14: Finding when a topic is discussed (Deviation: answer correct, tool path costly)
- **Query:** "Where in the video do they work on the pumpkin pies?"
- **Calls:**
  1. `search_visual_moments` (12.7 s, which includes about 10 s of SigLIP cold load) and `memories_semantic_search` in parallel.
  2. `view_candidates` on 4 frames (5.0 s, one look).
- **Answer:** squash shells [13:31–14:41], filling [14:42–16:52], meringue at [21:30], and piping it onto the pies at [22:16]. Start at [13:31].
- **Check:**
  - The locations are right, and the frames at 21:30 and 22:16 confirm the meringue work.
  - The transcript search's top 5 did not include the meringue memory [20:54–22:36]. Seven memories are relevant, but search returns only 5.
  - The second work session was found only because the agent chose picture search.
  - `get_video_outline`, which lists "Meringue for the Squash Pumpkin Pies" and takes 0.02 s, was never called.
- **Why the prompt allows this:** its visual section routes "where, when, or what happens (… an action)" to the visual tools. "Where do they work on X" fits that pattern, although the question is fully answerable from speech.
- **Cost:** 28.1 s, or roughly 16 s with a warm encoder, against about 6 s for search plus outline.

### T15: Ambiguous question with several candidates (Partial)
- **Query:** "How long does it bake?"
- **Calls:** `memories_semantic_search` (0.05 s).
- **Answer:** "Which dish do you mean—the fruit crisp or the pumpkin pie in squash shells?"
- **Check:**
  - Asking a clarifying question is acceptable, and no bake time was invented.
  - It offered only 2 of the 4 candidates, leaving out the crème caramel/bread pudding and the meringue.
  - It also did not say that only the fruit crisp has a stated time: 30 min, then coals on top for 15 more [05:32], [05:48].
  - One search, so the other desserts were never retrieved.

### T16: An action or sequence (Pass)
- **Query:** "Show me how the acorn squash gets hollowed out: what happens on screen, step by step?"
- **Calls:**
  1. `search_visual_moments` (0.2 s, warm) and `memories_semantic_search` in parallel.
  2. `view_candidates` on 4 times, mixing picture hits and the transcript start (3.7 s).
  3. `view_sequence` over 818–864 s with 9 frames (12.3 s).
  4. A narrower second `view_sequence` over 836–851 s (9.7 s).

  That is 4 visual calls and 3 looks, within the budget of 6 calls and 4 looks.
- **Answer:** five steps between 13:38 and 14:18:
  1. Knife around the top.
  2. Top removed, spoon inserted.
  3. Scraping the stringy inside.
  4. The cut top lying in front.
  5. The hollow yellow shell in the tray.
- **Check:** the frames at 13:38, 14:02, 14:08 and 14:18 match each step. Every citation came from a look, and none was a raw picture-search time.
- **Latency:** the slowest test at 44.9 s, of which 22 s was the two sequences.

## 5. Latency

### Per test

| Test | Total s | 1st tool s | 1st answer text s | Tool time s | Model time s | Model requests | Tool calls | Input tok | Cached tok | Output tok |
|---|---|---|---|---|---|---|---|---|---|---|
| T1 | 4.7 | 2.4 | 4.1 | 0.0 | 4.7 | 2 | 1 | 5046 | 5040 | 49 |
| T2 | 4.6 | 2.0 | 3.6 | 0.1 | 4.5 | 2 | 1 | 6185 | 4937 | 76 |
| T3 | 8.7 | 2.4 | 5.1 | 0.0 | 8.7 | 2 | 1 | 4388 | 1956 | 291 |
| T4 | 10.7 | 2.4 | 9.5 | 0.1 | 10.7 | 4 | 3 | 11010 | 7457 | 211 |
| T5 | 4.4 | 2.1 | 3.8 | 0.1 | 4.3 | 2 | 1 | 9884 | 3970 | 62 |
| T6 | 5.5 | 2.8 | 4.9 | 0.2 | 5.3 | 2 | 2 | 10133 | 7922 | 97 |
| T7 | 7.1 | 1.7 | 4.9 | 0.1 | 7.0 | 3 | 2 | 15154 | 11959 | 177 |
| T8 | 8.5 | 1.8 | 6.4 | 0.1 | 8.4 | 3 | 2 | 18503 | 14607 | 198 |
| T9 | 7.7 | 2.2 | 5.9 | 1.8 | 5.8 | 2 | 1 | 8820 | 4005 | 97 |
| T10 | 11.6 | 2.2 | 10.3 | 0.2 | 11.4 | 5 | 4 | 30827 | 23842 | 240 |
| T11 | 15.7 | 2.1 | 7.6 | 0.1 | 15.6 | 4 | 3 | 16748 | 13209 | 477 |
| T12 | 7.3 | 1.9 | 6.5 | 0.1 | 7.2 | 3 | 3 | 15035 | 8564 | 139 |
| T13 | 2.2 | – | 1.3 | 0.0 | 2.2 | 1 | 0 | 1962 | 1945 | 37 |
| T14 | 28.1 | 3.6 | 25.6 | 17.6 | 10.5 | 3 | 3 | 15870 | 13661 | 248 |
| T15 | 6.1 | 2.5 | 5.6 | 0.1 | 6.0 | 2 | 1 | 9792 | 7916 | 124 |
| T16 | 44.9 | 3.1 | 40.7 | 25.9 | 19.0 | 5 | 5 | 32070 | 27710 | 582 |

- **Model time** is the total minus the time any tool was running.
- **"1st answer text"** is when the model started writing the final answer. The runner buffers the answer until the citation check passes (`runner.py:191-194`), so the user sees no answer text before **Total**. Only the tool-activity lines stream before that.

### Per tool

| Tool | Calls | Median | Max |
|---|---|---|---|
| `get_video_info` | 2 | 0.02 s | 0.02 s |
| `get_video_outline` | 4 | 0.02 s | 0.02 s |
| `get_chapter_context` | 3 | 0.02 s | 0.02 s |
| `get_memory_context` | 3 | 0.05 s | 0.07 s |
| `memories_semantic_search` | 13 | 0.06 s | 0.07 s |
| `search_screen_text` | 1 | 0.17 s | 0.17 s |
| `search_visual_moments` | 2 | 0.2 s warm | 12.7 s cold |
| `view_frames_closeup` | 1 | 1.8 s | 1.8 s |
| `view_candidates` | 2 | 4.3 s | 5.0 s |
| `view_sequence` | 2 | 11.0 s | 12.3 s |

### Observations

1. **Model round trips dominate.**
   - Across the suite, 74% of wall time is model time.
   - The median is about 2.7 s per model request, ranging from 2.2 to 4.4 s.
   - The first tool call arrives after a median of 2.2 s, which is one model round.
   - Latency is therefore roughly 2.5 s times the number of sequential rounds, plus the answer-writing time. Transcript tools contribute almost nothing.
   - The multi-round tests show this: T4, with 3 sequential calls, took 10.7 s; T10, with 4 calls, took 11.6 s.
2. **Answer writing is hidden time.** From first answer text to done took about 8 s in T11 (477 tokens) and 3.6 s in T3. Because the answer is buffered for the citation check, the user waits through all of it with no text.
3. **Cold starts were not preloaded.** *(Fixed after this evaluation: the `lifespan` now starts `api/model_preload.py`, which loads both models on a background thread. The description below is of the code as tested.)*
   - The `lifespan` in `api/app.py:79-81` loaded nothing.
   - The first chat question on a fresh API process pays about 12 s to load the text-embedding model and open the DB pool. That was measured in this harness's warm-up and excluded from the table.
   - The first visual search pays about 10 s to load the SigLIP encoder (`image_embedding.shared_encoder()`, measured at 10.1 s). That is included in T14.
4. **Visual looks are the expensive tools.** A sequence takes about 10–12 s and a contact sheet about 4–5 s; both are image-model calls. A visual question that uses the full recipe (search, sheet, sequence) costs 25–45 s.
5. **Token use is modest.** Input ranges from 2k to 32k tokens per question, with high cache reuse, and output from 37 to 582 tokens. Reasoning tokens were near zero.

## 6. Tool-call behavior

| Check | Result |
|---|---|
| Correct tools chosen | 14 of 16 as expected. T14 took the visual path; T11 under-fetched, reading 1 of 3 chapters. |
| Correct order | Yes in all 16. Dependent calls were sequential, and independent calls were batched in parallel in T6, T12, T14 and T16. |
| Unnecessary calls | None were clearly wasteful. T10's first search was a wasted round, caused by an overloaded query and followed by a correct rephrase. T14's visual calls were costly, not useless, since they found the second session. |
| Correct use of tool results | Yes. T8 and T10 read the neighbouring memory and the chapter boundary correctly. T12 judged 10 irrelevant hits as irrelevant. T6 took the answer from the screen text, not the speech. T16 cited only times returned by a look. |
| Grounded final answers | All 16. No outside facts, and no invented timestamps. |
| Citation check | 0 rejections and 0 retries. All citations were within retrieved spans. I also checked each one for correctness by hand, because the automatic check is loose (§7). |
| Offered-tool restraint | The comments tool was not used in T1 or T2, and the visual tools were not used for speech questions in T5 or T7. |
| Internal leakage | None. No tool names or raw errors appeared in any answer. |

Problems found in the data (not the agent):

- **Captioned videos contain cue artifacts and gap text.** Memory text includes caption cue lines such as `00:09:00.403 --> 00:09:04.774`, plus speech that is timed in the gap between two memories. The result is a citation that points to the wrong window: in T8 the GPU line is spoken at about 09:00, but it is citable only as [07:39–08:58]. This affects `bdeac510` and `55705079`. **Fixed since**, and the "gap text" turned out to have the same cause as the cue lines; see §10, "Caption cue repair".
- **OCR is incomplete on `bdeac510`.** 70 of its 78 keyframes are unread, yet `visual_status` is `ready`. The screen-text tool reports this correctly in its note.

## 7. Tool descriptions: accuracy against actual behavior

| # | Issue (from reading the code) | Where | Seen in the runs |
|---|---|---|---|
| 1 | **Result field descriptions never reach the model.** pydantic-ai 2.45 leaves `include_return_schema` off, and `build_agent` doesn't enable it. Guidance written only in `result.py` field descriptions is invisible, for example `view_candidates`' "a signal, not the decision". | `runner.py:138-145`, `tools/*/result.py` | No failure could be attributed to it. The model interpreted `present` verdicts sensibly in T14 and T16. |
| 2 | **The prompt says `get_chapter_context` returns "all segments within one chapter".** It actually returns one-line summaries only, with no text. The timestamp recipe (outline, then chapter context) never gives the words said, and the tool's docstring points to search rather than `get_memory_context` for the words. | `prompt.py:41,45-49`, `get_chapter_context/tool.py:22-24` | T4: the model added `get_memory_context(range=0)` on its own. That worked, but the documented recipe is incomplete and costs a third sequential round. |
| 3 | **`memories_semantic_search` always returns 5 hits,** with no score and no threshold. The prompt's "when the first search returns nothing" and "if the tools indicate that additional matches exist" can never happen. | `memory_embeddings.py:148-159`, `prompt.py:53,88` | T10 and T12: the model judged off-target hits correctly. T14: 7 relevant memories but only 5 hits, and the model didn't notice the missing second session. |
| 4 | **The citation check accepts any second inside any retrieved span, whole chapters included.** One outline call makes almost any timestamp pass. Picture-search times become citable through overlapping spans, although the prompt says they are not. | `citations.py:59-61,98-101` | Not triggered: every citation was also correct by hand. The check could not have caught a wrong in-range citation. |
| 5 | **The visual prompt's routing is broader than intended.** "Where, when, or what happens (… an action)" sends speech-answerable "where do they do X" questions to the visual tools. | `prompt.py:153,160` | T14: 28 s, where about 6 s was expected. |
| 6 | **Minor issues.** The prompt says "segments" while the tools say "memories" or "moments"; there is a typo, "semanitc"; retrieved spans reset every turn, so a follow-up that reuses an earlier timestamp is rejected, and the prompt doesn't say so. | `prompt.py:40,79`, `conversations.py:292` | No observed effect. The span reset was not tested, since this run had no multi-turn tests. |

## 8. Recommendations

Ordered by expected impact. Which of these have been implemented since is listed in §10.

1. **Make the multi-part cases complete.**
   - For section questions, add prompt guidance to read every chapter a topic spans (T11).
   - When asking a clarifying question, list every candidate the video contains, and answer the ones the video does answer (T2, T15).
   - **Done:** see §10, "Multi-part answers".
2. **Fix the chapter-context description and the timestamp recipe (issue 2).**
   - The prompt should say it returns summaries.
   - The recipe should end with `get_memory_context(memory_id, context_range=0)`.
   - Alternatively, have `get_video_outline` return each chapter's memory ids and spans. That would cut T4-style questions from 3 sequential rounds to 2.
   - **Done:** the first two bullets, see §10 (§7 issue 2). The outline alternative was deliberately not taken: it helps only time-based questions, since ids and spans say nothing about what a moment contains, and it would grow every outline call for about 2.5 s saved.
3. **Pair "where is X" transcript searches with the outline.** The outline is a 20 ms call, and together they cover more than the top 5 hits (issue 3). Also consider returning a similarity score, so "off-target" can be judged from data.
4. **Narrow the visual routing (issue 5).** Visual tools should handle "what does it look like / what is on screen". Locating an activity that is also narrated should go to transcript tools first, with visual tools only if speech fails. This saves 20–40 s on such questions.
5. **Cut perceived latency.**
   - **Done (not yet re-measured):** preload the text-embedding model and the SigLIP encoder at API startup, saving about 12 s and 10 s on the first queries of each process.
     - The `lifespan` starts `start_model_preload()` (`api/model_preload.py`), which loads the text model first, then SigLIP only when `VIDSEEK_VISUAL_INDEXING` is on, on a daemon thread.
     - A model that fails to load is logged and falls back to loading on first use.
     - `VIDSEEK_PRELOAD_MODELS=false` turns it off; the test suite does so.
     - Cost: every API process holds both models in memory from startup, so each extra worker holds its own copy.
   - Consider streaming the answer and fixing citations afterwards, instead of buffering the whole answer. Today about 3–8 s of answer writing is invisible to the user.
   - Fewer sequential rounds (item 2) is the other lever, at about 2.5 s per round.
6. **Tighten the citation check (issue 4).** Accept a citation only inside memory-level or look-level spans, not chapter ranges. Stop treating picture-search times as citable.
7. **Send result field descriptions (issue 1).** Either enable the return schema, or move the rules the model must follow into the docstrings.
8. **Data hygiene.** Strip caption cue lines from memory text, and assign gap speech to the memory it is spoken in (T8). Don't report the visual index as ready while OCR is still incomplete, or make that state explicit.
   - **Done for the captions:** see §10, "Caption cue repair". The OCR half is still open.

## 9. Not covered

- **`get_viewer_comments`:** left out by decision. `comment_embeddings` has 0 rows, so a topic search over comments probably can't work.
- **Untimed transcripts:** no chattable untimed video exists in the DB.
- **Non-English transcripts:** none exist in the DB.
- **Multi-turn follow-ups:** not tested, including reuse of earlier timestamps (issue 6).
- **Run-to-run variance:** each test ran once.
- **The HTTP/SSE layer.**

## 10. Follow-up: fixes made after this report

Branches `fix/video-agent-tool-descriptions` and `perf/preload-embedding-models`, merged into `main` on 2026-10-01, and `feat/stream-answer-persist-citation-spans` (the last two rows below). The test results above describe the agent as it was on 2026-09-30 and were not re-run. The unit tests pass (964 passed, 1 skipped); nothing has been re-checked against the live model.

Done:

| Item | Change |
|---|---|
| §7 issue 1, §8.7 (field descriptions never sent) | Not fixed by enabling the return schema. The field meanings the model needs were moved into the tool docstrings (`get_memory_context`, `search_screen_text`, `view_sequence`). The other tools were already covered by the prompt or self-explanatory. |
| §7 issue 2, §8.2 (`get_chapter_context`) | The prompt's tool list was removed in favor of two routing lines. The docstrings of `get_chapter_context` and `get_video_outline` no longer imply full text, and `get_chapter_context` points to `get_memory_context` for the words. The timestamp recipe now ends with `get_memory_context(memory_id, context_range=0)`. |
| §7 issue 3, §8.3 (search always returns 5 hits) | `memories_semantic_search` scores every memory of the video and returns those with z >= 1.5 against the video's own scores, at most 8, closest first. When none stands out, it returns the 3 closest marked `weak`, with a note. The z-score is not sent to the model. The logic is in `backend/services/memory_search.py`. |
| §8.3 (pair "where is X" with the outline) | The prompt now has the model call search and `get_video_outline` in the same round for "where / when" questions. |
| §7 issue 6 (wording) | "segments" is now "moments" throughout, and the "semanitc" typo is gone. |
| Not in the report | `search_visual_moments` no longer sends its `score` field. |
| §8.5 (cold starts) | Branch `perf/preload-embedding-models`, merged into `main` on 2026-10-01. The API `lifespan` starts `start_model_preload()` (`backend/api/model_preload.py`), which loads the text-embedding model and then, when `VIDSEEK_VISUAL_INDEXING` is on, SigLIP, on a daemon thread. A model that fails to load is logged and loads on first use instead. `VIDSEEK_PRELOAD_MODELS=false` turns it off, and the test suite does so. Not re-measured: the 12 s and 10 s figures are the pre-fix ones. Cost: each API process holds both models in memory from startup. |
| §8.5 (streaming the answer) | The runner forwards the answer as it is written instead of buffering it for a whole-answer check. `CitationFilter` (`video_agent/citations.py`) holds back only an open `[`, and checks the citation when its `]` arrives: its shape and whether a tool returned the moment. A citation that fails is dropped with the space before it. The retry on a bad citation is gone (`_verify_citations`, `AnswerDraft.text`, `strip_unverified`); it fired 0 times in the 16 tests. Text a model writes before a tool call is separated from the answer by a paragraph break; none was seen in the production runs, and the stream's `FinalResultEvent` fires on that text too, so it cannot tell the two apart. Live check, one T8-style question: the first answer text appeared 1.5 s before the answer finished, where it used to appear only at the end. |
| §7 issue 6 (spans reset every turn) | Each assistant message now stores the spans its tools returned (`messages.retrieved_spans`, migration `0028_message_retrieved_spans.sql`). The next turn starts with them restored, so a moment cited earlier stays citable. Only tool-returned spans are stored, never times found in chat text. The prompt says so. |

### Multi-part answers (§8.1)

Branch `fix/video-agent-multi-part-answers`, merged into `main` on 2026-10-01. Prompt-only change in `backend/video_agent/prompt.py`:

- A new section, "Questions About a Part of the Video". In one round, it calls the outline and search. Then, in one round, it calls `get_chapter_context` on every chapter the topic spans: chapters whose title or summary covers it, plus chapters a relevant hit falls in. The answer covers each of them. It summarizes from the moment summaries and reads a moment's words only for a missing detail.
- A new section, "Questions With More Than One Possible Meaning". It finds every candidate with the outline and search in one round. When each answer is short, it answers for every candidate instead of asking, and says which candidates the video leaves unanswered. It asks a question back only when answering everything would be long, and then lists every candidate.
- Tone: "Answer only what was asked" became "…but all of it", so brevity no longer drops parts of an answer.
- The examples in the prompt are deliberately not from the test videos.

Re-run on 2026-10-01 through the production runner, once per test, with the same queries and empty history:

| Test | Before | After | Tools called (after) | Latency |
|---|---|---|---|---|
| T2 | Partial | Pass. Names both terms: "valuemaxxing" is credited to Mark Boroditsky [04:24–05:16]; "tokenmaxxing" is explained, but the video names no one who coined it [00:42–01:48]. | outline + search → search | 4.6 → 21.5 s |
| T11 | Partial | Pass. Covers all 3 chapters, including the NumPy/Jupyter tools and the optional Numba speed-up [56:03–59:30]. | outline + search → 3 × chapter | 15.7 → 31.0 s |
| T15 | Partial | Pass. Answers without asking, for all 4 desserts. Only the fruit crisp has a stated time, 30 + 15 min [05:21–06:18]. No time is given for the crème caramel/bread pudding or the squash pies, and the meringue takes "a few minutes". | outline + search → search + 2 × chapter | 6.1 → 12.8 s |
| T3 | Pass | Pass, unchanged. | outline | 8.7 → 12.3 s |
| T5 | Pass | Pass, unchanged. | search | 4.4 → 5.1 s |

All citations passed the check, with 0 rejections. On a first run, without the "summaries are usually enough" line, T11 added a fourth round of `get_memory_context` calls (28.6 s), and T15 took 4 rounds (16.6 s). The cost is latency: the extra rounds, plus long model think time between them (T2 spent about 14 s before its second search, and T11 about 13 s before its chapter reads). Each test ran once, so the latency figures are leads, not rates.

### Caption cue repair (§8.8, captions)

Branch `fix/caption-cues-without-blank-lines`, merged into `main` on 2026-10-01.

The cue lines and the "gap speech" in §6 had one cause. These two videos' WebVTT tracks sometimes leave out the blank line between two cues. The shared caption parser (`backend/core/captions.py`) ended a cue's text only at a blank line, so it swallowed the next cue whole: that cue's timing line was stored as speech, and its words were timed as the cue before it. The GPU line in T8 was stored inside a segment timed 08:55.9–08:58.9. It was never speech between two memories.

- **Parser:** a cue's text now also ends at the next timing line, dropping an SRT cue number just above it. The YouTube caption reader had the same weakness and was fixed the same way.
- **Stored data:** a one-off repair, `python -m backend.download_pipeline.repair_glued_caption_cues`, which reports only unless given `--apply`. It split each stored segment back into cues at the timing lines left in its text, normalized the result, and re-ran memories, chapters, embeddings and insights. It was applied on 2026-10-01 to the only 2 of the 8 videos affected:

| Video | Segments with a cue line | Segments | Memories | Chapters |
|---|---|---|---|---|
| `55705079` | 95 → 0 | 263 → 268 | 31 → 33 | 13 → 12 |
| `bdeac510` | 26 → 0 | 64 → 65 | 11 → 10 | 5 → 5 |

Before the repair, every memory on both videos held a cue line. The T8 GPU line is now timed 09:00.4 and sits in memory 9 (08:26.8–09:13.5), so [09:00] is citable. The unit tests pass (974 passed, 1 skipped).

The memories and chapters of these two videos were rebuilt by the LLM, so their boundaries and summaries differ from the ones T5 to T9 ran against. Those tests' results describe the old data and were not re-run.

Still open:

- §8.8, OCR: `visual_status` still says `ready` while OCR is incomplete, and an interrupted OCR pass never resumes, because the local video file is deleted once indexing ends (`bdeac510`: 8 of 78 keyframes read). Left for a separate run. A resume would read frames back from Blob Storage, which `ARCHITECTURE.md` currently rules out for visual indexing.
- §7 issue 5 and §8.4: the visual routing is still too broad (T14).
- §8.1 follow-up: the fixed questions are now about 2 to 5 times slower (T2, T11, T15). This could be cut by not repeating a search once the outline already names the candidates.
- §7 issue 4 and §8.6: the citation check is still loose.
- §8.5: cutting sequential rounds. The model preload and answer streaming are done; streaming is checked against the live model for two questions, not re-measured across the suite, and the web client and extension were not run against it.

Migration `0028_message_retrieved_spans.sql` is applied to the dev database. Any other database needs `python -m backend.storage.postgres.migrate` before the streaming code is deployed, because finalizing an answer writes the new column.

To re-check: T4, T10, T12 and T14 through the production runner, and the 8-hit search cap against T14. Also T5 to T9, whose two videos were re-segmented by the caption repair; T8 should now cite the GPU line at [09:00]. T11 and T15 were re-checked with the multi-part fix above; both passed. All of them now run through the streaming runner too.
