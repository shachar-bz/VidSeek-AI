# Video Agent Evaluation Report

- **Date:** 2026-10-02.
- **Agent under test:** `backend/video_agent` at `main` 81cb46f, model `gpt-6.1-sol` on the OpenAI Responses API, image model `gpt-6-luna`.
- **Scope:** two "where in the video do we see X" questions: one on a video with a ready visual index, one on a video whose visual index failed.
- **Method:** each test ran once. Ground truth was set before the run from the transcript and from frames extracted every 1–2.5 s, and every claim in the answers was checked against it.
- **Code changes:** none. The earlier 16-test report (2026-09-30) is in git history before this commit.

## 1. Summary

| Test | Video | Visual index | Grade | Latency |
|---|---|---|---|---|
| T1: whisking the eggs, and for how long | `6aa8f5ad`, Food Network broadcast (Internet Archive) | ready | Partial | 40.7 s |
| T2: an example of what image details look like | `75c17869`, Introduction to Computer Graphics 14:15–15:15 (Ofir) | failed (`visual_indexing_interrupted`) | Fail | 9.4 s |

- **No hallucinated facts.** Everything both answers say is true of the moments they cite.
- **T1 found both whisking sessions,** but it put the custard session at about 7 s when it is about 20 s. Its frames were 6.75 s apart, and the look budget was gone before it could look closer.
- **T2 pointed to the wrong example.** The slide that shows "details" is at 17:08–19:27. The agent sent the viewer to 19:31, the next slide (a vertical-derivative edge image). The word "details" appears only on screen, never in the speech, and the screen can't be searched because the visual index failed.

## 2. Setup

- **Harness:** each test ran through the production `PydanticConversationAgentRunner.stream()` around `build_agent()`, wrapped by a proxy that timestamps every pydantic-ai event and keeps the raw tool results.
  - Citations went through the production streaming `CitationFilter`.
  - The HTTP/SSE layer was not exercised.
- **Per-run setup:** `has_comments` and `visual_availability` were computed the same way as in `api/routes/conversations.py`. No viewer position was given, and every test started with empty history. Nothing was written to the database.
- **Warm-up:** before timing, both embedding models were loaded the way the API's startup preload does (`api/model_preload._load_models`), and the DB pool was opened. That took 6.8 s.
- **Environment:** a macOS (Apple Silicon) dev machine, the remote Azure Postgres and the OpenAI API.
- **Limits:** each test ran once, so a single failure is a lead, not a rate.

## 3. Results at a glance

Tools separated by `+` ran in the same round, in parallel. Tools separated by `→` ran in sequence.

| Test | Tools called | Expected | Grade |
|---|---|---|---|
| T1 | picture search + transcript search + outline → contact sheet (6 frames) + `get_chapter_context` (custard) → 3 × `view_sequence` + `get_memory_context` | the same first two rounds, then sequences on the two real sessions only | Partial |
| T2 | transcript search + outline | search + outline → `get_chapter_context` on "Image filters and convolution", to scan its moment summaries | Fail |

## 4. Per-test detail

Times are in seconds from the start of the run.

### T1: Where he whisks the eggs, and for how long (Partial)

- **Query:** "where in the video we see the man whisk the eggs and how much time he do it?"
- **Ground truth** (frames every 1 s):
  - **Custard for the crème caramel and bread pudding:** he whisks the yolks, eggs and sugar from 08:29 to 08:49, pausing about 2 s at 08:32 while the sugar goes in. That is roughly 20 s. He whisks again from about 08:54 to 08:58 as the hot milk is poured in. Speech: "I have here some yolks, eggs, and sugar. I mix all that together" (08:20–08:35).
  - **Pumpkin filling for the squash shells:** "some eggs. I have a whisk around here" (14:43). He whisks the eggs from 14:48, then keeps whisking as the sugar and spices (to about 15:09), milk, cream and pumpkin go in, until about 16:00. That is about 70 s, broken up by pours.
