# Video Agent Evaluation Report

- **Date:** 2026-10-03.
- **Agent under test:** `backend/video_agent` at `main` 00c1dc9, model `gpt-6.1-sol` on the OpenAI Responses API, image model `gpt-6-luna`.
- **Scope:** a re-run of all 18 tests from the 2026-10-02 report. It checks tool choice, tool order, how tool results are used, grounding, and latency, and compares latency with 2026-10-02.
- **What changed since 2026-10-02:**
  - The prompt fixes from `fix/video-agent-prompt-eval-issues` (ccdc9de) were merged.
  - The system prompt was rewritten in 00c1dc9 ("Update system prompt"). It adds a "Video navigation" section, merges the "where" and "part of the video" recipes into one workflow, and restyles the citation rules.
  - **`75c17869`'s visual index is now `ready`.** It was `failed` (`visual_indexing_interrupted`) on 10-02. T13 and T18 now get the visual tools, so their expected paths changed.

  The 2026-10-02 report and its follow-up re-run are in git history.
- **Method:** the full suite ran twice, as run A and run B, each in its own process. Every claim in every answer was checked against the database. The visual answers were checked against frames extracted every 1–3 s.
- **Code changes:** none. The agent implementation was not modified.

## 1. Summary

| | Run A | Run B |
|---|---|---|
| Tests | 18, on 6 videos | 18 |
| Pass | 16 | 16 |
| Partial (grounded, but incomplete or imprecise) | 1: T17 | 1: T17 |
| Fail | 1: T18 | 1: T18 |
| Hallucinated facts (from the agent) | 0 | 0 |
| False visual claims (from an image-model misread) | 0 | 1: T17 |
| Tool names or internals leaked in answers | 0 | 0 |
| Latency, all tests | median 9.3 s, mean 15.1 s, range 4.4–50.7 s | median 10.4 s, mean 14.0 s, range 4.7–47.5 s |
| Latency, tests with no visual tool (12 per run) | median 9.1 s, max 15.5 s | median 9.6 s, max 15.5 s |

Compared with 2026-10-02 (the suite run, and the after-fix re-run of T2, T3, T14, T15 and T17):

| | Better | Same or worse |
|---|---|---|
| Grades | T2, T3, T14 and T15 pass in all 4 runs since the fixes: all candidates answered, outline-only for T3, and no visual tools for T14. T13 now reads the slide. | T17 is still Partial: the pumpkin whisking is still understated. T18 still fails, now with the visual tools. |
| Latency, 16 unchanged tests | Sum 210–220 s, against 226 s at the 10-02 after-fix baseline. T2 is 9.8–13.3 s, where the after-fix runs took 11.8–22.5 s. T12 and T14 are each 2 s faster. | T17 is 2.7 s slower on average. T3 is 1 s slower. |
| Latency, changed tests | – | T13: 2.9 s → 16–42 s, and T18: 6.6 s → 16–19 s. Both now use visual tools instead of refusing. |

What went well:

- **Grounding stayed sound.**
  - T12, ray tracing: declined, and pointed to the nearest related section.
  - T6: the years came from the slide, not from the speech.
  - Every citation in all 36 answers falls inside a span a tool returned.
- **The 10-02 prompt fixes held under the rewritten prompt.**
  - T2 named both terms in both runs.
  - T15 covered all 4 desserts in both runs.
  - T3 called `get_video_outline` alone.
  - T14 used no visual tools.
- **The custard duration is now right in both runs:** "about 10–19 seconds" against a true 12 s.
- **T13 works with a ready index.** Both runs read the 3×3-filter slide with a close-up and quoted it exactly.

What to fix (details in §6–§8):

1. **T18 still misses the "details" example** at 17:08–19:27.
   - Run A: the picture search ranked that slide first (17:56), and the contact sheet said `present: yes`. The agent picked the next slide (19:50) anyway, because the sheet couldn't read the small "details" label.
   - Run B: the picture search missed the slide. The agent answered with the "Images" bullet slide (13:10) and the derivative slide (19:32).
   - OCR never read the label, so `search_screen_text` can't find "details" (§6).
2. **T17 run B reported whisking that didn't happen.** It reported "another brief whisking moment around 17:13–17:19, about 6–12 seconds". The sequence's observation was hedged ("appearing to whisk or stir"). Frames every 1 s show him gesturing and touching the whisk once, then turning to the stand mixer.
3. **The pumpkin-filling whisking is still understated** in both runs: about 21–29 s and about 30 s, against about 45–55 s of active whisking from 14:48 to about 16:00. Neither run looked past 15:24.
4. **The rewritten prompt has rendering defects** (§7). Backslash line endings join sentences. Two steps point to a section, "Finding Where Something Is", that no longer exists. The citation format reads `[MM–MM]`. No answer failed because of them yet.
5. **T12 no longer says what was searched.** The rewrite dropped "saying what you searched" from the not-found rule. Both runs answered "I couldn't find an explanation of ray tracing" without naming the searches.

## 2. Setup

