"""Tests for the visual searches: what counts as a hit, how hits become moments, and what comes back.

The stores are answered by a `FakePool`, in the order the searches read them -- the index state,
the segments, the chapters, the count of unread keyframes, the keyframe texts, then the frame
scores (`search_visual_moments`) or the keyframe-text scores (`search_screen_text`, for a video
with on-screen text). No search reads the transcript. The query encoders are stood in for, so
each test says exactly what matched and checks what the search made of it.
"""

import pytest

from backend.services.visual_indexing import CURRENT_VISUAL_INDEX_VERSION
from backend.services.visual_search import (
    IMAGE,
    INDEX_NOT_READY,
    INDEX_OUTDATED,
    INDEX_READY,
    ON_SCREEN_TEXT_CHARACTERS,
    TEXT_CHARACTERS,
    TEXT_MEANING,
    merge_into_ranges,
    normalized,
    search_screen_text,
    search_visual_moments,
    search_visual_text,
    standout_frames,
    standout_positions,
)
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"

READY_STATE = [{"visual_status": "ready", "visual_error": None, "visual_index_version": CURRENT_VISUAL_INDEX_VERSION}]

SEGMENTS = [
    {"segment_id": "s0", "segment_index": 0, "start_seconds": 0.0, "end_seconds": 20.0, "boundary_kind": "video_start", "keyframe_times": [0.0]},
    {"segment_id": "s1", "segment_index": 1, "start_seconds": 20.0, "end_seconds": 40.0, "boundary_kind": "scene_change", "keyframe_times": [20.0]},
    {"segment_id": "s2", "segment_index": 2, "start_seconds": 40.0, "end_seconds": 60.0, "boundary_kind": "text_change", "keyframe_times": [40.0]},
]

# Segment 2 has a second keyframe at 50 s, so the text read at 40 s stands for 40-50 s.
SEGMENTS_WITH_TWO_KEYFRAMES = SEGMENTS[:2] + [{**SEGMENTS[2], "keyframe_times": [40.0, 50.0]}]

CHAPTERS = [
    {"chapter_id": "c0", "chapter_index": 0, "title": "Opening", "summary": "", "start_seconds": 0.0, "end_seconds": 30.0},
    {"chapter_id": "c1", "chapter_index": 1, "title": "The diagram", "summary": "", "start_seconds": 30.0, "end_seconds": 60.0},
]


def ten_second_segments(count: int, *, second_keyframe_at: float | None = None) -> list[dict]:
    """`count` segments of ten seconds each, a keyframe at each start (and optionally one more)."""
    return [
        {
            "segment_id": f"s{index}",
            "segment_index": index,
            "start_seconds": index * 10.0,
            "end_seconds": index * 10.0 + 10.0,
            "boundary_kind": "scene_change",
            "keyframe_times": [index * 10.0]
            + ([index * 10.0 + second_keyframe_at] if second_keyframe_at is not None else []),
        }
        for index in range(count)
    ]


def frame_scores(hits: dict[float, float], *, until: int = 60, background: float = 0.05) -> list[dict]:
    """Frames two seconds apart up to `until`, all near `background` except the ones in `hits`."""
    return [
        {"time_seconds": float(t), "similarity": hits.get(float(t), background + (t % 4) * 0.001)}
        for t in range(0, until, 2)
    ]


def flat_frames(until: int = 60) -> list[dict]:
    """Frames that all score the same, so none stands out and none is present."""
    return [{"time_seconds": float(t), "similarity": 0.05} for t in range(0, until, 2)]


def opened_index(*, segments: list[dict], texts: dict[float, str], unread: int) -> list[list[dict]]:
    """The reads every search makes to open the index, answered in order."""
    return [
        READY_STATE,
        segments,
        CHAPTERS,
        [{"unread_count": unread}],
        [{"time_seconds": time, "ocr_text": text} for time, text in texts.items()],
    ]


def moments_pool(
    *,
    frames: list[dict],
    segments: list[dict] = SEGMENTS,
    texts: dict[float, str] | None = None,
    unread: int = 0,
) -> FakePool:
    """A pool answering `search_visual_moments`'s reads in the order it makes them."""
    return FakePool(responses=[*opened_index(segments=segments, texts=texts or {}, unread=unread), frames])


