# Visual investigation redesign

Show the same progress line in both chats while an answer is being generated. Then merge the
visual sub-agent into the main video agent, reshape its tools, and give the one agent a clear
way of investigating visual questions. The goal is lower latency, with no loss of grounding.

## Why

A visual question today runs about 5–8 slow reasoning calls one after another:

1. The main agent decides to call `investigate_visual`.
2. The sub-agent's planner decides to search.
3. The planner reads the results and asks for a look, which is an image-model call.
4. Often one more planner round for a close-up, which is another image-model call.
5. The planner writes a structured answer, plus a retry if the findings check rejects it.
6. The main agent rewrites that answer, plus a retry if the citation check rejects it.

The split costs at least two extra reasoning calls per visual question: the planner's first
decision and its write-up. It also loses information at the handoff, because the free-text
`context` is the sub-agent's only view of the conversation. And it decides the question type
twice.

The split between main agent and sub-agent keeps the main agent's history small, but that
benefit is mostly an illusion. `_model_history` rebuilds history from visible messages only, so
tool outputs never outlive a turn in either design.

The split worth keeping is the image model: it looks at contact sheets and sequences and
answers in text. The close-up is the one exception, where the agent looks at the frames itself.

## Decisions

| Topic | Decision |
|---|---|
| Architecture | One agent. The visual tools move into `video_agent`; `backend/visual_agent/` is deleted. |
| Routing | The main agent decides from rules in its prompt. No classifier call. |
| Memory across turns | Unchanged: only the written answer carries over. No saved visual notes. |
| Reasoning effort | Defaults everywhere, for the main agent and the image model. |
| Live OCR | Removed. `read_frame_text` is deleted. |
| Budget per turn | 6 visual tool calls and 4 looks. A look is one `view_candidates`, `view_sequence` or `view_frames_closeup` call. Transcript tools are free. |
| Instructions | A tool's docstring says what it does and costs. The prompt's visual section says when to use it. |
| Streaming | Not done. The answer still arrives whole, after its citations are checked, and the citation retry stays. |
| Progress while waiting | Tool labels only, no reasoning summary. Done first (stage 0). One generic label per tool, written by the server and sent with each tool call. Both chats show them the same way. They disappear when the answer arrives and are not saved. |
| Eval set and timing | Out of scope. Judged by trying it in the app (see Manual check). |
| Old code | Deleted. Git history keeps it. |

## The agent's tools after the change

Transcript tools, unchanged: `get_video_info`, `get_video_outline`, `memories_semantic_search`,
`get_chapter_context`, `get_memory_context`, and `get_viewer_comments` where the video has
comments.

Visual tools:

| Tool | What it does | Who sees the pixels | Budget |
|---|---|---|---|
| `search_visual_moments(query)` | Frames whose picture matches a description (SigLIP). The z-score gate is kept. At most one frame per shot, up to 6. When nothing stands out, it returns the 3 highest-scoring frames marked `weak`. No text in the results. | Nobody (embeddings) | 1 call |
| `search_screen_text(query, words=None)` | On-screen text: up to 5 matches by meaning of the OCR text (e5), plus up to 5 by exact `words`, each with a short OCR snippet. | Nobody (stored OCR) | 1 call |
| `view_candidates(times, question)` **new** | Up to 6 scattered frames on one contact sheet. Per frame: `present` (yes/no/unclear) and a 1–3 line description. | Image model | 1 call, 1 look |
| `view_sequence(start, end, question)` | Frames spread across one window, usually a whole shot. The image model reports frame by frame and describes what changes. Unchanged, except that it counts as a look. | Image model | 1 call, 1 look |
| `view_frames_closeup(times)` **changed** | 1–3 frames at 1024px, **returned as images to the agent itself**. | The agent | 1 call, 1 look |

## The investigation logic (goes in the prompt)

This is the substance of the prompt's visual section. The draft wording is at the end.

1. **Route.** Questions about what was said, and general questions, use transcript tools
   only. Go visual only when the user asks about the picture or points at the screen.
2. **Pointing questions** ("what is this?") with the viewer's position known don't search.
   - Paused: `view_frames_closeup` at that time.
   - Playing, or player state unknown: `view_sequence` over the last ~5 s, with 3–4 frames.
   - No position, and nothing in the conversation says what "this" is: say it isn't known
     which moment is meant.