- **Harness:** the same as 10-02. Each test ran through the production `PydanticConversationAgentRunner.stream()` around `build_agent()`.
  - A proxy wrapped the agent to timestamp every pydantic-ai event and keep the raw tool results.
  - Citations went through the production streaming `CitationFilter`.
  - The HTTP/SSE layer was not exercised.
- **Per-run setup:** `has_comments` and `visual_availability` were computed the same way as in `api/routes/conversations.py`. The viewer position was set where a test needs it:
  - T4: playing at 11:00.
  - T9: paused at 37:12.
- **Conversation state:** every test started with empty history. Nothing was written to the database.
- **Order and warm-up:** in each run, the tests ran one after another in a single process. Before timing, both embedding models were loaded the way the API's startup preload does, and the DB pool was opened.
- **Environment:** the same macOS (Apple Silicon) dev machine as on 10-02, the remote Azure Postgres and the OpenAI API.
- **Limits:**
  - Two runs per test is enough to see variance, not to measure a rate.
  - All videos are English.
  - `get_viewer_comments`, untimed transcripts and multi-turn follow-ups were not tested.
  - Citations the filter dropped were not counted.

### Videos

| id | Content | Length | Visual index | Tests |
|---|---|---|---|---|
| `3b03286e` | Talk "Goodbye Tokenmaxxing" (has YouTube comments) | 8 min | skipped | T1, T2 |
| `0d4377ef` | Nand to Tetris Part II, course overview lecture | 21 min | skipped | T3, T4 |
| `bdeac510` | TED talk on climate innovation (Xu Hao), titled "Video" | 13 min | ready, with on-screen text | T5, T6 |
| `55705079` | TED interview, Chris Anderson and Sam Altman, titled "Prismic Toolbar iFrame" | 47 min | ready, with on-screen text | T7, T8, T9 |
| `75c17869` | Introduction to Computer Graphics 14:15–15:15 (Ofir), TA recitation | 61 min | **ready (was failed)**, 82 keyframes, about one a minute | T10–T13, T18 |
| `6aa8f5ad` | 2004 Food Network broadcast with ads (Internet Archive) | 34 min | ready, with on-screen text | T14–T17 |

## 3. Results at a glance

Tools separated by `+` ran in the same round, in parallel. Tools separated by `→` ran in sequence. "sheet" is `view_candidates`, "seq" is `view_sequence`, and "close" is `view_frames_closeup`. The last three columns are each test's total time: today's run A, today's run B, and the 2026-10-02 report.

| Test | Behavior | Tools called (run A; run B if different) | Grade A / B | Run A | Run B | 10-02 |
|---|---|---|---|---|---|---|
| T1 | Basic info | `get_video_info` | Pass / Pass | 4.9 s | 4.7 s | 5.5 s |
| T2 | Ambiguous ("the term") | search + outline → chapter; B: → chapter + search → chapter → memory | Pass / Pass | 9.8 s | 13.3 s | 17.1 s * |
| T3 | Outline | outline | Pass / Pass | 9.4 s | 7.2 s | 7.3 s * |
| T4 | Viewer position, speech | outline → chapter → memory | Pass / Pass | 10.0 s | 9.4 s | 9.7 s |
| T5 | Specific fact | search + outline | Pass / Pass | 4.4 s | 4.9 s | 4.9 s |
| T6 | On-screen text | screen text + search | Pass / Pass | 4.9 s | 5.5 s | 6.1 s |
| T7 | Basic info, misleading title | info + outline + search; B: info → outline + search | Pass / Pass | 7.4 s | 8.4 s | 8.3 s |
| T8 | Context within a chapter | search + outline → memory | Pass / Pass | 7.9 s | 9.5 s | 8.6 s |
| T9 | Viewer position, visual (paused) | close | Pass / Pass | 6.3 s | 6.1 s | 6.9 s |
| T10 | Context across a chapter boundary | search + outline → chapter; B: → memory | Pass / Pass | 9.1 s | 11.6 s | 10.1 s |
| T11 | Larger section (3 chapters) | search + outline → 3 × chapter | Pass / Pass | 14.4 s | 15.5 s | 16.0 s |
| T12 | Not in the video | search + outline → search + chapter | Pass / Pass | 9.1 s | 9.7 s | 11.4 s |
| T13 | Slide text, index now ready | screen text + search → chapter → close → sheet → picture search → seq; B: → chapter → close → close | Pass / Pass | 42.3 s | 16.3 s | 2.9 s, declined |
| T14 | Finding when | search + outline; B: → 2 × chapter | Pass / Pass | 9.2 s | 11.2 s | 12.2 s * |
| T15 | Ambiguous (several candidates) | search + outline → 3–4 × chapter (+ memory) → 3 × memory (+ search) | Pass / Pass | 15.5 s | 14.4 s | 16.1 s * |
| T16 | Action or sequence (visual) | picture search + search → sheet → 2 × seq → close; B: → seq | Pass / Pass | 37.5 s | 41.2 s | 39.0 s |
| T17 | Where and how long (visual) | picture search + search → sheet → 2 × seq → seq; B: 2 × seq + search → memory → seq | Partial / Partial | 50.7 s | 47.5 s | 46.4 s * |
| T18 | Where on screen, index now ready | search + outline → 2 × chapter + picture search → sheet; B: search + picture search + outline → chapter + sheet | Fail / Fail | 19.1 s | 16.1 s | 6.6 s, declined |