def screen_pool(
    texts: dict[float, str],
    *,
    text_scores: dict[float, float] | None = None,
    segments: list[dict] = SEGMENTS,
    unread: int = 0,
) -> FakePool:
    """A pool answering `search_screen_text`'s reads in the order it makes them.

    The keyframe-text scores are read only when some keyframe shows text; texts with no score
    have no e5 vector, so they can be found by their words and never by meaning.
    """
    responses = opened_index(segments=segments, texts=texts, unread=unread)
    if texts:
        scores = text_scores or {}
        responses.append(
            [
                {"time_seconds": time, "ocr_text": texts[time], "similarity": score}
                for time, score in sorted(scores.items(), key=lambda item: -item[1])
            ]
        )
    return FakePool(responses=responses)


def search(pool: FakePool, **options):
    return search_visual_moments(
        VIDEO_ID, "the architecture diagram", pool=pool, image_query_encoder=lambda _: [1.0], **options
    )


def screen_search(pool: FakePool, words=None, **options):
    return search_screen_text(
        VIDEO_ID,
        "the architecture diagram",
        words,
        pool=pool,
        on_screen_text_query_encoder=lambda _: [1.0],
        **options,
    )


def reads_the_transcript(pool: FakePool) -> bool:
    return any("transcript_segments" in statement for statement in pool.statements)


# --- what counts as a hit ------------------------------------------------------------------


def test_a_frame_is_a_hit_from_a_z_score_of_one_and_a_half() -> None:
    # z-scores of the last three: 1.40, 1.60 and 3.59.
    scores = [0.0] * 17 + [0.45, 0.5, 1.0]

    standouts = standout_frames(range(20), scores, z_threshold=1.5, present_similarity=2.0)

    assert [frame.time_seconds for frame in standouts] == [18.0, 19.0]
    assert standouts[0].z_score == pytest.approx(1.602, abs=1e-3)


def test_a_frame_that_stands_out_is_a_hit_however_low_it_scores() -> None:
    # "A dog" on a padel match: there is no floor; the agent's look decides.
    scores = [0.010 + 0.001 * (i % 3) for i in range(30)]
    scores[7] = 0.031

    standouts = standout_frames(range(30), scores, z_threshold=1.5, present_similarity=0.15)

    assert [frame.time_seconds for frame in standouts] == [7.0]


def test_something_on_screen_the_whole_time_is_found_though_nothing_stands_out() -> None:
    scores = [0.18 + 0.001 * (i % 3) for i in range(30)]
    scores[4] = 0.5

    standouts = standout_frames(range(30), scores, z_threshold=1.5, present_similarity=0.15)

    # Every frame is at the present level, whatever its z-score.
    assert len(standouts) == 30
    assert min(frame.z_score for frame in standouts) < 0


def test_consecutive_hits_merge_into_one_range_with_its_peak() -> None:
    frames = standout_frames(
        [0.0, 2.0, 4.0, 6.0, 8.0, 30.0] + [float(t) for t in range(40, 100, 2)],
        [0.3, 0.35, 0.3, 0.02, 0.02, 0.3] + [0.02] * 30,
        z_threshold=1.5,
        present_similarity=1.0,
    )

    ranges = merge_into_ranges(frames, interval_seconds=2.0)

    assert [(r.start_seconds, r.end_seconds) for r in ranges] == [(0.0, 4.0), (30.0, 30.0)]
    assert ranges[0].peak_time_seconds == 2.0


def test_few_scores_are_all_hits_and_many_are_judged_by_their_z_score() -> None:
    few = [0.9, 0.8, 0.7]
    many = [0.8] * 19 + [0.95]

    assert standout_positions(few, z_threshold=1.5, minimum_for_z_score=20) == [0, 1, 2]
    assert standout_positions(many, z_threshold=1.5, minimum_for_z_score=20) == [19]
    assert standout_positions([0.8] * 20, z_threshold=1.5, minimum_for_z_score=20) == []


# --- the index -----------------------------------------------------------------------------


def _run(search_name: str, pool: FakePool):
    if search_name == "moments":
        return search(pool)
    if search_name == "screen":
        return screen_search(pool, ["kafka"])
    return search_visual_text(VIDEO_ID, ["kafka"], pool=pool)


@pytest.mark.parametrize("search_name", ["moments", "screen", "words_only"])
def test_a_video_whose_index_is_not_ready_is_not_searched(search_name: str) -> None:
    pool = FakePool(responses=[[{"visual_status": "indexing", "visual_error": None, "visual_index_version": None}]])

    result = _run(search_name, pool)

    assert (result.index_status, result.visual_status, result.moments) == (INDEX_NOT_READY, "indexing", ())
    assert len(pool.recorded) == 1


@pytest.mark.parametrize("search_name", ["moments", "screen", "words_only"])
def test_an_index_built_with_other_models_is_refused_rather_than_mixed(search_name: str) -> None:
    pool = FakePool(responses=[[{"visual_status": "ready", "visual_error": None, "visual_index_version": "clip@1fps"}]])

    result = _run(search_name, pool)

    assert (result.index_status, result.moments) == (INDEX_OUTDATED, ())