- **Calls:**
  1. At 4.1 s, in parallel:
     - `search_visual_moments`, "a man whisking eggs in a bowl with a whisk". The top two hits were 14:58 and 14:48, plus 08:44 and 09:06 from the custard and a false lead at 17:14.
     - `memories_semantic_search`. It returned the pumpkin-filling memory and 3 sugar/meringue memories, but not the custard memory.
     - `get_video_outline`.
  2. At 8.7 s, in parallel:
     - `view_candidates` on 6 frames (9.3 s). It said whisking was present at 14:58, 17:14 and 08:44, unclear at 14:48 and 09:06, and absent at 09:48.
     - `get_chapter_context` on the custard chapter.
  3. At 24.9 s, in parallel:
     - `view_sequence` over 08:18–09:12 with 9 frames (7.9 s).
     - `view_sequence` over 14:36–15:54 with 9 frames (10.1 s).
     - `view_sequence` over 17:10–17:34 with 6 frames (6.6 s).
     - `get_memory_context` on the custard memory.

  That used 5 of 6 visual calls and 4 of 4 looks.
- **Answer:**
  > I found two places where he whisks the egg mixture:
  > - **Around 08:38–08:45:** He visibly whisks the eggs for the custard. That's about **7 seconds of confirmed whisking**, though the exact start and stop aren't clear because of the cuts. [08:38] [08:45]
  > - **Around 14:55–15:54:** He whisks the pumpkin-custard mixture **intermittently over about a minute**, pausing to add ingredients—not whisking continuously. [14:55] [15:15] [15:24] [15:44–15:54]
  >
  > He says to mix the eggs, yolks, and sugar **very well**, but doesn't specify a whisking time in seconds. [08:01–09:10]
- **Check:**
  - **Where: correct.** Both sessions were found, and each was matched to the right dish. The 17:14 lead was checked with a sequence and correctly dropped: it is a stand mixer, not hand whisking. Every cited time came from a look, apart from the memory span in the last line.
  - **Pumpkin duration: about right.** "About a minute" against roughly 70 s (14:48 to about 16:00). The start is 7 s late: the sequence's frame at 14:45 caught him reaching across the counter, and its next frame was 14:55.
  - **Custard duration: understated about 3×.** The answer says 7 s; it is about 20 s.
    - With 9 frames over 54 s, the frames were 6.75 s apart. The 08:31 frame fell on the 2 s sugar pour and was read as "no whisking".
    - The 08:51 frame, a wide shot after a cut, was read as stirring with a spoon. So only 08:38 and 08:45 counted.
    - The answer does hedge: "confirmed" whisking, and "the exact start and stop aren't clear".
  - **Why it could not correct itself:** the contact sheet and the three parallel sequences used all 4 looks. One sequence went to the 17:14 false lead, which left none for a narrower look at 08:25–08:55.
  - **The transcript search** missed the custard memory. The query packed "how long does he whisk them" into one embedding, and three of its four hits were the sugar corn and the meringue. The outline recovered the custard chapter, so the outline-plus-search pairing paid off here.
- **Latency:** 40.7 s. The first answer text was shown at 37.1 s.
  - **Model time:** about 21 s over 4 model requests (4.1, 4.4, 6.9 and 5.8 s, the last including the writing).
  - **Tool time:** about 19.6 s, almost all of it the contact sheet (9.3 s) and the parallel sequences (10.1 s).
  - **Tokens:** 33.4k input (25.5k cached), 643 output.

### T2: Where there is an example of what image details look like (Fail)

- **Query:** "where in the video we can find an exampe of how image details looks like"
- **Ground truth:**
  - **The slide:** "Image Filtering": original − smoothed = ?. It is up from about 15:40.
  - **The "details" image:** at 17:08 the "?" is replaced by the result, labelled **"details"**: an edge image of the woman in the hat. It stays on screen until 19:27.
  - **The speech:** the TA asks what subtracting the blurred image gives (16:15), then says "this is what I get. I get the edges" (17:09). He explains that the edges keep "the woman, the hat, the actual content of the image" (17:21–17:43), and that "when we subtract the smooth version, we actually get only the sharp changes" (18:18).
  - **The memory:** 9, [16:15–19:30]. Its summary reads "edges as large changes between neighboring pixels … extracting them by subtracting a blurred image".
  - **The word "details":** spoken nowhere in the recitation. It appears only on the slide.