\* The prompt was fixed after the main 10-02 run, and these five tests were re-run twice with the fix. Today's code includes that fix, so the 10-02 number here is the average of those two re-runs: T2 11.8 and 22.5 s, T3 7.4 and 7.1 s, T14 11.5 and 12.9 s, T15 16.0 and 16.1 s, T17 44.2 and 48.6 s. Before the fix, the main 10-02 run took 8.1 s (T2), 14.8 s (T3), 25.3 s (T14), 12.5 s (T15) and 49.6 s (T17).

## 4. Per-test detail

Times are in seconds from the start of the run. Tests whose answers match 10-02 are kept short.

### T1–T12: transcript and simple visual tests (all Pass)

- **T1, basic info:** "'Goodbye Tokenmaxxing: From AI Usage to Agentic AI Outcomes' … from YouTube", in both runs. The comments tool was offered and not called.
- **T2, "Who coined the term?":** one line per term in both runs. Valuemaxxing is credited to Mark Boroditsky, CRO of Nebus [04:24–05:16]. For tokenmaxxing, the video names no originator [00:42–01:48]. Neither run uses "if you mean".
  - Run B took 5 model requests: an extra search, a second chapter read and a memory read before answering.
- **T3, outline:** `get_video_outline` alone, in both runs. All 5 chapters, with the outline's ranges [00:10–04:21] … [18:01–20:54].
- **T4, "What's being talked about right now?" at 11:00:** the timestamp recipe (outline → chapter → memory). The answer is the VM translator [09:27–11:14], and it avoids the OS section that starts at 11:15.
- **T5, solar reflection:** "93% of solar radiation" [09:00–10:28]. It didn't take the 80% distractor. **New:** the outline is now called alongside the search for a plain fact question. It costs no round and about 1,400 input tokens.
- **T6, ethanol slide years:** "1784 and 1875" [01:10-01:22], from the screen text.
- **T7, what and who:** "a TED interview with Sam Altman, conducted by Chris Anderson" [00:00–00:52], plus a topic line with 4 citations, all moment spans.
- **T8, before the growth question:** the GPU begging and the compute constraint, in answer to the DeepSeek question [08:26–09:13]. This is correct.
- **T9, "What is this?" paused at 37:12:** one close-up and no search. It describes the baby announcement post and the NICU line, matching the keyframe OCR.
- **T10, after the padding note:** seam carving [35:02–37:25], with "just a side note … I don't think it should concern you too much" [34:21–35:00].
  - Run A took the quote straight from the search hit's text, with no memory read.
  - Run B read the memory context.
- **T11, seam-carving summary:** all 3 seam-carving chapters were read in one round, and every part was covered, including the NumPy/Numba material [51:57–59:30].
- **T12, ray tracing:** two different searches, then "I couldn't find an explanation of ray tracing". It pointed to the nearest section, how a digital image represents the 3D world [12:07–14:27].
  - It no longer says what it searched for, as the 10-02 answer did ("after searching both for the term and for tracing light through a 3D scene"). See §7, issue 4.

### T13: Slide text when he explains convolution (Pass, both runs) — expected path changed
- **Query:** "What's written on the slide when he explains convolution?"
- **Ground truth:**
  - "Convolution" is first named at 19:16, while the "Image Filtering: original − smoothed = details" slide is on screen.
  - It is demonstrated from 23:39 with a 3×3 filter, the memory "The TA demonstrates convolution with a 3-by-3 filter …" [23:39–25:49]. The slide there reads "An image I_2 is obtained by applying the following 3x3 filter twice on image I: ⅓[0 1 0; 0 1 0; 0 1 0] … Can the same image be obtained from a single Filtering operation?"
  - It is worked through mathematically from 28:52.
  - No slide contains the word "convolution".
- **Answer (both runs):** the 3×3-filter slide, quoted exactly, with the matrix and the question [24:00] (A) and [24:10] (B). The citations come from close-ups.
- **Check:**
  - Correct for the demonstration, the moment that best fits "explains". Neither run mentions the 19:16 or 28:52 slides. That is acceptable for a single "the slide" question.
  - **Run B's path is the recipe:** screen text + search → chapter → close-up on 3 times → close-up on 3 more. 16.3 s.
  - **Run A wandered:** it took 5 visual calls and 3 looks, in 42.3 s with 7 model requests.
    1. Its first close-up was on 3 guessed times (24:00, 18:20, 30:00), and it already had the answer at 24:00.
    2. Then a contact sheet over 21:40–25:00.
    3. Then a picture search, for a text slide.
    4. Then a 9-frame sequence over 18:20–23:40 (10.5 s).
  - `search_screen_text` returned the 3 course-title slides for "slide explaining convolution", with no `weak` mark (§6).

### T14: Where they work on the pumpkin pies (Pass, both runs)
- **Answer:** the squash [13:31–14:41], the filling [14:42–16:52], the baking explanation [17:03–17:22], the meringue [20:54–22:36] and the finale [30:15–30:38]. All the locations are correct and complete.
- **No visual tools in either run.** Run A answered from the first round alone: search + outline, in 9.2 s.
- **The count is wrong in both runs.** Each opens with "in two main sections", then lists 4 sections plus the finale (§7, issue 5). One of the two 10-02 after-fix runs did the same.

