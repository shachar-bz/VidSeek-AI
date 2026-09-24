"""Tests for the visual sub-agent's budget, the check its findings pass, and the prompt it is given."""

import pytest
from pydantic_ai import ModelRetry

from backend.visual_agent import runner
from backend.visual_agent.budget import MAX_IMAGES, MAX_TOOL_CALLS, InvestigationBudget
from backend.visual_agent.result import (
    SLACK_SECONDS,
    VisualFinding,
    VisualInvestigation,
    unsupported_findings,
)
from backend.visual_agent.tools.deps import VisualDeps

VIDEO_ID = "11111111-2222-3333-4444-555555555555"


class FakeRunContext:
    """The three attributes the findings check reads off a RunContext."""

    def __init__(self, deps: VisualDeps, *, retry: int, max_retries: int):
        self.deps = deps
        self.retry = retry
        self.max_retries = max_retries


def _finding(start: float, end: float, observation: str = "A slide titled Kafka.") -> VisualFinding:
    return VisualFinding(
        start_seconds=start, end_seconds=end, observation=observation, evidence="image"
    )


# --- the budget -------------------------------------------------------------------------


def test_the_budget_is_eight_tool_calls_and_six_images() -> None:
    assert (MAX_TOOL_CALLS, MAX_IMAGES) == (8, 6)


def test_tool_calls_stop_being_granted_after_the_eighth() -> None:
    budget = InvestigationBudget()

    granted = [budget.start_tool_call() for _ in range(10)]

    assert granted == [True] * 8 + [False, False]
    # A refused call spends nothing.
    assert budget.tool_calls_used == 8


def test_images_are_granted_partially_when_fewer_are_left_then_not_at_all() -> None:
    budget = InvestigationBudget()

    assert budget.take_images(4) == 4
    assert budget.take_images(4) == 2
    assert budget.take_images(1) == 0
    assert budget.images_used == MAX_IMAGES


def test_asking_for_no_images_or_a_negative_number_spends_none() -> None:
    budget = InvestigationBudget()

    assert budget.take_images(0) == 0
    assert budget.take_images(-3) == 0
    assert budget.images_used == 0


def test_images_given_back_can_be_granted_again_and_never_go_below_zero() -> None:
    budget = InvestigationBudget()
    budget.take_images(MAX_IMAGES)

    budget.return_images(3)
    assert budget.take_images(4) == 3

    budget.return_images(100)
    assert budget.images_used == 0


def test_what_is_left_is_told_in_calls_and_images() -> None:
    budget = InvestigationBudget()
    budget.start_tool_call()
    budget.take_images(2)

    assert budget.remaining() == "7 tool calls and 4 images left."


def test_the_last_tool_call_says_it_was_the_last() -> None:
    budget = InvestigationBudget()
    for _ in range(MAX_TOOL_CALLS):
        budget.start_tool_call()
    budget.take_images(1)

    remaining = budget.remaining()

    assert remaining.startswith("That was your last tool call (5 images unused).")
    assert "Answer now" in remaining


# --- the findings check -----------------------------------------------------------------


def test_a_finding_whose_ends_fall_inside_returned_spans_is_supported() -> None:
    spans = [(100.0, 100.0), (200.0, 230.0)]

    assert unsupported_findings([_finding(100.0, 100.0), _finding(205.0, 230.0)], spans) == []


def test_a_finding_from_one_returned_span_to_another_far_away_is_unsupported() -> None:
    finding = _finding(100.0, 210.0)

    assert unsupported_findings([finding], [(100.0, 100.0), (200.0, 230.0)]) == [finding]


def test_a_finding_may_run_across_spans_that_touch() -> None:
    spans = [(128.0, 133.5), (133.5, 140.0), (140.8, 150.0)]

    assert unsupported_findings([_finding(128.0, 150.0)], spans) == []


def test_spans_further_apart_than_the_slack_do_not_join() -> None:
    finding = _finding(10.0, 20.0)

    assert unsupported_findings([finding], [(10.0, 10.0), (11.5, 11.5), (20.0, 20.0)]) == [finding]


def test_ends_a_second_either_side_of_a_span_are_accepted() -> None:
    spans = [(734.6, 740.0)]

    assert SLACK_SECONDS == 1.0
    assert unsupported_findings([_finding(733.6, 741.0)], spans) == []


def test_an_end_past_the_slack_is_unsupported() -> None:
    spans = [(734.6, 740.0)]
    early = _finding(733.5, 740.0)
    late = _finding(735.0, 741.1)

    assert unsupported_findings([early, late], spans) == [early, late]


def test_a_finding_whose_end_lies_outside_every_span_is_unsupported() -> None:
    spans = [(100.0, 110.0)]
    supported = _finding(100.0, 110.0)
    runs_on = _finding(105.0, 160.0)

    assert unsupported_findings([supported, runs_on], spans) == [runs_on]


def test_a_finding_that_ends_before_it_starts_is_unsupported() -> None:
    backwards = _finding(110.0, 100.0)

    assert unsupported_findings([backwards], [(90.0, 120.0)]) == [backwards]


def test_a_single_frame_finding_at_the_frame_s_own_time_is_supported() -> None:
    assert unsupported_findings([_finding(42.5, 42.5)], [(42.5, 42.5)]) == []


