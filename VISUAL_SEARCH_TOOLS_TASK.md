# Task: rebuild the visual search services

This file is the brief for the agent that implements the redesigned visual search. The design
was agreed with the user on 2026-09-24 and lives in `VISUAL_UNDERSTANDING_PLAN.md` §5. This file
says what to build, in what order, and what to check. If this file and §5 disagree, §5 wins; ask
the user if it is unclear.

## Before you start

* **Work on this branch, in this worktree:** `feat/visual-search-tools`, at
  `.claude/worktrees/visual-search-tools`. Do not create another branch or worktree (CLAUDE.md,
  rule 3). The branch is based on `refactor/remove-saved-frame-captions`, which is not merged
  into `main` yet.
* Read `CLAUDE.md`, `backend/CLAUDE.md`, `ARCHITECTURE.md`, and `VISUAL_UNDERSTANDING_PLAN.md`
  §3.2 (segments and keyframes), §4 and **§5 in full**.
* Read the current code you are replacing: `backend/services/visual_search/` (all of it),
  `backend/storage/postgres/visual_index.py`, `backend/storage/postgres/transcript_segments.py`,
  and `backend/tests/test_visual_search.py`.

## Scope

**In scope:** the two search **services** in `backend/services/visual_search/`, the storage reads
they need, and their tests.

**Out of scope, do not build:** `backend/visual_agent/`, the Pydantic AI tool wrappers
(`visual_agent/tools/search_visual_moments/`, `.../search_visual_text/`), `investigate_visual`,
and any change to the main agent (`backend/video_agent/`). Those come later, when the visual
sub-agent is built. The services must be callable without an agent.

## What exists today, and what changes

`services/visual_search/search.py` has one `search_visual_moments` that reads four lists (picture,
on-screen text by trigram, on-screen text by e5, transcript by MiniLM) and fuses them per segment
with reciprocal rank fusion (`fusion.py`). The redesign replaces this with **two independent
searches and no fusion**:

| | `search_visual_moments(query, ...)` | `search_visual_text(words, ...)` |
|---|---|---|
| Lists | picture (SigLIP) + on-screen text by meaning (e5) | on-screen text by character sequence |
| Rule | z ≥ 1.5 against the whole video; picture also hits at raw ≥ 0.15; e5 with < 20 texts: top 5, no z | a keyframe matches if any word is found; no score, no threshold |
| Output | up to 10 unique moments (≤ 5 per list) | up to 5 moments |

Keep what still fits: `scoring.py`'s z-score and range merge, `video_map.py`, the index status
checks (`not_ready`, `outdated`) and the query encoders being injectable for tests.

## Build steps

### 1. Storage reads

In `backend/storage/postgres/`:

* **All keyframe texts of a video**, for the character search: `(time_seconds, ocr_text)` for
  every keyframe with `ocr_text is not null`. Matching is done in Python, not SQL (see step 4).
* **Every keyframe text scored by e5**, with no `limit`: the z-score needs the whole
  distribution. `keyframe_text_similarities` currently takes a `limit`; change it or add a read
  without one.
* **Whether OCR is still pending** for a video: keyframes with `ocr_engine is null` (§12 of the
  plan: null engine means unread). Used for §5.6.
* **Transcript by time** in `transcript_segments.py`: the segments of one video that overlap
  `[start, end]`, in order. Today there is only `load` (the whole transcript).

### 2. Scoring (`scoring.py`)

* `standout_frames`: **remove the similarity floor** (`similarity_floor`, 0.08). Keep the z-score
  rule and the present level (0.15). The z threshold becomes **1.5**.
* Add or generalize a z-score helper the e5 list can use too (z ≥ 1.5 against all the video's
  keyframe-text scores). With fewer than **20** keyframes with an e5 vector, skip the z filter
  and take the 5 closest.
* Update the module docstring: it still explains the floor with the "a dog, 0.03" example. The
  reason the floor existed is still true; say it was removed on purpose and the sub-agent's look
  is the acceptance step.

### 3. `search_visual_moments(video_id, query, *, start_seconds=None, end_seconds=None, ...)`

Follow plan §5.1, §5.3, §5.4, §5.5:

1. Refuse an index that is not `ready` or is `outdated`, as today.
2. Picture list: score every frame, keep standouts, merge consecutive hits into ranges, **cut
   ranges at segment boundaries** (use `VideoVisualMap.segments_overlapping`), apply the window
   (drop or clip; z computed against the whole video before the window), rank by peak z, keep 5.
3. Text-by-meaning list: score every keyframe text, keep hits, turn each into the stretch it
   stands for (keyframe to next keyframe of its segment, or segment end; today's
   `_on_screen_range` does this), **merge hits of the same segment** into one moment, apply the
   window, rank by best similarity, keep 5.
4. Join: a picture moment and a text moment are one moment when they share a segment and their
   ranges overlap; the joined moment spans both and has `found_by: [image, text_meaning]`.
   Order: joined moments first, then the rest alternating by rank, picture first. At most 10.
5. Fill each moment (§5.4): segment, chapter (`VideoVisualMap.chapter_at`), `found_by`, the OCR
   text of the keyframe covering it (≤ ~400 characters), the transcript by time (overlapping
   segments; widen to ±5 s when the moment is shorter than 10 s; ≤ ~600 characters), and the
   peak z-score for picture matches.
6. Report OCR still pending (§5.6).

