"""Tests for the URL normalization that `videos.normalized_source_url` is defined by."""

import pytest

from backend.core.source_urls import normalize_source_url, youtube_video_id

VIDEO_ID = "dQw4w9WgXcQ"
CANONICAL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
        f"https://youtube.com/watch?v={VIDEO_ID}",
        f"http://www.youtube.com/watch?v={VIDEO_ID}",
        f"https://m.youtube.com/watch?v={VIDEO_ID}",
        f"https://music.youtube.com/watch?v={VIDEO_ID}",
        f"https://youtu.be/{VIDEO_ID}",
        f"https://youtu.be/{VIDEO_ID}?t=42",
        f"https://www.youtube.com/shorts/{VIDEO_ID}",
        f"https://www.youtube.com/embed/{VIDEO_ID}",
        f"https://www.youtube.com/live/{VIDEO_ID}",
        f"https://www.youtube-nocookie.com/embed/{VIDEO_ID}",
        f"https://www.youtube.com/watch?v={VIDEO_ID}&list=PL123&index=4",
        f"https://www.youtube.com/watch?v={VIDEO_ID}&utm_source=newsletter&si=abc",
        f"https://www.youtube.com/watch?v={VIDEO_ID}#t=1m",
    ],
)
def test_every_spelling_of_one_youtube_video_normalizes_to_one_url(url: str) -> None:
    # The whole point of the column: these all download the same video, and without this
    # each of them would download, transcribe, segment and embed it again.
    assert normalize_source_url(url) == CANONICAL


def test_two_different_youtube_videos_stay_different() -> None:
    other = normalize_source_url("https://youtu.be/oHg5SJYRHA0")

    assert other != CANONICAL


def test_a_youtube_page_with_no_video_is_normalized_as_an_ordinary_page() -> None:
    # A channel page carries no video id, so there is nothing to canonicalize it to.
    assert (
        normalize_source_url("https://www.youtube.com/@someone/videos")
        == "https://youtube.com/@someone/videos"
    )


def test_a_www_prefix_and_a_default_port_are_dropped() -> None:
    assert normalize_source_url("https://www.example.com:443/talks/1") == "https://example.com/talks/1"


def test_a_non_default_port_is_kept_because_it_selects_a_different_server() -> None:
    assert normalize_source_url("https://example.com:8443/talks/1") == "https://example.com:8443/talks/1"


def test_http_and_https_collapse_because_they_serve_the_same_page() -> None:
    assert normalize_source_url("http://example.com/talks/1") == normalize_source_url(
        "https://example.com/talks/1"
    )


def test_a_trailing_slash_and_a_fragment_are_dropped() -> None:
    assert normalize_source_url("https://example.com/talks/1/#chapter-2") == "https://example.com/talks/1"


def test_query_parameter_order_does_not_change_the_result() -> None:
    assert normalize_source_url("https://example.com/watch?b=2&a=1") == normalize_source_url(
        "https://example.com/watch?a=1&b=2"
    )


def test_tracking_parameters_are_dropped_and_meaningful_ones_are_kept() -> None:
    # `id` is not on the tracking list, and on plenty of sites it is what selects the video.
    assert (
        normalize_source_url("https://example.com/watch?id=99&utm_source=x&fbclid=y&gclid=z")
        == "https://example.com/watch?id=99"
    )


def test_a_repeated_parameter_is_not_collapsed_into_one() -> None:
    # A dictionary would have lost one of these, and some sites read every occurrence.
    assert normalize_source_url("https://example.com/w?tag=a&tag=b") == "https://example.com/w?tag=a&tag=b"


def test_an_unparseable_url_comes_back_as_itself_rather_than_raising() -> None:
    # This keys a row; rejecting a request is `core.security.validate_remote_url`'s job.
    assert normalize_source_url("  not a url  ") == "not a url"
    assert normalize_source_url("magnet:?xt=urn:btih:abc") == "magnet:?xt=urn:btih:abc"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"https://youtu.be/{VIDEO_ID}", VIDEO_ID),
        (f"https://www.youtube.com/watch?v={VIDEO_ID}", VIDEO_ID),
        (f"https://www.youtube.com/shorts/{VIDEO_ID}", VIDEO_ID),
        (f"https://www.youtube.com/embed/{VIDEO_ID}", VIDEO_ID),
        (f"https://www.youtube.com/live/{VIDEO_ID}", VIDEO_ID),
        (f"https://www.youtube.com/v/{VIDEO_ID}", VIDEO_ID),
        ("https://www.youtube.com/@someone", None),
        ("https://www.youtube.com/playlist?list=PL123", None),
    ],
)
def test_the_video_id_is_read_off_every_shape_that_carries_one(url: str, expected: str | None) -> None:
    assert youtube_video_id(url) == expected


def test_normalizing_is_idempotent() -> None:
    # A value written to the column and normalized again must not drift, or a re-run would
    # stop matching the row it wrote.
    once = normalize_source_url("https://WWW.Example.com/Talks/1/?utm_source=x&b=2&a=1#top")

    assert normalize_source_url(once) == once
