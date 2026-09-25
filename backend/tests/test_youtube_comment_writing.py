"""Tests for how the YouTube pipeline fetches comments, and what a failed fetch leaves behind."""

from pathlib import Path
from unittest.mock import patch

from backend.services.video_download.youtube import pipeline


def test_up_to_three_pages_of_top_comments_are_asked_for(tmp_path: Path) -> None:
    with patch.object(pipeline, "fetch_top_comments", return_value=[]) as fetch:
        pipeline._write_comments("abc", tmp_path, pipeline.DEFAULT_COMMENT_LIMIT)

    fetch.assert_called_once_with("abc", limit=300, max_pages=3)


def test_a_failed_fetch_is_none_so_a_rescan_keeps_the_stored_comments(tmp_path: Path) -> None:
    """An empty list would be written as "no comments" and clear the ones already stored."""
    with patch.object(pipeline, "fetch_top_comments", side_effect=RuntimeError("quota")):
        comments, comments_path = pipeline._write_comments("abc", tmp_path, 300)

    assert comments is None
    assert comments_path is None


def test_a_fetch_that_found_nothing_is_an_empty_list(tmp_path: Path) -> None:
    with patch.object(pipeline, "fetch_top_comments", return_value=[]):
        comments, _ = pipeline._write_comments("abc", tmp_path, 300)

    assert comments == []