### T15: How long does it bake? (Pass, both runs)
- **Answer:** all 4 candidates, one line each:
  - the fruit crisp, about 45 min (30, then 15 with coals on the lid) [05:21–06:18];
  - the crème caramel and bread pudding, no time given [09:14–09:55];
  - the pumpkin pies and their meringue, no time given [17:03–17:22] [20:54–22:36].
- **Check:** true, and complete as far as the chapters go. The meringue's "let that cook for few minutes" (22:46) sits just past the meringue chapter's end (22:36), so the chapter reads can't reach it.

### T16: Hollowing the acorn squash, step by step (Pass, both runs)
- **Answer:**
  - **Run A, six steps:**
    1. Trims the bottom [13:46].
    2. Cuts the top off as a lid [13:51].
    3. Starts scraping with a spoon [13:56–13:59].
    4. Scoops out the interior [14:03–14:10].
    5. Shows the hollow shell [14:13].
    6. Puts it in the roasting pan [14:17–14:20].
  - **Run B, five steps.** It says the exact cuts are hard to see in the frames, and names the narration ("trims the bottom and cuts off the top") as the source for that step.
- **Check:** frames every 3 s match:
  - the knife at 13:38–13:53;
  - the spoon in the opening at 14:05–14:08;
  - the hollow shell held up with its cap at 14:14;
  - into the pan at 14:17–14:20.

  Every visual citation came from a look.

### T17: Where he whisks the eggs, and for how long (Partial, both runs)
- **Ground truth** (frames every 1 s, unchanged from 10-02):
  - **Custard:** he whisks the eggs and sugar from 08:37 to 08:49, about 12 s, and briefly again at 08:54–08:58.
  - **Pumpkin filling:** he whisks from 14:48 with pauses until about 16:00, about 45–55 s of active whisking.
  - **17:10–17:23:** he talks and gestures, touches the whisk standing in the bowl at about 17:15, and turns to the stand mixer at 17:17. There is no whisking.
- **Run A:**
  - Picture search + search → contact sheet → sequences over 08:18–08:56 and 14:36–15:14 → a narrower sequence over 14:45–15:14.
  - **Custard:** "approximately 10–19 seconds" [08:32–08:51]. The truth, about 12 s, is in the range.
  - **Pumpkin:** "about 21–29 seconds, with pauses" [14:45–15:14]. That is short, because no look went past 15:14.
- **Run B:**
  - The same first two rounds. Then a transcript search for whisking around the pies, then a memory read, then a sequence over 17:10–17:34.
  - **Custard:** "about 10–19 seconds" [08:32–08:51]. Correct.
  - **Pumpkin:** "intermittent whisking over roughly 30 seconds" [14:42–15:24]. Short, as in run A.
  - **A third session that didn't happen:** "Around 17:13–17:19, lasting approximately 6–12 seconds" [17:10–17:22]. The contact sheet had said "holds a whisk … and stirs" at 17:14. The sequence said "appearing to whisk or stir" at 17:13 and "consistent with continued hand-whisking" at 17:19. The agent turned two hedged observations into a measured duration (§7, issue 3).
  - Run B spent its last look on the 17:14 lead, which no moment supports. The memory it read was the filling at 14:42–16:52.
- **Latency:** 50.7 s and 47.5 s. Tool time was 31.0 s and 25.6 s. The two parallel coarse sequences took 15.0 s and 12.1 s.

### T18: Where there is an example of what image details look like (Fail, both runs)
- **Query:** "where in the video we can find an exampe of how image details looks like"
- **Ground truth:**
  - The slide "Image Filtering": original − smoothed = ? is up from about 15:40.
  - At 17:08 the "?" becomes an edge image labelled **"details"**. It stays until 19:27.
  - The memory [16:15–19:30] reads "edges as large changes between neighboring pixels … extracting them by subtracting a blurred image".
  - "Details" is never spoken. The OCR keyframe inside that window, at 17:28, reads only "Image Filtering • What is the result image ?", without the small "details", "original" and "smoothed" labels.
- **Run A (19.1 s):**
  - Search + outline → both image chapters + picture search, which led with **17:56**, inside the right slide.
  - The contact sheet on 17:56, 19:50 and 13:10 said:
    - 17:56: "a sequence of small grayscale images, including an original-looking photo and a darker result, with an equals sign", `present: yes`.
    - 19:50: "a street/bicycle scene on the left and a gray image with prominent contour-like edges on the right", `present: yes`.
  - **Answer:** "A good example is around 19:50 … a filtered version highlighting its edges" [19:50], with the explanation at [19:31–23:37]. That is the derivative slide, the one after the "details" example.
  - It had the right frame and didn't take a close-up to read its labels.
- **Run B (16.1 s):**
  - Search + picture search + outline → chapter + contact sheet. The picture search ("example image showing fine details or image detail settings") returned only 13:10 and 58:06. The agent added 19:32 to the sheet itself.
  - **Answer:** the "Images" bullet slide, "an image is a grid of pixels" [13:10], and the derivative slide [19:32]. Neither shows image details.