def test_no_span_returned_means_no_finding_is_supported() -> None:
    finding = _finding(0.0, 0.0)

    assert unsupported_findings([finding], []) == [finding]


# --- verify_findings --------------------------------------------------------------------


def test_an_answer_whose_findings_are_all_supported_is_returned_as_it_is() -> None:
    deps = VisualDeps(video_id=VIDEO_ID)
    deps.spans = [(42.0, 42.0)]
    output = VisualInvestigation(answer="A slide.", findings=[_finding(42.0, 42.0)])

    assert runner.verify_findings(FakeRunContext(deps, retry=0, max_retries=1), output) is output


def test_an_unsupported_finding_sends_the_answer_back_while_a_retry_is_left() -> None:
    deps = VisualDeps(video_id=VIDEO_ID)
    deps.spans = [(42.0, 42.0)]
    output = VisualInvestigation(
        answer="A slide.", findings=[_finding(42.0, 42.0), _finding(600.0, 605.0)]
    )

    with pytest.raises(ModelRetry) as raised:
        runner.verify_findings(FakeRunContext(deps, retry=0, max_retries=1), output)

    # Names only the unsupported finding's times, written the way the tools write them.
    assert "10:00-10:05" in str(raised.value)
    assert "00:42" not in str(raised.value)


def test_on_the_last_try_only_the_unsupported_findings_are_dropped() -> None:
    deps = VisualDeps(video_id=VIDEO_ID)
    deps.spans = [(42.0, 42.0)]
    kept = _finding(42.0, 42.0, "The slide says Kafka.")
    invented = _finding(600.0, 605.0, "A diagram nobody looked at.")
    output = VisualInvestigation(answer="The slide says Kafka.", findings=[kept, invented])

    checked = runner.verify_findings(FakeRunContext(deps, retry=1, max_retries=1), output)

    assert checked.answer == "The slide says Kafka."
    assert checked.findings == [kept]
    # The model's own answer object is left untouched.
    assert output.findings == [kept, invented]


# --- the investigation prompt -----------------------------------------------------------


def test_the_prompt_gives_the_question_and_the_viewer_s_position_as_mm_ss() -> None:
    prompt = runner.investigation_prompt(
        "What is on the slide?", current_time_seconds=754.3, start_seconds=None, end_seconds=None
    )

    assert prompt.splitlines()[0] == "Question: What is on the slide?"
    assert "12:34" in prompt
    assert "754.3 seconds" in prompt
    assert "No part of the video was named" in prompt


def test_a_paused_player_is_the_very_frame_and_a_playing_one_may_be_a_little_late() -> None:
    paused = runner.investigation_prompt(
        "What is this?", current_time_seconds=754.3, start_seconds=None, end_seconds=None, player_paused=True
    )
    playing = runner.investigation_prompt(
        "What is this?", current_time_seconds=754.3, start_seconds=None, end_seconds=None, player_paused=False
    )
    unsaid = runner.investigation_prompt(
        "What is this?", current_time_seconds=754.3, start_seconds=None, end_seconds=None
    )

    assert "paused at 12:34 (754.3 seconds)" in paused and "very frame" in paused
    assert "playing, at 12:34 (754.3 seconds)" in playing and "a few seconds earlier" in playing
    assert "was at 12:34 (754.3 seconds)" in unsaid
    assert "paused" not in unsaid and "playing" not in unsaid


def test_the_main_agent_s_context_is_given_as_hints_and_cut_when_too_long() -> None:
    with_context = runner.investigation_prompt(
        "Where is it drawn?",
        current_time_seconds=None,
        start_seconds=None,
        end_seconds=None,
        context="  'It' is the consumer group diagram; groups are discussed at 04:10.  ",
    )
    too_long = runner.investigation_prompt(
        "q", current_time_seconds=None, start_seconds=None, end_seconds=None, context="x" * 5000
    )
    blank = runner.investigation_prompt(
        "q", current_time_seconds=None, start_seconds=None, end_seconds=None, context="   "
    )

    assert "never as proof of what is shown" in with_context
    assert with_context.endswith("'It' is the consumer group diagram; groups are discussed at 04:10.")
    assert too_long.endswith("x" * runner.MAX_CONTEXT_CHARACTERS + " [cut]")
    assert "main agent" not in blank


def test_the_prompt_says_when_the_viewer_s_position_is_unknown() -> None:
    prompt = runner.investigation_prompt(
        "What is this?", current_time_seconds=None, start_seconds=None, end_seconds=None
    )

    assert "position in the video is not known" in prompt


def test_the_prompt_names_a_closed_range_both_ways_the_tools_speak_it() -> None:
    prompt = runner.investigation_prompt(
        "What is drawn?", current_time_seconds=None, start_seconds=60.0, end_seconds=125.5
    )

    assert "from 01:00 (60.0 s) to 02:05 (125.5 s)" in prompt


def test_the_prompt_describes_a_range_open_at_either_end() -> None:
    from_start = runner.investigation_prompt(
        "q", current_time_seconds=None, start_seconds=None, end_seconds=90.0
    )
    to_end = runner.investigation_prompt(
        "q", current_time_seconds=None, start_seconds=3725.0, end_seconds=None
    )

    assert "from the start to 01:30 (90.0 s)" in from_start
    assert "from 1:02:05 (3725.0 s) to the end" in to_end
