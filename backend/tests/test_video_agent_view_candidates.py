"""Tests for the video agent's view_candidates tool, and the contact-sheet prompt it sends.

The tool is called directly with a real ConversationDeps. The frame source hands back small real
JPEGs, so the sheet is really built; the image analyzer is a stand-in that records what it was
sent. The only read is the chapter outline, from a `FakePool`. What the answer may cite is read
the way the runner reads it: `spans_of` on the result.
"""

import asyncio
import io

import pytest
from PIL import Image

from backend.services.video_frames import JPEG, FrameExtractionError, VideoNotStoredError
from backend.services.video_frames.grid import CELL_GAP, CELL_LONG_SIDE
from backend.tests.fake_postgres import FakePool
from backend.tests.fake_visual_looks import VIDEO_ID, FakeFrameSource, FakeImageAnalyzer, FakeRunContext, look_deps
from backend.video_agent.citations import spans_of
from backend.video_agent.image_analysis import (
    CANDIDATES_ANALYSIS_PROMPT,
    CandidateAnalysis,
    CandidateVerdict,
    candidates_prompt,
)
from backend.video_agent.tools.deps import ConversationDeps
from backend.video_agent.tools.view_candidates import MAX_CANDIDATES, ViewedCandidates, view_candidates
from backend.video_agent.tools.visual_budget_spent import VisualBudgetSpent
from backend.video_agent.visual_budget import MAX_LOOKS, MAX_VISUAL_TOOL_CALLS

CHAPTERS = [
    {"chapter_id": "c0", "chapter_index": 0, "title": "Opening", "summary": "", "start_seconds": 0.0, "end_seconds": 120.0},
    {"chapter_id": "c1", "chapter_index": 1, "title": "The match", "summary": "", "start_seconds": 120.0, "end_seconds": 600.0},
]


def _deps(
    *, frame_source: FakeFrameSource | None = None, analyzer: FakeImageAnalyzer | None = None
) -> ConversationDeps:
    return look_deps(FakePool(rows=CHAPTERS), frame_source=frame_source, analyzer=analyzer)


def _view(deps: ConversationDeps, times: list[float], question: str = "Is there a ball?"):
    return asyncio.run(view_candidates(FakeRunContext(deps), times, question))


# --- the sheet ------------------------------------------------------------------------------


def test_scattered_frames_are_one_sheet_costing_one_call_and_one_look() -> None:
    source = FakeFrameSource()
    analyzer = FakeImageAnalyzer(verdicts=["yes", "no", "unclear"])
    deps = _deps(frame_source=source, analyzer=analyzer)

    result = _view(deps, [300.0, 12.0, 150.5])

    assert isinstance(result, ViewedCandidates)
    assert [
        (f.frame, f.time_seconds, f.timestamp, f.chapter, f.present, f.description) for f in result.frames
    ] == [
        (1, 300.0, "05:00", "The match", "yes", "Cell 1"),
        (2, 12.0, "00:12", "Opening", "no", "Cell 2"),
        (3, 150.5, "02:30", "The match", "unclear", "Cell 3"),
    ]
    assert result.note is None
    assert (deps.visual_budget.tool_calls_used, deps.visual_budget.looks_used) == (1, 1)
    assert result.budget == f"{MAX_VISUAL_TOOL_CALLS - 1} visual tool calls and {MAX_LOOKS - 1} looks left."
    # The frames are extracted in the order given, at the grid's cell size, and the image model
    # gets one JPEG sheet with their times.
    assert source.calls == [{"video_id": VIDEO_ID, "times": [300.0, 12.0, 150.5], "long_side": CELL_LONG_SIDE}]
    [(question, sheet, cell_times)] = analyzer.candidate_calls
    assert question == "Is there a ball?"
    assert Image.open(io.BytesIO(sheet)).format == "JPEG"
    assert cell_times == [300.0, 12.0, 150.5]


def test_six_frames_are_laid_out_three_across_and_two_down() -> None:
    analyzer = FakeImageAnalyzer()

    _view(_deps(analyzer=analyzer), [float(second) for second in range(0, 60, 10)])

    sheet = Image.open(io.BytesIO(analyzer.candidate_calls[0][1]))
    # Each small test frame is 64x36, so three cells across and two down, with a gap between.
    assert sheet.size == (3 * 64 + 2 * CELL_GAP, 2 * 36 + CELL_GAP)


def test_every_frame_shown_is_citable_as_an_instant() -> None:
    result = _view(_deps(), [300.0, 12.0])

    assert spans_of(result) == [(300.0, 300.0), (12.0, 12.0)]


def test_repeated_and_negative_times_are_looked_at_once_from_the_start() -> None:
    source = FakeFrameSource()

    result = _view(_deps(frame_source=source), [-4.0, 0.0, 10.0, 10.0])

    assert source.calls[0]["times"] == [0.0, 10.0]
    assert [frame.frame for frame in result.frames] == [1, 2]