- **Check:** neither run reached 17:08–19:27. Both read the chapter that lists "subtracting a blurred image" [16:15–19:30], and neither connected "details" to it.

## 5. Latency

### Per test

| Test, run | Total s | 1st tool s | 1st answer text s | Tool time s | Model time s | Model requests | Tool calls | Input tok | Cached tok | Output tok |
|---|---|---|---|---|---|---|---|---|---|---|
| T1 A | 4.9 | 2.7 | 4.2 | 0.0 | 4.8 | 2 | 1 | 6028 | 2971 | 49 |
| T1 B | 4.7 | 2.7 | 4.1 | 0.0 | 4.7 | 2 | 1 | 6028 | 6022 | 49 |
| T2 A | 9.8 | 2.6 | 8.2 | 0.2 | 9.5 | 3 | 3 | 11620 | 9980 | 240 |
| T2 B | 13.3 | 2.3 | 12.0 | 0.3 | 13.0 | 5 | 6 | 20772 | 18553 | 342 |
| T3 A | 9.4 | 3.1 | 5.3 | 0.0 | 9.4 | 2 | 1 | 5634 | 2579 | 220 |
| T3 B | 7.2 | 2.0 | 3.6 | 0.0 | 7.2 | 2 | 1 | 5634 | 5628 | 225 |
| T4 A | 10.0 | 2.0 | 8.5 | 0.1 | 9.9 | 4 | 3 | 14166 | 9326 | 173 |
| T4 B | 9.4 | 1.7 | 7.7 | 0.1 | 9.3 | 4 | 3 | 14166 | 14154 | 173 |
| T5 A | 4.4 | 2.3 | 3.7 | 0.1 | 4.3 | 2 | 2 | 10774 | 4938 | 87 |
| T5 B | 4.9 | 2.6 | 4.2 | 0.1 | 4.8 | 2 | 2 | 10774 | 9876 | 87 |
| T6 A | 4.9 | 2.7 | 4.3 | 0.2 | 4.7 | 2 | 2 | 10694 | 9858 | 94 |
| T6 B | 5.5 | 2.6 | 4.9 | 0.2 | 5.3 | 2 | 2 | 10694 | 9874 | 94 |
| T7 A | 7.4 | 3.7 | 5.5 | 0.1 | 7.3 | 2 | 3 | 12877 | 9856 | 181 |
| T7 B | 8.4 | 1.7 | 6.0 | 0.1 | 8.2 | 3 | 3 | 17893 | 14877 | 183 |
| T8 A | 7.9 | 2.6 | 6.3 | 0.2 | 7.7 | 3 | 3 | 19017 | 16340 | 188 |
| T8 B | 9.5 | 3.5 | 7.9 | 0.2 | 9.3 | 3 | 3 | 18735 | 16359 | 181 |
| T9 A | 6.3 | 2.1 | 4.3 | 0.8 | 5.6 | 2 | 1 | 10757 | 4973 | 98 |
| T9 B | 6.1 | 2.0 | 4.1 | 0.8 | 5.3 | 2 | 1 | 10757 | 10751 | 96 |
| T10 A | 9.1 | 3.4 | 7.5 | 0.1 | 9.0 | 3 | 3 | 18266 | 16386 | 187 |
| T10 B | 11.6 | 2.8 | 9.8 | 0.2 | 11.5 | 4 | 4 | 25693 | 23206 | 239 |
| T11 A | 14.4 | 3.7 | 8.6 | 0.1 | 14.3 | 3 | 5 | 19990 | 16775 | 520 |
| T11 B | 15.5 | 2.6 | 7.5 | 0.1 | 15.4 | 3 | 5 | 19992 | 16791 | 577 |
| T12 A | 9.1 | 2.4 | 7.3 | 0.1 | 8.9 | 3 | 4 | 22096 | 17401 | 231 |
| T12 B | 9.7 | 2.8 | 8.1 | 0.2 | 9.5 | 3 | 4 | 21494 | 17112 | 222 |
| T13 A | 42.3 | 4.3 | 40.6 | 17.9 | 24.5 | 7 | 7 | 64775 | 57473 | 471 |
| T13 B | 16.3 | 2.5 | 14.6 | 1.4 | 14.9 | 5 | 5 | 43030 | 38402 | 313 |
| T14 A | 9.2 | 2.7 | 5.9 | 0.2 | 9.0 | 2 | 2 | 12579 | 9858 | 278 |
| T14 B | 11.2 | 2.6 | 8.0 | 0.1 | 11.1 | 3 | 4 | 20654 | 17323 | 357 |
| T15 A | 15.5 | 2.4 | 12.6 | 0.2 | 15.3 | 4 | 10 | 32405 | 25674 | 542 |
| T15 B | 14.4 | 2.1 | 12.0 | 0.2 | 14.1 | 4 | 9 | 31653 | 26128 | 520 |
| T16 A | 37.5 | 4.6 | 32.2 | 15.8 | 21.7 | 5 | 6 | 42361 | 35730 | 584 |
| T16 B | 41.2 | 4.0 | 35.9 | 19.3 | 21.9 | 5 | 6 | 40312 | 35066 | 622 |
| T17 A | 50.7 | 3.0 | 48.5 | 31.0 | 19.7 | 5 | 6 | 36967 | 31699 | 581 |
| T17 B | 47.5 | 2.8 | 44.3 | 25.6 | 21.9 | 6 | 8 | 51843 | 45597 | 653 |
| T18 A | 19.1 | 2.7 | 17.5 | 3.8 | 15.3 | 4 | 6 | 28477 | 24905 | 370 |
| T18 B | 16.1 | 3.7 | 14.2 | 4.2 | 11.9 | 3 | 5 | 19723 | 16931 | 359 |