- **Calls:** at 4.0 s, `memories_semantic_search` ("An example illustrating image details or what image details look like") and `get_video_outline` in parallel. There was one round of tools, then the answer.
  - The search returned 2 hits: memory 10, the vertical-derivative example [19:31–23:37], and memory 12, the averaging-filter exercise. Memory 9 was not among them.
  - No visual tools were offered, because the visual index failed.
- **Answer:**
  > Visual analysis isn't available for this video, so I can't confirm what's shown on screen.
  >
  > If you mean an **example explaining image details such as edges**, try **19:31**. The instructor discusses a grayscale-image example and explains horizontal edges, bright and dark lines, and smooth gray regions. [19:31–23:37]
- **Check:**
  - **Grounded.** What it says about 19:31 is true: the next slide shows a brick wall and its vertical derivative, with horizontal edges only.
  - **The location is wrong.** It is an edge example, but not the one labelled "details". The example the question names is at 17:08, 2½ minutes earlier, in the memory just before the one cited.
  - **Saying visual analysis is unavailable was right,** and it then offered the speech-based answer instead of stopping.
- **Why it missed:**
  1. **The key word is only on screen.** The speech says "edges" and "subtract the blur", never "details". The semantic search ranked the derivative memory above memory 9, whose words are a closer match to what "details" means here.
  2. **The screen can't be searched.** `visual_status` is `failed` with `visual_indexing_interrupted`, although the video file is in Blob Storage and its frames extract fine (they were used for the ground truth above). With a ready index, `search_screen_text` for "details" would have found the slide directly.
  3. **It did not scan the chapter.** The outline showed that "Image filters and convolution" (14:29–35:00) "explores blur and edge detection". One `get_chapter_context` call, at 0.02 s, would have listed memory 9's summary, "extracting them by subtracting a blurred image". With only two search hits and no way to look, one more round was cheap.
- **Latency:** 9.4 s over 2 model requests, with the first answer text at 7.2 s. Tokens: 6.8k input (2.4k cached), 233 output.

## 5. Findings

1. **A failed visual index is losing answers.** `75c17869` failed with `visual_indexing_interrupted`, but its video is stored and readable. The interrupted indexing run has to be re-run by hand. Until then, any question that turns on slide text has to rely on the speech saying the same word.
2. **The look budget is spent before precision is.** In T1, three sequences in parallel used the last look. One of them went to 17:14, a false positive that the contact sheet had marked `present: yes` (a whisk standing in a stand-mixer bowl), so there was no look left to narrow the custard session. A "how long" question needs a dense look over one short window, rather than 9 frames over a minute.
3. **The duration answers are only as fine as the frame spacing.** A sequence's frames are its only evidence, so a 6.75 s spacing can't measure a 20 s action to better than about ±7 s. The answer hedged ("confirmed"), but the number it gave was the lower bound, not an estimate.
4. **"Where is X" with few hits should scan the chapter.** When the search returns only 2 hits and the outline names a matching chapter, `get_chapter_context` on that chapter costs one round and 0.02 s (T2). The prompt's "Questions About a Part of the Video" section does this for summary questions, but not for "where" questions.
5. **The outline-plus-search pairing works.** In T1 the transcript search missed the custard memory, and the outline brought it back through its chapter title.

## 6. Recommendations

1. **Re-index `75c17869`** and re-run T2. Separately, make an interrupted visual index retry or resume, instead of staying `failed`.
2. **For "how long" questions,** have the visual section of the prompt ask for a narrow `view_sequence` over the action's own window, and keep one look in reserve to tighten a boundary. A lead that the transcript doesn't support (17:14 fell in no whisking speech) should not get a sequence before the supported ones have been measured.
3. **For "where" questions with weak or few search hits,** have the prompt call `get_chapter_context` on the chapters the outline matches before answering.
4. **When an answer gives a duration from frames,** state the frame spacing as the error ("about 7–20 s"), instead of a single number that is really a lower bound.

## 7. To re-check

- T2 after re-indexing `75c17869`. Expected: `search_screen_text` "details" finds the slide at 17:08.
- T1 after recommendation 2. Expected: about 20 s for the custard and about 70 s for the pumpkin filling, with no look spent at 17:14.
- Each test more than once, to tell a behavior from a run.