def test_more_than_six_times_are_cut_to_the_first_six_and_says_so() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)

    result = _view(deps, [float(second) for second in range(8)])

    assert MAX_CANDIDATES == 6
    assert source.calls[0]["times"] == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    assert len(result.frames) == 6
    assert result.note == "Only the first 6 times were looked at."
    assert deps.visual_budget.looks_used == 1


# --- verdicts -------------------------------------------------------------------------------


def test_a_frame_the_image_model_gave_no_verdict_for_comes_back_unclear() -> None:
    result = _view(_deps(analyzer=FakeImageAnalyzer(answered=1)), [10.0, 20.0])

    assert [(frame.present, frame.description) for frame in result.frames] == [
        ("yes", "Cell 1"),
        ("unclear", "The image model gave no verdict for this frame."),
    ]
    # Both were shown, so both may be cited.
    assert spans_of(result) == [(10.0, 10.0), (20.0, 20.0)]


def test_extra_verdicts_are_ignored() -> None:
    result = _view(_deps(analyzer=FakeImageAnalyzer(answered=3)), [10.0])

    assert [frame.description for frame in result.frames] == ["Cell 1"]


def test_a_verdict_is_parsed_description_first_and_only_yes_no_or_unclear() -> None:
    parsed = CandidateAnalysis.model_validate(
        {"frames": [{"description": "A ball at a player's feet.", "present": "no"}]}
    )

    assert parsed.frames == [CandidateVerdict(description="A ball at a player's feet.", present="no")]
    assert list(CandidateVerdict.model_json_schema()["properties"]) == ["description", "present"]
    with pytest.raises(ValueError):
        CandidateVerdict(description="A ball.", present="maybe")


# --- calls that spend nothing, failures and the budget --------------------------------------


@pytest.mark.parametrize(
    ("times", "question", "reason"),
    [([], "Is there a ball?", "no times were given"), ([10.0], "  ", "the question is empty")],
)
def test_a_call_that_cannot_look_spends_nothing(times: list[float], question: str, reason: str) -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)

    result = _view(deps, times, question)

    assert reason in result.note
    assert source.calls == []
    assert (deps.visual_budget.tool_calls_used, deps.visual_budget.looks_used) == (0, 0)


@pytest.mark.parametrize(
    "failure",
    [FrameExtractionError("The video has no frame at 900.0 s"), VideoNotStoredError("no stored file")],
)
def test_frames_that_cannot_be_extracted_give_their_look_back(failure: Exception) -> None:
    analyzer = FakeImageAnalyzer()
    deps = _deps(frame_source=FakeFrameSource(failure), analyzer=analyzer)

    result = _view(deps, [900.0, 10.0])

    assert result.frames == []
    assert result.note == f"The frames could not be extracted: {failure}"
    assert (deps.visual_budget.tool_calls_used, deps.visual_budget.looks_used) == (1, 0)
    assert spans_of(result) == []
    assert analyzer.candidate_calls == []


def test_a_failing_image_model_is_a_note_and_its_look_stays_spent() -> None:
    deps = _deps(analyzer=FakeImageAnalyzer(RuntimeError("provider down")))

    result = _view(deps, [10.0, 20.0])

    assert result.frames == []
    assert result.note == "The image model failed to look at the frames."
    assert deps.visual_budget.looks_used == 1
    # Nothing came back about the frames, so nothing may be cited.
    assert spans_of(result) == []


def test_with_no_looks_left_nothing_is_extracted() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)
    for _ in range(MAX_LOOKS):
        deps.visual_budget.take_look()

    result = _view(deps, [10.0])

    assert result.frames == []
    assert result.note == "No looks are left in this answer's budget."
    assert source.calls == []


def test_after_six_visual_calls_view_candidates_does_no_work_and_says_the_budget_is_spent() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)
    for _ in range(MAX_VISUAL_TOOL_CALLS):
        deps.visual_budget.start_tool_call()

    assert isinstance(_view(deps, [10.0]), VisualBudgetSpent)
    assert source.calls == []


# --- the image model's message --------------------------------------------------------------


def test_the_candidates_prompt_lists_every_frame_s_number_and_time_and_says_it_is_not_a_sequence() -> None:
    [text, image] = candidates_prompt("Is there a ball?", b"sheet", [300.0, 12.0])

    assert text.splitlines() == [
        "Question: Is there a ball?",
        "The image is a contact sheet of 2 frames from different moments of the video, not a "
        "sequence, read left to right, then top to bottom: Frame 1 at 05:00, Frame 2 at 00:12.",
    ]
    assert (image.data, image.media_type) == (b"sheet", JPEG)


def test_the_candidates_instructions_ask_for_the_description_first_and_unclear_when_too_small() -> None:
    assert "unrelated moments from different parts of the video, not a sequence" in CANDIDATES_ANALYSIS_PROMPT
    assert "first write its description" in CANDIDATES_ANALYSIS_PROMPT
    assert "Use unclear when the cell is too small, too dark" in CANDIDATES_ANALYSIS_PROMPT