- **Model time** is the total minus the time any tool was running.
- **"1st answer text"** is when the first answer text reached the caller, which is when the user starts reading.

### Against the 2026-10-02 latency results

The 10-02 baseline below is the 10-02 suite run. For T2, T3, T14, T15 and T17 it is the mean of the two after-fix runs, since those fixes are now merged. T13 and T18 are left out of the totals, because the visual index change gave them a different job.

| | 10-02 suite | 10-02 with after-fix runs | Now, run A | Now, run B |
|---|---|---|---|---|
| 16 unchanged tests, sum | 236.8 s | 225.6 s | 210.4 s | 220.0 s |
| 16 unchanged tests, median / mean | 9.9 / 14.8 s | 9.9 / 14.1 s | 9.1 / 13.2 s | 9.6 / 13.8 s |
| All 18 tests, median / mean | 9.2 / 13.7 s | – | 9.3 / 15.1 s | 10.4 / 14.0 s |
| First tool call, median | 3.0 s | – | 2.7 s | 2.6 s |
| Model time, share of wall time | 80% | – | 74% | 79% |
| Model time per request | 3.9 s | – | 3.5 s | 3.3 s |

The 10-02 report printed the all-tests median as 9.7 s. Recomputed the same way as here (the mean of the two middle values), it is 9.2 s.

Per test, against that baseline (mean of runs A and B; negative is faster):

| Faster by 1 s or more | Within ±1 s | Slower by 1 s or more |
|---|---|---|
| T2 −5.6 s, T12 −2.0 s, T14 −2.0 s, T11 −1.1 s, T15 −1.1 s | T1, T4–T10, T16 | T17 +2.7 s, T3 +1.1 s |

What the 10-02 latency observations look like now:

1. **"Model round trips still dominate."** They still do, at 74–79% of wall time. Each request got slightly cheaper (3.9 → 3.3–3.5 s), and the first tool call now arrives at a median 2.6–2.7 s, against 3.0 s. The rewritten prompt costs little in input: T1 used 6.0k input tokens over its 2 requests, against 5.7k.
2. **"Streaming hides part of the writing."** This still holds. T11's text starts at 7.5–8.6 s of 14.4–15.5. T3's starts at 3.6–5.3 s of 7.2–9.4.
3. **"The cold starts are gone."** This holds. The first picture search of run A took 1.9 s and the second 1.0 s. All 5 later picture searches took 0.18–0.20 s.
4. **"The multi-part rules cost rounds."** Less than after the fixes. T2 took 9.8 s in run A, with one read round, against the after-fix 11.8 and 22.5 s. Run B took two extra rounds (13.3 s). T15 still needs a memory round (14.4–15.5 s). T14 run A skipped the chapter round entirely (9.2 s).
5. **"Visual answers cost 25–50 s."** Unchanged. T16 took 37.5–41.2 s and T17 47.5–50.7 s. A coarse 9-frame sequence still takes 6–15 s, and two in parallel take as long as the slower one. T13 shows how much a visual path can vary: 16.3 s with 2 close-ups, against 42.3 s with 5 visual calls.

### Per tool (both runs)

| Tool | Calls | Median | Max |
|---|---|---|---|
| `get_video_info` | 4 | 0.03 s | 0.03 s |
| `get_video_outline` | 24 | 0.03 s | 0.03 s |
| `get_chapter_context` | 29 | 0.03 s | 0.06 s |
| `get_memory_context` | 14 | 0.07 s | 0.09 s |
| `memories_semantic_search` | 33 | 0.09 s | 0.19 s |
| `search_screen_text` | 4 | 0.17 s | 0.19 s |
| `search_visual_moments` | 7 | 0.19 s | 1.91 s (first call of run A) |
| `view_frames_closeup` | 6 | 0.7 s | 0.8 s |
| `view_candidates` | 7 | 4.2 s | 6.1 s |
| `view_sequence` | 12 | 9.9 s | 15.0 s |

## 6. Tool-call behavior

