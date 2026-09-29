"""Tests for the visual budget one answer spends: six visual tool calls, four looks."""

from backend.video_agent.tools.deps import ConversationDeps
from backend.video_agent.visual_budget import MAX_LOOKS, MAX_VISUAL_TOOL_CALLS, VisualBudget


def test_the_budget_is_six_visual_tool_calls_and_four_looks() -> None:
    assert (MAX_VISUAL_TOOL_CALLS, MAX_LOOKS) == (6, 4)


def test_tool_calls_stop_being_granted_after_the_sixth() -> None:
    budget = VisualBudget()

    granted = [budget.start_tool_call() for _ in range(8)]

    assert granted == [True] * 6 + [False, False]
    # A refused call spends nothing.
    assert budget.tool_calls_used == 6


def test_looks_stop_being_granted_after_the_fourth() -> None:
    budget = VisualBudget()

    granted = [budget.take_look() for _ in range(5)]

    assert granted == [True] * 4 + [False]
    assert budget.looks_used == 4


def test_a_look_given_back_can_be_taken_again_and_looks_never_go_below_zero() -> None:
    budget = VisualBudget()
    for _ in range(MAX_LOOKS):
        budget.take_look()

    budget.return_look()
    assert budget.take_look() is True

    budget = VisualBudget()
    budget.return_look()
    assert budget.looks_used == 0


def test_what_is_left_is_told_in_visual_calls_and_looks() -> None:
    budget = VisualBudget()
    budget.start_tool_call()
    budget.take_look()

    assert budget.remaining() == "5 visual tool calls and 3 looks left."


def test_one_of_each_left_is_told_in_the_singular() -> None:
    budget = VisualBudget()
    for _ in range(MAX_VISUAL_TOOL_CALLS - 1):
        budget.start_tool_call()
    for _ in range(MAX_LOOKS - 1):
        budget.take_look()

    assert budget.remaining() == "1 visual tool call and 1 look left."


def test_the_last_visual_tool_call_says_it_was_the_last() -> None:
    budget = VisualBudget()
    for _ in range(MAX_VISUAL_TOOL_CALLS):
        budget.start_tool_call()
    budget.take_look()

    remaining = budget.remaining()

    assert remaining.startswith("That was your last visual tool call (3 looks unused).")
    assert "Answer now" in remaining


def test_each_run_gets_a_fresh_budget() -> None:
    first, second = ConversationDeps(video_id="video"), ConversationDeps(video_id="video")

    first.visual_budget.start_tool_call()

    assert second.visual_budget.tool_calls_used == 0