def test_a_video_that_does_not_exist_is_not_ready() -> None:
    result = search(FakePool(responses=[[]]))

    assert (result.index_status, result.visual_status) == (INDEX_NOT_READY, None)


def test_keyframes_ocr_has_not_read_yet_are_reported() -> None:
    result = screen_search(screen_pool({}, unread=3))

    assert result.index_status == INDEX_READY
    assert result.ocr_pending and result.unread_keyframe_count == 3
    assert not screen_search(screen_pool({})).ocr_pending


# --- search_visual_moments: the picture only -----------------------------------------------


def test_a_picture_hit_carries_its_best_frame_its_segment_and_its_chapter() -> None:
    result = search(moments_pool(frames=frame_scores({32.0: 0.28, 34.0: 0.3})))

    [moment] = result.moments
    assert moment.frame_seconds == 34.0
    assert (moment.start_seconds, moment.end_seconds) == (32.0, 34.0)
    assert moment.found_by == (IMAGE,)
    assert moment.segment.segment_index == 1
    assert moment.chapter.title == "The diagram"
    assert moment.peak_z_score > 1.5
    assert not moment.weak and not result.nothing_stood_out


def test_the_picture_search_reads_neither_the_on_screen_text_nor_the_transcript() -> None:
    def no_model(_query):
        raise AssertionError("e5 must not load for a picture search")

    pool = moments_pool(
        frames=frame_scores({52.0: 0.3}),
        segments=SEGMENTS_WITH_TWO_KEYFRAMES,
        texts={40.0: "First half", 50.0: "Second half"},
    )

    [moment] = search(pool).moments

    assert moment.on_screen_text is None
    assert not reads_the_transcript(pool)
    assert not any("ocr_embedding <=>" in statement for statement in pool.statements)


def test_a_picture_range_crossing_a_segment_boundary_is_one_moment_in_each() -> None:
    result = search(
        moments_pool(frames=frame_scores({16.0: 0.3, 18.0: 0.31, 20.0: 0.32, 22.0: 0.3}))
    )

    assert sorted((m.segment.segment_index, m.frame_seconds) for m in result.moments) == [(0, 18.0), (1, 20.0)]


def test_a_segment_keeps_only_its_range_whose_best_frame_stood_out_most() -> None:
    # Two separate ranges in segment 0; the later one stood out more.
    result = search(moments_pool(frames=frame_scores({2.0: 0.25, 12.0: 0.35, 14.0: 0.3})))

    [moment] = result.moments
    assert (moment.segment.segment_index, moment.frame_seconds) == (0, 12.0)
    assert (moment.start_seconds, moment.end_seconds) == (12.0, 14.0)


def test_picture_moments_are_ranked_by_how_far_they_stood_out_and_cut_to_six() -> None:
    # One hit in each of eight segments, the later ones standing out less.
    segments = ten_second_segments(8)
    hits = {index * 10.0 + 4.0: 0.40 - index * 0.02 for index in range(8)}

    result = search(moments_pool(frames=frame_scores(hits, until=80), segments=segments))

    assert [moment.frame_seconds for moment in result.moments] == [4.0, 14.0, 24.0, 34.0, 44.0, 54.0]


def test_something_on_screen_the_whole_time_comes_back_once_per_segment() -> None:
    frames = [{"time_seconds": float(t), "similarity": 0.2 + (0.01 if t == 26 else 0.0)} for t in range(0, 60, 2)]

    result = search(moments_pool(frames=frames))

    assert sorted(moment.segment.segment_index for moment in result.moments) == [0, 1, 2]
    assert not result.nothing_stood_out


# --- search_visual_moments: when nothing stands out ----------------------------------------


def two_level_frames(until: int, *, high_from: float, bumps: dict[float, float]) -> list[dict]:
    """Frames at 0.050 before `high_from` and 0.051 from it, with a few nudged a hair higher.

    Two levels half and half put every frame about one standard deviation from the mean, so
    none stands out and none is present: nothing matched.
    """
    return [
        {"time_seconds": float(t), "similarity": bumps.get(float(t), 0.051 if t >= high_from else 0.050)}
        for t in range(0, until, 2)
    ]