| Check | Result |
|---|---|
| Correct tools chosen | 35 of 36 runs as expected. T13 run A took 3 extra visual calls after it already had the slide. |
| Correct order | Yes in all 36. Independent calls were batched, and dependent calls were sequential. |
| Unnecessary calls | T13 A's picture search for a text slide, its contact sheet and its sequence. T17 B's sequence on the 17:14 lead, which no moment supports. The outline added to the first round of fact questions (T5, T8), which is cheap. |
| Correct use of tool results | Mostly. **But:** T18 A had the right frame at the top of its picture search and its contact sheet, and chose another one. T17 B treated hedged frame observations as whisking. |
| Grounded final answers | All 36. No outside facts and no invented timestamps. T17 B's third session is grounded in a tool result, but that result was wrong. |
| Citations | Every citation is inside a span a tool returned. All are `MM:SS` or `MM:SS–MM:SS`; none followed the prompt's new `[MM–MM]` wording. |
| Offered-tool restraint | The comments tool was not called in T1 or T2. No visual tool was used for a speech question (T5, T7, T14). |
| Internal leakage | None. |

Problems found in the data and the tools (not the agent):

- **OCR misses small slide labels.** On `75c17869`, the keyframe at 17:28 reads only the slide title and bullet. The labels "original", "smoothed" and "details" above the images were not read. So `search_screen_text` with `words=["details"]` finds nothing, and T18 can't be answered from the screen text.
- **OCR keyframes are sparse on a static slide recording.** The video has 82 keyframes over 61 min. A new keyframe comes with a scene change or with new text that OCR read, so a slide whose picture changes (the "?" replaced by the "details" image at 17:08) gets none until the next minute.
- **`search_screen_text` never marks a meaning hit `weak`.** For "slide explaining convolution", with no exact-word match, it returned the 3 course-title slides (00:36, 00:42, 02:46) as plain hits. The agent can't tell from the result that nothing relevant was found.

## 7. Prompt and tool behavior against what they claim

| # | Issue | Where | Seen in the runs |
|---|---|---|---|
| 1 | **The rewritten prompt doesn't render as written.** In the Python string, a `\` at a line's end joins it to the next with no space: "…the VidSeek Video Agent.Your job is…", "…moments.A round is…", and the three "Where Is This Discussed?" steps run into one line. `1\.` is an invalid escape and raises a `SyntaxWarning` at import. There is also a literal `&#x20;`, Hebrew gershayim (`״`) around the example, "where of if", and a step that ends in a comma. | `prompt.py`, `SYSTEM_PROMPT` | No failure traced to it yet. The model reads joined sentences fine, but the warning appears whenever the module is compiled. |
| 2 | **Two steps point to a section that no longer exists.** "as in 'Finding Where Something Is'" appears in "Where Is This Discussed?" and in "Questions With More Than One Possible Meaning". That section was replaced by "Video navigation" → "Workflow". "Where Is This Discussed?" now has two numbered lists for the same job. | `prompt.py` | No failure yet: T2, T14 and T15 still pass. |
| 3 | **Hedged frame observations become facts.** The visual prompt says "Never state what is shown until a look has shown it", but it doesn't say how to read a look that only half-shows it ("appearing to", "consistent with"). | `prompt.py`, `VISUAL_PROMPT`; `view_sequence` | T17 B: a 6–12 s whisking session at 17:13–17:19 that didn't happen. |
| 4 | **The not-found rule lost "saying what you searched".** The old bullet read "I couldn't find X in the video": otherwise, saying what you searched. It is now just "I couldn't find X in the video". | `prompt.py`, "Core Principle" | T12: both runs omit what was searched. |
| 5 | **Counts in the opening line don't match the list.** "in two main sections" is followed by 4 sections and the finale. | `prompt.py`, response format | T14: both runs here, and one of the two 10-02 after-fix runs. |
| 6 | **The citation format now reads `[MM–MM]` and `[H\:MM–H\:MM]`.** The seconds are gone, and the backslash is left over from a Markdown editor. A model that follows it literally would write `[14–16]`, which the citation filter can't match. | `prompt.py`, "Citations" | Not followed: all 36 answers used `MM:SS`, copied from the tool timestamps. |
| 7 | **A contact sheet can't read small text, and a `yes` on such a frame isn't followed up.** The prompt says a yes "for a small detail" needs a close view, but the sheet doesn't say that a label was unreadable. | `view_candidates`, `VISUAL_PROMPT` | T18 A: the right frame got `yes` with "small grayscale images", and no close-up was taken. |

## 8. Recommendations

Ordered by expected impact.

