"""Tests for turning a browser tab title into the title of the video on that tab."""

import pytest

from backend.core.page_titles import clean_page_title, display_title

YOUTUBE = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.parametrize(
    ("page_title", "page_url", "expected"),
    [
        ("(3) How Transformers Work - YouTube", YOUTUBE, "How Transformers Work"),
        ("(99+) How Transformers Work - YouTube", YOUTUBE, "How Transformers Work"),
        ("How Transformers Work - YouTube", "https://m.youtube.com/watch?v=x", "How Transformers Work"),
        ("How Transformers Work - YouTube", "https://youtu.be/x", "How Transformers Work"),
        ("Week 1 Introduction | Coursera", "https://www.coursera.org/learn/ml/lecture/x", "Week 1 Introduction"),
        ("Intro to Rust on Vimeo", "https://vimeo.com/1", "Intro to Rust on Vimeo"),
    ],
)
def test_the_tab_decoration_is_removed(page_title: str, page_url: str, expected: str) -> None:
    assert clean_page_title(page_title, page_url) == expected


def test_a_dash_that_is_part_of_the_title_is_kept() -> None:
    title = "Part 1 - The Basics"
    assert clean_page_title(title, YOUTUBE) == title


def test_a_suffix_naming_another_site_is_kept() -> None:
    title = "Lecture 4 - YouTube"
    assert clean_page_title(title, "https://www.coursera.org/learn/x") == title


def test_a_title_that_would_become_empty_is_left_as_it_was() -> None:
    assert clean_page_title("YouTube", YOUTUBE) == "YouTube"


@pytest.mark.parametrize(
    ("page_title", "page_url", "expected"),
    [
        ("video", "https://www.coursera.org/learn/x", "Coursera video, Sep 23, 2026"),
        ("", "https://www.coursera.org/learn/x", "Coursera video, Sep 23, 2026"),
        ("(2) YouTube", YOUTUBE, "YouTube video, Sep 23, 2026"),
        ("Video", "https://drive.google.com/file/d/x", "Google Drive video, Sep 23, 2026"),
    ],
)
def test_a_video_with_no_title_is_labelled_by_platform_and_date(
    page_title: str, page_url: str, expected: str
) -> None:
    assert display_title(page_title, page_url, "2026-09-23T10:00:00+00:00") == expected


def test_the_label_leaves_the_date_off_when_there_is_none() -> None:
    assert display_title("video", "https://vimeo.com/1") == "Vimeo video"
    assert display_title("video", "https://vimeo.com/1", "not a date") == "Vimeo video"


def test_a_real_title_is_shown_cleaned() -> None:
    assert display_title("(3) Recursion - YouTube", YOUTUBE, "2026-09-23T10:00:00Z") == "Recursion"