def test_when_nothing_stands_out_the_three_closest_frames_come_back_weak() -> None:
    frames = two_level_frames(80, high_from=40.0, bumps={72.0: 0.05103, 44.0: 0.05102, 56.0: 0.05101})

    result = search(moments_pool(frames=frames, segments=ten_second_segments(8)))

    assert result.index_status == INDEX_READY
    assert result.nothing_stood_out
    assert [moment.frame_seconds for moment in result.moments] == [72.0, 44.0, 56.0]
    assert all(moment.weak for moment in result.moments)
    assert all(moment.start_seconds == moment.end_seconds == moment.frame_seconds for moment in result.moments)
    assert all(moment.peak_z_score < 1.5 for moment in result.moments)


def test_the_weak_frames_are_each_from_a_different_segment() -> None:
    # The two best frames are both in segment 1; the second is passed over, and so is every
    # other frame of segments 1 and 2 once each has given one.
    frames = two_level_frames(60, high_from=20.0, bumps={22.0: 0.05103, 24.0: 0.05102, 50.0: 0.05101})

    result = search(moments_pool(frames=frames))

    assert [(m.segment.segment_index, m.frame_seconds) for m in result.moments] == [(1, 22.0), (2, 50.0), (0, 0.0)]


def test_with_no_frames_at_all_nothing_stood_out_and_nothing_comes_back() -> None:
    result = search(moments_pool(frames=[]))

    assert result.nothing_stood_out and result.moments == ()


# --- search_screen_text: by meaning --------------------------------------------------------


def test_with_few_texts_the_closest_five_are_returned_with_no_z_filter() -> None:
    segments = ten_second_segments(7)
    texts = {index * 10.0: f"slide {index}" for index in range(7)}
    # Far apart, but no z-score is taken over seven texts: the five closest come back.
    scores = {index * 10.0: 0.95 - index * 0.05 for index in range(7)}

    result = screen_search(screen_pool(texts, text_scores=scores, segments=segments))

    assert [moment.start_seconds for moment in result.moments] == [0.0, 10.0, 20.0, 30.0, 40.0]
    assert all(moment.found_by == (TEXT_MEANING,) for moment in result.moments)
    assert result.moments[0].on_screen_text == "slide 0"


def test_with_twenty_texts_or_more_only_those_that_stand_out_are_hits() -> None:
    segments = ten_second_segments(24)
    texts = {index * 10.0: f"slide {index}" for index in range(24)}
    scores = {index * 10.0: 0.80 + (index % 3) * 0.001 for index in range(24)}
    scores[70.0] = 0.95

    result = screen_search(screen_pool(texts, text_scores=scores, segments=segments))

    [moment] = result.moments
    assert (moment.start_seconds, moment.end_seconds) == (70.0, 80.0)
    assert moment.on_screen_text == "slide 7"


def test_two_keyframes_of_one_segment_matching_by_meaning_are_one_moment() -> None:
    texts = {40.0: "Architecture diagram", 50.0: "Architecture diagram, continued"}

    result = screen_search(
        screen_pool(texts, text_scores={40.0: 0.88, 50.0: 0.9}, segments=SEGMENTS_WITH_TWO_KEYFRAMES)
    )

    [moment] = result.moments
    assert (moment.start_seconds, moment.end_seconds) == (40.0, 60.0)
    # The text shown is the keyframe that matched best.
    assert moment.on_screen_text == "Architecture diagram, continued"


def test_a_video_whose_keyframes_show_no_text_is_not_searched_for_it() -> None:
    def no_model(_query):
        raise AssertionError("e5 must not load for a video with no on-screen text")

    pool = screen_pool({})

    result = search_screen_text(VIDEO_ID, "a diagram", pool=pool, on_screen_text_query_encoder=no_model)

    assert result.moments == ()
    assert not any("ocr_embedding <=>" in statement for statement in pool.statements)


def test_a_screen_text_moment_carries_its_text_capped_and_reads_no_transcript() -> None:
    pool = screen_pool({40.0: "word " * 200}, text_scores={40.0: 0.9})

    [moment] = screen_search(pool).moments

    assert len(moment.on_screen_text) <= ON_SCREEN_TEXT_CHARACTERS
    assert moment.on_screen_text.endswith("…")
    assert not reads_the_transcript(pool)


# --- search_screen_text: by exact words ----------------------------------------------------


def test_case_and_whitespace_are_ignored_on_both_sides() -> None:
    result = screen_search(
        screen_pool({20.0: "Kafka\nPartitions", 40.0: "Load Bal ancer"}),
        ["kafka partitions", "  LOAD\tbalancer "],
    )

    assert [(m.start_seconds, m.matched_words) for m in result.moments] == [
        (20.0, ("kafka partitions",)),
        (40.0, ("  LOAD\tbalancer ",)),
    ]
    assert normalized(" Kaf ka\n PARTITIONS ") == "kafkapartitions"