1. **Repair the prompt text (issues 1, 2, 4, 6).**
   - Remove the trailing `\` characters, `&#x20;` and the `״` marks. Write the numbered steps as `1.`, not `1\.`.
   - Either restore a short "Finding Where Something Is" section or point both references to "Video navigation" → "Workflow". Keep one list of steps in "Where Is This Discussed?".
   - Restore the citation formats `[MM:SS–MM:SS]` and `[H:MM:SS–H:MM:SS]`.
   - Restore "saying what you searched" in the not-found bullet.
   - Add a test that renders `SYSTEM_PROMPT` and checks that it has no `\` followed by a newline and no `SyntaxWarning`, and that every section a step names exists.
2. **Read hedged observations as unclear (issue 3).**
   - Add to "How to investigate": a frame described as "appearing to", "consistent with" or "may be" doing the action is unclear, not a yes. Don't report a time or duration from unclear frames alone.
   - In `view_sequence`'s answer, ask the image model to say `unclear` rather than hedge inside a positive observation.
3. **Make small on-screen labels findable (§6, T18).**
   - Run OCR on a keyframe at a higher resolution, or on crops of a slide's image regions, so that labels such as "details" are read.
   - Add a keyframe when the picture of a slide changes, not only when its OCR text changes. Recording-style lectures change images under a fixed title.
4. **Follow a sheet `yes` on small content with a close-up (issue 7).** When the question names a word or label, and the sheet's description doesn't contain it, view the top frame closely before choosing between frames. In T18 A, one close-up on 17:56 (about 0.7 s) would have read "details".
5. **Mark `search_screen_text` meaning hits `weak` the way scored search does (§6).** With no exact-word match and no meaning hit that stands out, say so in the note. In T13 the agent would then have gone to the close-ups without weighing 3 title slides.
6. **Don't open with a count that the list doesn't keep (issue 5).** Add one line to the response format: give a number of parts only if the list that follows has exactly that many.

## 9. Not covered

- **`get_viewer_comments`:** `comment_embeddings` has 0 rows.
- **Untimed transcripts and non-English transcripts:** none exist in the DB.
- **Multi-turn follow-ups,** including reuse of an earlier turn's citations. The rewrite removed the line saying that moments returned earlier in the conversation can still be cited, and that is untested.
- **Variance beyond two runs.** T2, T13 and T17 took different paths in A and B.
- **The HTTP/SSE layer, the web client and the extension.**
- **Dropped-citation counts:** the harness saw the answer after the citation filter.

## 10. After-fix re-run

- **Branch:** `fix/video-agent-prompt-repair-and-durations`. It applies recommendations 1 and 6, and part of the duration work from T17:
  - **Prompt repair:** no line joins, no invalid escape, no editor artifacts. Citations are `[MM:SS–MM:SS]` again. "Video navigation → Workflow" is the one procedure, and the other sections point to it.
  - **Restored rules:** "saying what you searched", citing moments from earlier turns, reading every chapter of a topic, "two searches are enough", and the resting-time example.
  - **New rules:**
    - Open with a count of parts only when the list keeps it.
    - The image model ends a sequence answer with "Still showing at the first/last frame (MM:SS)" when a start, end or duration question's action reaches the window's edge.
    - A duration sequence covers the whole supporting moment.
- **Method:** one run each of T2, T12, T14, T15 and T17, with the same harness as §2. Answers were checked against the ground truth in §4. Raw tool results were not kept, so it is not known whether the image model wrote the new edge phrase.

| Test | Grade | Tools called | Total | Against runs A / B |
|---|---|---|---|---|
| T2 | Pass | search + outline → 3 × chapter + search | 10.8 s | 9.8 / 13.3 s |
| T12 | Pass, **fixed** | search + outline → search + chapter | 13.9 s | 9.1 / 9.7 s |
| T14 | Pass, **fixed** | search + outline → 3 × chapter | 39.5 s | 9.2 / 11.2 s |
| T15 | Pass | search + outline → 5 × chapter → 3 × memory | 37.2 s | 15.5 / 14.4 s |
| T17 | Partial | picture search + search → sheet → chapter → 2 × seq → seq | 56.3 s | 50.7 / 47.5 s |

- **T12:** "I couldn't find an explanation of ray tracing in this lecture, searching both for the term and for tracing light rays through a 3D scene." It now names what it searched.
- **T14:** it opens with "Here are the relevant moments", with no count, then lists the same 5 correct places.
- **T2 and T15:** these still pass after the restructure. T2 gives one line for each term, and T15 covers all 4 desserts.
- **T17:**
  - **Pumpkin, better:** "roughly a minute", intermittent, from 14:48 to 15:53, against about 45–55 s of active whisking from 14:48 to about 16:00. Its first sequence spanned the whole filling moment, 14:42–16:52, and its narrower pass spanned 14:42–16:04. Runs A and B stopped at 15:14–15:24 and reported 21–30 s.
  - **Custard, worse:** "approximately 20–34 seconds" [08:31–09:05], against about 12 s from 08:37 to 08:49, plus 08:54–08:58. The location, 08:38–08:58, is right.
  - **Why the custard got worse:** its whole-moment sequence ran 08:18–09:12, with 9 frames 6.75 s apart. The only narrowing look went to the pumpkin, which had the widest range. So the range follows the duration rule, but at a spacing too coarse for a 12 s action. Runs A and B used 08:18–08:56 and gave 10–19 s.
  - **No whisking was invented at 17:13 this time.** That was one run, and recommendation 2 is not applied, so this is not a fix.
- **Latency:** T14's first tool call came at 27.6 s, against 2.7 s in runs A and B. T15's last tool finished at 11.0 s, and its answer text started at 34.7 s. Both waits were model time, and their cause is not known from one run. The other three tests are within about 1–4 s of runs A and B.

What it leaves open:

1. **Duration windows are now wider, but the looks did not increase.** For a short action inside a long moment, either give one more look to narrowing, or start the sequence with more frames when the moment is long against the action.
2. **Recommendations 2–5 still apply:** hedged observations, small on-screen labels (T18), the contact-sheet close-up, and weak screen-text hits.
3. **Re-run T14 and T15** to see whether their slow model requests repeat.