3. **Text on screen** ("what does the slide say", "where does the lecturer write the formula
   for X"):
   - Round 1, in parallel: `search_screen_text` and `memories_semantic_search` on the topic.
     A lecturer often talks about what they write, so the transcript points to where it's
     discussed. Running both at once adds no wait. The OCR search still covers the whole
     video, because the text may be written before or after it's discussed, or never said
     aloud.
   - An OCR hit's snippet answers the question → answer and cite it.
     - Several OCR hits → prefer the one whose time matches where the transcript discusses
       it.
     - A screen starts exactly when new text appears, so for "when is it written" the hit's
       start is the answer. Run a sequence only when the question is about the act of
       writing.
   - The snippet is cut, or the question needs a diagram's meaning → `view_frames_closeup`.
   - OCR finds nothing (it may have misread handwriting or math) → the transcript times from
     round 1 become the look candidates: a contact sheet, or a close-up when there is only
     one. Then step 4 if they fail.
4. **Where / when / what happens** (a scene, an object, an action):
   - Round 1, in parallel: `search_visual_moments` with a plain description, and
     `memories_semantic_search` on the topic.
   - Round 2: `view_candidates` on the picture hits plus the top 1–2 transcript times, 6 at
     most. Ask the question one frame can answer: "is there a ball?", not "is the ball in the
     air?".
   - Read the verdict **and** the description together. The verdict is a signal, not the
     decision:
     - A clear "yes" that already answers the question → answer.
     - A "yes" that needs more → `view_sequence` over that shot for an action, an order of
       events, or where in the shot it happens; `view_frames_closeup` for a small detail.
     - "No" or "unclear" → don't drop the frame by default. Judge from the description
       whether the shot could still lead to the answer. For example: "a ball at a player's
       feet" for "when is the ball in the air?" is worth a sequence over that shot.
   - For a sequence over a long shot (over ~60 s), one narrower second pass is allowed.
5. **Picture search found nothing that stands out** (the result says so and lists 3 `weak`
   frames):
   - Search once more with a different description. This costs a call but no look.
   - Still nothing: `view_candidates` on the weak frames plus the transcript times.
   - None fits → answer that it wasn't found, saying what was searched and why it may still
     be there. Never say it isn't in the video.
6. **Visual index not ready:** the search tools aren't offered. Look with `view_sequence`
   across the range the user named, or around the viewer's position, and say the video was
   only sampled.

Standing rules:

- **Speech proposes, a look confirms.** The transcript can suggest candidate moments, but
  never confirms what's on screen. For example, a talk about a war may play over pictures of
  something else.
- **Seen means cited.** A picture-search hit can't be cited until one of the look tools has
  shown it: the contact sheet, a sequence, or a close-up. This is enforced by field names
  (see "Citations").
- **Searches are accurate to about 2 seconds.** Something on screen for under 2 seconds can be
  missed.
- **Every look costs time.** Answer as soon as what you have answers the question.

## Implementation, in four stages (0–3)

Each stage leaves the test suite green.

- Stage 0 (progress line) stands on its own and applies to every answer, not only visual ones.
- Stages 1 and 2 add new code beside the old sub-agent without switching anything on.
- Stage 3 switches over and deletes the old code.

### Stage 0: the same progress line in both chats

**Done** (commits `852b8e7`, `bd184b7`, `5c75a4e`). Everything below landed as written:

- `ToolStarted.activity` reads the label from `video_agent/activity.py`.
- `ToolCallTrace.activity` is streamed, and `_finalize` saves the trace without it.
- The extension's `TOOL_ACTIVITY` table is gone.
- The website shows the extension's typing indicator and activity line.
- Tests: `test_conversation_routes.py`, `conversation-stream.test.tsx`, and a new
  `chrome-extension/tests/chat-activity.test.ts`.

Two decisions the plan didn't cover:

- `get_viewer_comments` gets the label "Reading viewer comments". The extension's old table
  had none for it, so it showed "Thinking…".
- On the website, an empty answer that is no longer being generated (stopped or failed
  before any text) reads "No answer was saved for this question.", as in the extension. It
  used to still say "Waiting for an answer…".

The manual check below has not been done yet.

**Where things stood.** The answer isn't streamed, and that stays. `video_agent/runner.py`
holds the text until `_verify_citations` passes and sends it once, so the citation retry can
rewrite a bad answer without the user seeing text replaced. What the user sees while waiting
differs between the two chats:

- The **extension** shows a typing indicator and, under it, an activity line such as
  "Searching the video…". The labels come from its own `TOOL_ACTIVITY` table
  (`chrome-extension/src/chat.ts`).
- The **website** shows only "Waiting for an answer…" and never says which tool is running.

**Backend: the stream contract**
- `ToolCallTrace` gains `activity: str | None`: a short generic label per tool, such as
  "Searching the video" or "Reading a chapter". The label table lives beside the tools, in
  `video_agent/activity.py`, and `ToolStarted` fills the label from it.
- It is only for display while waiting, so **it is not saved**. `_finalize` in
  `backend/api/routes/conversations.py` dumps the trace without `activity`, so a reopened
  conversation carries no labels.
- Stage 0 labels cover today's tools, including `investigate_visual`: "Looking at what the
  video shows". Stage 3 swaps in the new visual tools' labels.

**Both clients behave the same while an answer is being generated**
1. The pending answer shows the typing indicator.
2. Under it, an activity line shows the label of the tool call still running, or of the last
   one, followed by `…`. It says "Thinking…" when there is no call yet, or when a call carries
   no label.
3. When `message_complete`, `stopped` or `error` arrives, the activity line disappears and
   the answer appears whole. Nothing of the activity is kept.

**Extension (`chrome-extension/src/chat.ts`)**
- Delete the `TOOL_ACTIVITY` table. `latestActivity` reads `call.activity`.
- Add `activity` to `ToolCallTrace` in `chrome-extension/src/types.ts`.

**Website (`frontend/src/pages/video/ConversationWorkspace.tsx`)**
- Replace the "Waiting for an answer…" placeholder with the same typing indicator and activity
  line the extension shows, using the same wording and the same `…`.
- Add `activity` to `ToolCallTrace` in `frontend/src/api/types.ts`.

**Tests**
- Backend: a streamed tool call carries its `activity`; the saved trace does not.
- Website: `conversation-stream.test.tsx` covers the activity line, the "Thinking…" fallback,
  and the line disappearing at the end.
- Extension: the same cases in a chat render test.

**Manual check.** Ask the same question in the website and the extension. Both should show the
same activity lines in the same order, and both should end with the same answer.

### Stage 1: search

**Done** (commit `cfdad5d`). Everything below landed as written, except where the decisions that
follow change it.

Decisions the plan didn't cover, or that changed it:

- **No time window.** `TimeWindow` and the `start_seconds`/`end_seconds` parameters are gone
  from the search service. Every search, the weak fallback included, covers the whole video.
- **The screen-text lists are not merged.** Exact-word hits come first (up to 5), then meaning
  hits (up to 5). A segment both lists found appears once in each, and each hit's `found_by`
  names one list. This replaces "merged into one ... and ranked first" below.
- "Shot" is a visual segment. `shot_start_seconds`/`shot_end_seconds` are its bounds.
- `score` is the frame's z-score against the whole video, rounded to 2 decimals.
- The weak frames are the highest raw similarity, one per segment.
- `timestamp` is `MM:SS-MM:SS` for a screen-text hit and `MM:SS` for a picture hit.
- The wrappers spend no budget yet. That comes with `VisualBudget` in stage 2.
- The note both wrappers give for an index that can't be searched lives in
  `video_agent/tools/visual_index_notes.py`.
- The old sub-agent was not designed around, only kept working until stage 3 deletes it. Its
  search wrappers lost their window and transcript, weak frames are hidden from it, and a few
  prompt lines that told it to pass a window were cut. `search_visual_text` (words only) stays
  in the service for its words tool.

**`services/visual_search/moment_search.py`**
- Remove the `text_meaning` list, and the joining of lists, from `search_visual_moments`. The
  function becomes picture only.
- Keep the z-score gate (`standout_frames`, including the present-level rule).
- Carry each range's best frame out of `HitRange.peak_time_seconds`. `FoundMoment` and
  `VisualMoment` need a field for it.
- Return at most one moment per shot (segment), the best peak first, up to 6.
- When no frame stands out, return the 3 highest-scoring frames from different shots, marked
  `weak`, plus a flag saying nothing stood out.

**`services/visual_search/text_search.py`**
- Add `search_screen_text(video_id, query, words=None, ...)`. It runs the meaning list moved
  out of `moment_search.py` (up to 5) and, when `words` is given, the exact-word match (up to
  5).
- A moment found both ways is merged into one, with both listed in `found_by`, and ranked
  first.

**`moments.fill_moments`**
- Picture results carry no transcript and no OCR text.
- Screen-text results carry the OCR snippet (400 characters) and no transcript.
- Drop `TRANSCRIPT_CHARACTERS` and the transcript read from the search path.

**New tool modules** (not yet registered), one directory each per ARCHITECTURE.md:
- **`video_agent/tools/search_visual_moments/`**. Result fields per frame: `frame_seconds`,
  `timestamp`, `shot_start_seconds`, `shot_end_seconds`, `chapter`, `score`, `weak`.
  - These deliberately **don't** use `start_seconds`/`end_seconds`, so the citation check
    doesn't treat an unseen frame as citable.
  - Also a `note` saying nothing stood out, or that the index isn't ready.
- **`video_agent/tools/search_screen_text/`**. Per moment: `start_seconds`, `end_seconds`
  (citable: the text was read there), `timestamp`, `chapter`, `found_by`, `matched_words`,
  `on_screen_text`, `shot_boundary`, plus the note that OCR is still pending.

**Tests.** Update `test_visual_search.py` for the picture-only search, the weak fallback,
one-per-shot, and the merged screen-text search. Add tests for both tool wrappers, including
the check that picture hits carry no citable pair.

### Stage 2: looks

**Done** (commit `0e8d6a9`). Everything below landed as written, except where the decisions that
follow change it.

Decisions the plan didn't cover, or that changed it:

- **Copied, not moved.** `visual_agent/` may not import `video_agent/` (ARCHITECTURE.md), so the
  budget, `image_analysis.py` and `view_sequence` are adapted copies. `visual_agent/` and its
  tests are untouched and still work; stage 3 deletes them.
- **`view_sequence` result fields renamed**, so the citation walk collects exactly "first to last
  frame of each scene". The window is `first_frame_seconds`/`last_frame_seconds`, a scene's index
  bounds are `scene_start_seconds`/`scene_end_seconds`, and each scene's
  `start_seconds`/`end_seconds` are its first and last frame. Frames whose scene isn't known form
  one entry with `scene: None`, citable from first to last.
- **Citability comes only from result fields.** No tool records spans itself any more: the
  runner's walk over `start_seconds`/`end_seconds` is the one mechanism.
- **The visual deps are on `ConversationDeps` already**: `visual_budget`, `frame_source`,
  `image_analyzer`, `video_map()` and `chapter_at()`, since the look tools need them to be
  tested. Stage 3 adds only `visual_index_ready`.
- **The search wrappers spend a call now**, and every visual result carries a `budget` line
  ("5 visual tool calls and 3 looks left."). A call that can't run (empty query, no times)
  spends nothing. A look tool with no look left still spends its call, as before.
- **No hard stop.** The old sub-agent's `UsageLimits` wasn't carried over; the cap is soft only.
- The image model's two prompts live in `video_agent/image_analysis.py`.
- `view_candidates` keeps the order the times were given (best hit first), not time order.
  Cells are labelled with their times, as in a sequence grid.
- **No live `gpt-6.1-sol` test**, by choice. A runner test with `FunctionModel` checks that the
  close-up images reach the model and that `draft.spans` gets the frame times.
- New tests: `test_video_agent_visual_budget.py`, `test_video_agent_view_sequence.py`,
  `test_video_agent_view_candidates.py`, `test_video_agent_view_frames_closeup.py`, with shared
  fakes in `tests/fake_visual_looks.py`.

**Budget.** Move `InvestigationBudget` into `video_agent/visual_budget.py` as `VisualBudget`:
6 calls and 4 looks, one per turn, held on `ConversationDeps`. The soft "budget spent" message
stays, and it doesn't count transcript tools.

**`video_agent/image_analysis.py`** (moved from `visual_agent/`)
- Keep `analyze_sequence` and `SEQUENCE_ANALYSIS_PROMPT`.
- Remove `analyze` and `IMAGE_ANALYSIS_PROMPT`: the close-up no longer uses the image model.
- Add `analyze_candidates(question, grid_jpeg, cells)`, returning a `CandidateVerdict` for
  each cell with:
  - `description`: 1–3 lines of what is visible that bears on the question, written first;
  - `present`: `yes`, `no` or `unclear`.

  Its prompt should:
  - say the frames are unrelated moments from different parts of the video, not a sequence;
  - ask for the description before the verdict;
  - say to use `unclear` when a cell is too small or too dark to tell.

**`video_agent/tools/view_candidates/`** (new)
- Takes 1–6 times and a question.
- Extracts each frame at `CELL_LONG_SIDE`, builds one grid with `build_frame_grid`, labeled
  with times, and makes one image-model call.
- Records each frame looked at as an instant span (`start_seconds == end_seconds`), so every
  frame shown is citable.

**`video_agent/tools/view_sequence/`** (moved). Behavior unchanged. It now spends one look.
Its docstring says the default window is the shot the start falls in.

**`video_agent/tools/view_frames_closeup/`** (changed)
- Takes 1–3 times and no question.
- Extracts the frames at 1024px and returns a `ToolReturn`:
  - `return_value`: one entry per frame with `time_seconds`, `start_seconds`, `end_seconds`
    (the same instant) and `chapter`. The runner's citation check gets these through
    `FunctionToolResultEvent`.
  - `content`: each frame after a `Frame N at MM:SS` label, as `BinaryContent`.
- One look per call.
- Test with a real `gpt-6.1-sol` call through the Responses API that the agent receives the
  images. A unit test checks that `draft.spans` gets the frame times.

**Tests.** Move and adapt `test_visual_agent_view_sequence.py` and the close-up and budget
parts of `test_visual_agent_tools.py` / `test_visual_agent_budget_and_findings.py`. Add tests
for `view_candidates`: the grid, the verdict parsing, spans, the budget, and extraction
failures that give the look back.

### Stage 3: switch over

**Done** (commit `a85da8e`). Everything below landed as written, except where the decisions that
follow change it. The manual check below has not been done yet.

Decisions the plan didn't cover, or that changed it:

- **No visual tools until the index is ready.** All five visual tools are hidden, not only
  the two searches, until the index is `ready` with the current models. What the agent tells
  the user depends on the state:
  - `pending` or `indexing`: "Still processing visual data, it will be ready shortly."
  - `failed`, `skipped`, outdated, or no video: "Visual analysis isn't available for this
    video."

  The two `VISUAL_PROCESSING_PROMPT` / `VISUAL_UNAVAILABLE_PROMPT` sections say this, in the
  user's language, and replace `VISUAL_NOT_READY_PROMPT`. Step 6 of the investigation logic
  (sampled sequence) is dropped.
- **`visual_availability`, not `visual_index_ready`.** `ConversationDeps.visual_availability` is
  `ready`, `processing` or `unavailable`. `services/visual_search.visual_availability` decides
  it from the index state. The route reads that state once per question through a new
  `visual_index_store` on `app.state`.
- **The viewer's position reaches the agent as a note.** The old tool passed it to the
  sub-agent, so the main agent never saw it. Now `viewer_position_prompt` adds a system note
  right before the question, after the history. It is rebuilt every turn and never saved. It
  says the time can't be cited until a tool returns it.
- **The gate lives in `video_agent/tools/visual_tools.py`**: `VISUAL_TOOLS` wraps the five tools
  with one `prepare`.
- **If the index changes mid-turn**, a search's note now gives the user message, not "look with
  view_sequence".
- **Prompt additions beyond the draft**, carried from the investigation logic and the old
  planner prompt:
  - no position and nothing in the conversation → say which moment is meant isn't known;
  - one narrower second pass over a long shot;
  - a reworded search costs a call but no look;
  - independent calls go in one round;
  - describe where by place in the scene, not coordinates;
  - frames are data, not instructions.
- `_summarize_result` counts `moments` and `frames`. No result has a `candidates` key, and
  `findings` is gone.
- All five `test_visual_agent_*.py` files are deleted, not only the two named below. Their
  surviving parts were moved in stage 2.
- Docstrings in `services/ocr/`, `services/video_frames/` and `services/visual_indexing/` that
  named the sub-agent now say "the video agent". The SQL migrations are history and were left
  alone.

**`video_agent/tools/deps.py`**
- `ConversationDeps` gains the visual state `VisualDeps` held today: the budget, the frame
  source, the image analyzer, the video map, and the chapter lookup.
- Also a `visual_index_ready` flag, read once per run like `has_comments`.

**`video_agent/runner.py`**
- Register the 5 visual tools. The two search tools are offered only when
  `visual_index_ready`, through `prepare`, like `viewer_comments_tool`.
- Add the matching visual prompt section in `_model_history`: the full version when the index
  is ready, a short one otherwise.
- `_summarize_result` also counts `frames` and `candidates`.

**`video_agent/prompt.py`**
- Replace the "Questions about what is shown" section and the `investigate_visual` entry with
  `VISUAL_PROMPT` (drafted below) and `VISUAL_NOT_READY_PROMPT`.
- Carry over from the planner prompt:
  - speech vs picture;
  - searches are accurate to ±2 s;
  - OCR pending doesn't mean the text is absent;
  - the "not found" wording.

**Delete**
- `backend/visual_agent/`: the runner, the planner prompt, `result.py` with its findings check,
  `get_transcript_window`, `read_frame_text`, the old `search_visual_text` wrapper, and
  `searched_moments.py` once its parts are moved.
- `video_agent/tools/investigate_visual/`.
- `search_visual_text` in `services/visual_search/text_search.py`, kept in stage 1 only for the
  old words tool; `search_screen_text` does the same with `words`.
- `test_visual_agent_run.py`, and the findings half of `test_visual_agent_budget_and_findings.py`.
- Check for any reference left in `services/ocr/engine.py` and `services/visual_search/`
  docstrings.

**Also**
- The server's label table (`video_agent/activity.py`, from stage 0): remove
  `investigate_visual` and add the lines below. Neither client needs to change.
  - `search_visual_moments`: "Searching the picture"
  - `search_screen_text`: "Searching on-screen text"
  - `view_candidates`: "Checking candidate moments"
  - `view_sequence`: "Watching part of the video"
  - `view_frames_closeup`: "Looking closely at a frame"
- `ARCHITECTURE.md`: the `visual_agent/` entries, the import rule on lines 121–125 (there's no
  sub-agent any more), and the note that only the image model sees pixels. The close-up is now
  the exception.
- Update `test_video_agent.py` for the new toolset and prompt sections.

## Citations

The main agent's check collects every `start_seconds`/`end_seconds` pair in any tool result
([citations.py](backend/video_agent/citations.py)). Stage 1 relies on that: only results the
agent may cite use those names.

| Source | Citable? |
|---|---|
| Transcript tools | Yes (speech), as today |
| `search_screen_text` hit | Yes: the text was read there |
| `search_visual_moments` hit | **No**: uses `frame_seconds` / `shot_*` |
| `view_candidates` frame | Yes, each frame shown, as an instant |
| `view_sequence` | Yes, first to last frame of each scene, as today |
| `view_frames_closeup` frame | Yes, as an instant |

One gap is left to the prompt, not the check: citing a transcript time for a claim about what
is *shown* passes the check. The rule "speech proposes, a look confirms" covers it.

## Draft tool descriptions (docstrings: what it does and what it costs)

**search_visual_moments.** Find frames whose picture looks like a description. Costs no look.
Every frame sampled every 2 seconds is compared with the query. Only frames that stand out from
the rest of this video are returned: at most one per shot, up to 6, best first. When nothing
stands out, the note says so and the 3 closest frames come back marked `weak`. A hit means a
frame resembles the query, not that it shows it: look at it before saying what it shows. Its
times cannot be cited until you have. Describe what is visible ("a whiteboard with equations",
"a ball on grass"), not what the user asked ("when is the ball in the air").

**search_screen_text.** Find moments by the text written on screen: slides, boards, signs,
code. Costs no look. `query` finds text that *means* what it describes. `words` finds text
that *contains* those exact strings, ignoring case and spaces; give the spellings it may be
written in. Up to 5 of each, with a snippet of the text read there. OCR can misread
handwriting and math. While OCR is still reading the video, an empty result does not mean the
text isn't on screen.

**view_candidates.** Check up to 6 frames from anywhere in the video at once, on one contact
sheet. Costs one look. For each frame, the image model describes in 1–3 lines what is visible
and says whether the thing in `question` is present: yes, no or unclear. Ask what one frame
can show ("Is there a ball?"), since a single frame cannot show an action. The cells are
small: for fine detail, use `view_frames_closeup`.

**view_sequence.** Look at frames spread across one window, as one grid, and learn what happens
across them. Costs one look. For actions, order, before and after, and where inside a shot
something appears. With no end, the window runs to the end of the shot the start falls in.
Frames from different scenes are marked; a change across a cut is not an action.

**view_frames_closeup.** See 1–3 frames yourself, large. Costs one look. For small text, a
diagram's boxes and arrows, a face, a small object, or the frame the viewer paused on.

## Draft prompt section (`VISUAL_PROMPT`: when to use them)

```
Questions about what is shown
The transcript tools know only what was said. For what is shown, use the visual tools, and
only when the user asked about the picture or points at the screen ("what is this?"). Never
for what was said, and never on your own initiative.

Speech proposes, a look confirms. What was said can suggest where to look, but speech and
picture often part: a talk about a war may play over pictures of something else. Never state
what is shown until a look has shown it.

How to investigate
- Pointing at the screen, with the viewer's position given: no search. Paused: view the frame
  closely. Playing or not known: a sequence over the 5 seconds up to the position.
- Text on screen: in one round, search_screen_text over the whole video and
  memories_semantic_search for where it is discussed; a lecturer often talks about what they
  write. When a snippet answers, answer; among several, prefer the one where it is discussed.
  A screen starts when new text appears, so its start is when the text was written. When the
  snippet is cut or a diagram must be understood, view the frame closely. When the text
  search finds nothing, look at the times where it is discussed; when those fail too, search
  the picture as below.
- Where, when, or what happens: in one round, search_visual_moments with a plain description
  of what is visible, and memories_semantic_search for where it is discussed. Then put the
  picture hits and the best one or two transcript times on one contact sheet.
- Ask the sheet what a single frame can show: "Is there a ball?", not "Is the ball in the
  air?".
- Read each verdict with its description. The verdict is a signal, not the decision. A clear
  yes that answers the question is enough. A yes that needs more: a sequence over its shot
  for an action or order, or a close view for a detail. A no or unclear whose description
  still points toward the answer (a ball at a player's feet, when asked when it is in the air)
  is worth a sequence over its shot.
- When the picture search says nothing stood out: search once more with another description.
  When that fails too, put its weak frames and the transcript times on one sheet. When none
  fits, answer that it was not found.

Budget
Each turn allows 6 visual tool calls and 4 looks (a contact sheet, a sequence or a close view
each count as one). It is a ceiling, not a target: answer as soon as what you have answers
the question.

Not found
Say what you searched and why it may still be there: shown too briefly, OCR still reading,
the searches matching other things. Never say it is not in the video.
```

## Manual check (after stage 3)

Try these by hand on 3–4 videos, and watch for tool order and latency:

1. A question about what was said → no visual tools called.
2. "What is this?" while paused → one close-up, no search.
3. "What does the slide about X say?" → `search_screen_text` answers without a look.
4. "Where does the lecturer write the formula for X?" → screen-text hit, answered with its start.
5. "Where do we see <object>?" → picture and transcript search, one contact sheet, answer.
6. "When is the ball in the air?" → a "no" candidate is followed by a sequence over its shot.
7. Something not in the video → reworded search, weak sheet, honest "not found".
8. A video whose visual index isn't ready → sampled sequence, and the answer says so.

## Risks

- **The main agent carries 10–11 tools and a longer prompt.** Watch for visual tools called on
  questions about what was said.
- **Images from close-ups are in the agent's context for the rest of the turn**, which slows
  its later steps. The 4-look cap limits this.
- **The latency gain is expected, not measured.** It removes about 2–3 serial reasoning
  calls, replaces serial looks with one contact sheet, and removes the image-model round trip
  from close-ups.
- **The weak-frame fallback can produce misleading candidates** (for example the known "dog
  on a padel court" false standout). The look filters them, at the cost of one look.