def test_a_hebrew_word_is_found_with_a_prefix_before_it() -> None:
    result = screen_search(screen_pool({0.0: "הכוס על השולחן"}), ["כוס"])

    [moment] = result.moments
    assert moment.found_by == (TEXT_CHARACTERS,)
    assert moment.matched_words == ("כוס",)
    assert moment.on_screen_text == "הכוס על השולחן"


def test_a_misreading_is_not_found_by_its_words() -> None:
    result = screen_search(screen_pool({0.0: "Kafka Partitons"}), ["partitions"])

    assert result.index_status == INDEX_READY
    assert result.moments == ()


def test_word_moments_are_ordered_by_different_words_found_then_by_time() -> None:
    result = screen_search(
        screen_pool({0.0: "kafka", 20.0: "KAFKA and its partitions", 40.0: "partitions, again"}),
        ["Kafka", "Partitions", "kafka"],
    )

    assert [(m.segment.segment_index, m.matched_words) for m in result.moments] == [
        # "kafka" twice is one word: found as the caller first wrote it.
        (1, ("Kafka", "Partitions")),
        (0, ("Kafka",)),
        (2, ("Partitions",)),
    ]
    assert result.moments[0].chapter.title == "Opening"


def test_the_words_of_one_segments_keyframes_are_one_moment() -> None:
    result = screen_search(
        screen_pool({40.0: "Kafka", 50.0: "Kafka partitions"}, segments=SEGMENTS_WITH_TWO_KEYFRAMES),
        ["kafka", "partitions"],
    )

    [moment] = result.moments
    assert (moment.start_seconds, moment.end_seconds) == (40.0, 60.0)
    assert moment.matched_words == ("kafka", "partitions")
    # The keyframe that shows the most of the words.
    assert moment.on_screen_text == "Kafka partitions"


@pytest.mark.parametrize(
    "words",
    [[], ["a", "b", "c", "d", "e", "f"], ["kafka", " \n\t "], "kafka", [3]],
)
def test_words_that_cannot_be_searched_for_are_refused_before_anything_is_read(words) -> None:
    pool = FakePool()

    with pytest.raises(ValueError):
        screen_search(pool, words)
    with pytest.raises(ValueError):
        search_visual_text(VIDEO_ID, words, pool=pool)

    assert pool.recorded == []


# --- search_screen_text: the two lists together --------------------------------------------


def test_the_exact_word_matches_come_first_then_the_ones_by_meaning() -> None:
    texts = {0.0: "Agenda", 20.0: "Kafka partitions", 40.0: "How the brokers are laid out"}

    result = screen_search(screen_pool(texts, text_scores={40.0: 0.9, 0.0: 0.7}), ["kafka"])

    assert [(m.start_seconds, m.found_by) for m in result.moments] == [
        (20.0, (TEXT_CHARACTERS,)),
        (40.0, (TEXT_MEANING,)),
        (0.0, (TEXT_MEANING,)),
    ]


def test_a_moment_both_lists_found_is_returned_by_each_not_merged() -> None:
    texts = {40.0: "Architecture diagram", 50.0: "Kafka architecture diagram"}

    result = screen_search(
        screen_pool(texts, text_scores={40.0: 0.9}, segments=SEGMENTS_WITH_TWO_KEYFRAMES), ["kafka"]
    )

    assert [(m.found_by, m.start_seconds, m.end_seconds, m.on_screen_text) for m in result.moments] == [
        ((TEXT_CHARACTERS,), 50.0, 60.0, "Kafka architecture diagram"),
        ((TEXT_MEANING,), 40.0, 50.0, "Architecture diagram"),
    ]


def test_each_list_keeps_its_best_five() -> None:
    segments = ten_second_segments(7)
    texts = {index * 10.0: f"kafka slide {index}" for index in range(7)}
    scores = {index * 10.0: 0.95 - index * 0.05 for index in range(7)}

    result = screen_search(screen_pool(texts, text_scores=scores, segments=segments), ["kafka"])

    assert [m.found_by for m in result.moments] == [(TEXT_CHARACTERS,)] * 5 + [(TEXT_MEANING,)] * 5


def test_the_words_only_search_left_for_the_old_sub_agent_still_finds_words() -> None:
    pool = FakePool(responses=opened_index(segments=SEGMENTS, texts={20.0: "Kafka"}, unread=0))

    [moment] = search_visual_text(VIDEO_ID, ["kafka"], pool=pool).moments

    assert (moment.start_seconds, moment.found_by) == (20.0, (TEXT_CHARACTERS,))
    assert not any("ocr_embedding <=>" in statement for statement in pool.statements)
