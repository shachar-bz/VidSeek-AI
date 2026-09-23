"""Tests for turning a browser tab title into the title of the video on that tab."""

import pytest

from backend.core.page_titles import clean_page_title

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