Every moment uses plain `start_seconds`/`end_seconds`.

### 4. `search_visual_text(video_id, words, *, start_seconds=None, end_seconds=None, ...)`

Follow plan §5.2:

* `words`: 1 to 5 strings. Reject 0, more than 5, or a word that is empty once whitespace is
  removed, with a `ValueError`. The tool wrapper will turn that into a message for the model
  later.
* Normalize both sides the same way: **lower-case, and remove every whitespace character**
  (spaces, tabs, newlines). Then a word matches a keyframe when it is a substring of the
  keyframe's normalized OCR text. So "kafka partitions" matches "Kafka" and "Partitions" on two
  lines, "כוס" matches "הכוס", and "cup" matches "cupboard" (accepted, by design).
* A keyframe matches when at least one word is found. Turn matches into moments exactly as the
  text list in step 3 does (stretch, same-segment merge, window).
* Order by the number of **different** words found in the moment, then by time. Return 5. Each
  moment lists its matched words (as the caller wrote them, not normalized) and carries the
  same fields as in step 3 (§5.4), without a z-score.
* Refuse a non-ready or outdated index, and report OCR still pending, as in step 3.

### 5. Shared code

The moment type, the window, the segment-stretch logic and the transcript-by-time filling are
shared by both searches. Put them in one place in `services/visual_search/` rather than
duplicating them. Export both searches from `services/visual_search/__init__.py`.

### 6. Tests

Replace `backend/tests/test_visual_search.py` with tests for the new behaviour, using the
existing `FakePool` pattern and injected encoders. At least:

* z ≥ 1.5 is a hit and below is not; no floor (a low-similarity frame that stands out *is* a
  hit); a frame at ≥ 0.15 is a hit whatever its z-score.
* A picture range crossing a segment boundary becomes two moments.
* e5 with fewer than 20 texts returns the 5 closest with no z filter; with 20 or more, the z
  rule applies.
* Two keyframes of the same segment matching the same list become one moment.
* A moment found by both lists appears once, with both in `found_by`, and comes first; the rest
  alternate picture first; at most 10.
* The window drops and clips moments, while the z-score still uses the whole video.
* Transcript by time: overlapping segments are attached; a short moment is widened to ±5 s; the
  caps hold.
* `search_visual_text`: case and whitespace are ignored on both sides; a Hebrew prefix still
  matches; a misreading does not; ordering by distinct words then time; at most 5; matched words
  are reported; invalid `words` raise `ValueError`.
* Index not ready or outdated returns a status and no moments; OCR pending is reported.

Add storage tests for each new read in `test_postgres_visual_index.py` and the transcript-segment
tests.

## Deletions: approved

The user **approved all five deletions below on 2026-09-24**; do not ask again. Once the new
code works, re-check with Grep that nothing else uses each item. If something unexpected still
uses one, stop and ask the user before deleting that item. Anything else already built that you
want to delete, and that is not in this table, needs the user's approval first.

| # | What | Why it is no longer needed |
|---|---|---|
| 1 | `services/visual_search/fusion.py` (reciprocal rank fusion), its exports and its test | No fusion between lists |
| 2 | `PostgresMemoryEmbeddings.memory_similarities` and `MemorySimilarity` in `storage/postgres/memory_embeddings.py`, their exports and test | The transcript is no longer a search list, only context read by time. On 2026-09-24 only the visual search used them |
| 3 | `PostgresVisualIndex.keyframe_text_word_matches`, `KEYFRAME_TEXT_WORD_MATCHES_SQL`, and its test | Replaced by the character search |
| 4 | The GIN trigram index `video_keyframes_ocr_text_trgm_idx`, dropped by a new migration (`0026_...`; 0025 drops the caption table) | Only the trigram search used it. A video has ~100–300 keyframes, cheap to scan |
| 5 | The `pg_trgm` extension, dropped in the same migration | Nothing uses it once 3 and 4 are gone. Tell the user they can also untick PG_TRGM in the server's `azure.extensions` parameter |

Leave migrations `0023` and `0024` as they are: databases that applied them record them as done.
`backend/tests/test_postgres_migrations.py` has a test about 0023 failing; it stays valid.

## Documentation

* `VISUAL_UNDERSTANDING_PLAN.md`:
  * remove the paragraph under "Status" that says the redesign is still being implemented;
  * rewrite the §12 notes that describe the old code: "OCR columns arrive in 0024, pg_trgm in
    0023" (fusion of two OCR lists, trigram), "OCR runs after the index is `ready`" (trigram
    floor, e5 floor and margin), "Two absolute levels beside the z-score" (the floor is gone),
    "On-screen text by meaning is matched against the best one" (now z-score or top 5), and
    "Fusion is per segment". Keep the measurements; they are still the reason for the numbers.
* `ARCHITECTURE.md`: update only if a directory is added, removed or renamed, or a boundary
  changes.
* Delete this file (`VISUAL_SEARCH_TOOLS_TASK.md`) in the final commit.

## Finishing

* Run the whole backend suite from the worktree root:
  `C:/Shachar/VidSeek-AI/backend/.venv/Scripts/python.exe -m pytest backend/tests -q`
  (check with `python -c "import backend...; print(__file__)"` that it imports the worktree's code).
* Commit in logical steps (storage reads; services and tests; deletions; docs).
* Do not merge. Open the worktree with the `open-worktree` skill and tell the user what was
  built, what was deleted, and anything left open.
