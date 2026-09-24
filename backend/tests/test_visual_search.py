"""Tests for the visual search: what counts as a hit, how lists are fused, and what comes back.

The stores are answered by a `FakePool`, in the order the search reads them, and the three
query encoders are stood in for, so each test says exactly which frames, captions and memories
matched and checks what the search made of them.
"""

import pytest

from backend.services.visual_indexing import CURRENT_VISUAL_INDEX_VERSION
from backend.services.visual_search import (
    CAPTION,
    IMAGE,
    INDEX_NOT_READY,
    INDEX_OUTDATED,
    INDEX_READY,
    OCR_MEANING,
    OCR_WORDS,
    TRANSCRIPT,
    TimeRange,
    merge_into_ranges,
    reciprocal_rank_fusion,
    search_visual_moments,
    standout_frames,
)
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"

READY_STATE = [{"visual_status": "ready", "visual_error": None, "visual_index_version": CURRENT_VISUAL_INDEX_VERSION}]

SEGMENTS = [
    {"segment_id": "s0", "segment_index": 0, "start_seconds": 0.0, "end_seconds": 20.0, "boundary_kind": "video_start", "keyframe_times": [0.0]},
    {"segment_id": "s1", "segment_index": 1, "start_seconds": 20.0, "end_seconds": 40.0, "boundary_kind": "scene_change", "keyframe_times": [20.0]},
    {"segment_id": "s2", "segment_index": 2, "start_seconds": 40.0, "end_seconds": 60.0, "boundary_kind": "text_change", "keyframe_times": [40.0]},
]

CHAPTERS = [
    {"chapter_id": "c0", "chapter_index": 0, "title": "Opening", "summary": "", "start_seconds": 0.0, "end_seconds": 30.0},
    {"chapter_id": "c1", "chapter_index": 1, "title": "The diagram", "summary": "", "start_seconds": 30.0, "end_seconds": 60.0},
]


def frame_scores(hits: dict[float, float], *, background: float = 0.05) -> list[dict]:
    """Thirty frames two seconds apart, all at `background` except the ones in `hits`."""
    return [
        {"time_seconds": float(t), "similarity": hits.get(float(t), background + (t % 4) * 0.001)}
        for t in range(0, 60, 2)
    ]


def search(pool: FakePool, **options):
    return search_visual_moments(
        VIDEO_ID,
        "the architecture diagram",
        pool=pool,
        image_query_encoder=lambda _: [1.0],
        caption_query_encoder=lambda _: [1.0],
        transcript_query_encoder=lambda _: [1.0],
        **options,
    )


def test_a_frame_counts_only_when_it_stands_out_from_its_own_video() -> None:
    times = [float(t) for t in range(0, 60, 2)]
    scores = [0.05 + 0.001 * (i % 3) for i in range(30)]
    scores[10] = 0.2

    standouts = standout_frames(
        times, scores, z_threshold=2.5, similarity_floor=0.08, present_similarity=0.5
    )

    assert [frame.time_seconds for frame in standouts] == [20.0]


def test_a_chance_standout_with_a_junk_score_is_not_a_hit() -> None:
    # "A dog" on a padel match: one frame stands out, at a similarity nothing real scores.
    scores = [0.010 + 0.001 * (i % 3) for i in range(30)]
    scores[7] = 0.031

    assert standout_frames(
        range(30), scores, z_threshold=2.5, similarity_floor=0.08, present_similarity=0.15
    ) == []


def test_something_on_screen_the_whole_time_is_found_though_nothing_stands_out() -> None:
    scores = [0.18 + 0.001 * (i % 3) for i in range(30)]

    standouts = standout_frames(
        range(30), scores, z_threshold=2.5, similarity_floor=0.08, present_similarity=0.15
    )

    assert len(standouts) == 30


def test_consecutive_hits_merge_into_one_range_with_its_peak() -> None:
    frames = standout_frames(
        [0.0, 2.0, 4.0, 6.0, 8.0, 30.0] + [float(t) for t in range(40, 100, 2)],
        [0.3, 0.35, 0.3, 0.02, 0.02, 0.3] + [0.02] * 30,
        z_threshold=2.0,
        similarity_floor=0.08,
        present_similarity=1.0,
    )

    ranges = merge_into_ranges(frames, interval_seconds=2.0)

    assert [(r.start_seconds, r.end_seconds) for r in ranges] == [(0.0, 4.0), (30.0, 30.0)]
    assert ranges[0].peak_time_seconds == 2.0


def test_rank_fusion_rewards_agreement_and_lets_ties_share_a_rank() -> None:
    fused = reciprocal_rank_fusion(
        {IMAGE: {"a": 1, "b": 2}, TRANSCRIPT: {"b": 1, "c": 1}}
    )

    assert [item.key for item in fused] == ["b", "a", "c"]
    assert fused[0].sources == (IMAGE, TRANSCRIPT)
    assert fused[1].score == pytest.approx(fused[2].score)
    with pytest.raises(ValueError):
        reciprocal_rank_fusion({IMAGE: {"a": 0}})


def test_a_video_whose_index_is_not_ready_is_not_searched() -> None:
    pool = FakePool(responses=[[{"visual_status": "indexing", "visual_error": None, "visual_index_version": None}]])

    result = search(pool)

    assert (result.index_status, result.visual_status, result.moments) == (INDEX_NOT_READY, "indexing", ())
    assert len(pool.recorded) == 1


def test_an_index_built_with_other_models_is_refused_rather_than_mixed() -> None:
    pool = FakePool(responses=[[{"visual_status": "ready", "visual_error": None, "visual_index_version": "clip@1fps"}]])

    result = search(pool)

    assert result.index_status == INDEX_OUTDATED


def test_image_hits_come_back_as_ranges_tagged_with_segment_and_chapter() -> None:
    pool = FakePool(
        responses=[
            READY_STATE,
            SEGMENTS,
            CHAPTERS,
            frame_scores({32.0: 0.3, 34.0: 0.28}),
            [{"caption_count": 0}],
            [],
        ]
    )

    result = search(pool)

    assert result.index_status == INDEX_READY and result.image_match_found
    moment = result.moments[0]
    assert (moment.start_seconds, moment.end_seconds) == (32.0, 34.0)
    assert moment.matched_ranges == (TimeRange(32.0, 34.0),)
    assert moment.sources == (IMAGE,)
    assert moment.segment.segment_index == 1
    assert moment.chapter.title == "The diagram"
    assert moment.peak_z_score > 2.5


def test_the_picture_and_the_transcript_agreeing_ranks_first() -> None:
    pool = FakePool(
        responses=[
            READY_STATE,
            SEGMENTS,
            CHAPTERS,
            # The strongest frame is in segment 0; a weaker one is in segment 2.
            frame_scores({4.0: 0.35, 44.0: 0.25}),
            [{"caption_count": 0}],
            # The transcript names the diagram in segment 2, and below the floor elsewhere.
            [
                {"memory_id": "m1", "start_seconds": 38.0, "end_seconds": 50.0, "similarity": 0.6},
                {"memory_id": "m2", "start_seconds": 0.0, "end_seconds": 10.0, "similarity": 0.1},
            ],
        ]
    )

    result = search(pool)

    first, second = result.moments[:2]
    assert first.segment.segment_index == 2
    assert first.sources == (IMAGE, TRANSCRIPT)
    # The picture pinned it down, so the frame range is reported rather than the memory's.
    assert first.matched_ranges == (TimeRange(44.0, 44.0),)
    assert second.segment.segment_index == 0
    # The memory also overlaps segment 1, which the picture never matched.
    transcript_only = [m for m in result.moments if m.sources == (TRANSCRIPT,)]
    assert transcript_only[0].segment.segment_index == 1
    assert transcript_only[0].matched_ranges == (TimeRange(38.0, 40.0),)


def test_saved_captions_are_searched_and_reported_when_the_video_has_any() -> None:
    pool = FakePool(
        responses=[
            READY_STATE,
            SEGMENTS,
            CHAPTERS,
            frame_scores({}),
            [{"caption_count": 2}],
            [
                {"id": "k1", "time_seconds": 24.0, "end_seconds": 30.0, "caption": "A diagram of three services on a whiteboard", "similarity": 0.88},
                {"id": "k2", "time_seconds": 50.0, "end_seconds": None, "caption": "A kitchen", "similarity": 0.7},
            ],
            [],
        ]
    )

    result = search(pool)

    assert not result.image_match_found
    assert [moment.sources for moment in result.moments] == [(CAPTION,)]
    assert result.moments[0].caption.startswith("A diagram")
    assert result.moments[0].matched_ranges == (TimeRange(24.0, 30.0),)


def test_a_caption_far_behind_the_best_one_is_not_a_match_even_above_the_floor() -> None:
    # e5 scores bunch up: an unrelated caption can clear the floor, but not by as much as the
    # caption that actually describes the query.
    pool = FakePool(
        responses=[
            READY_STATE,
            SEGMENTS,
            CHAPTERS,
            frame_scores({}),
            [{"caption_count": 2}],
            [
                {"id": "k1", "time_seconds": 24.0, "end_seconds": None, "caption": "A colourful fractal", "similarity": 0.905},
                {"id": "k2", "time_seconds": 50.0, "end_seconds": None, "caption": "A white slide", "similarity": 0.803},
            ],
            [],
        ]
    )

    result = search(pool)

    assert [moment.caption for moment in result.moments] == ["A colourful fractal"]


def test_nothing_found_anywhere_is_an_empty_answer_not_the_least_bad_frames() -> None:
    pool = FakePool(
        responses=[READY_STATE, SEGMENTS, CHAPTERS, frame_scores({}), [{"caption_count": 0}], []]
    )

    result = search(pool)

    assert result.index_status == INDEX_READY
    assert result.moments == ()
    assert not result.image_match_found


def test_a_window_limits_where_hits_may_be_but_not_what_stands_out() -> None:
    pool = FakePool(
        responses=[
            READY_STATE,
            SEGMENTS,
            CHAPTERS,
            frame_scores({4.0: 0.35, 44.0: 0.3}),
            [{"caption_count": 0}],
            [],
        ]
    )

    result = search(pool, start_seconds=40.0, end_seconds=60.0)

    assert [moment.segment.segment_index for moment in result.moments] == [2]
    assert result.image_match_found


# --- on-screen text ------------------------------------------------------------------------

# Segment 2 has a second keyframe at 50 s, so the text read at 40 s stands for 40-50 s.
SEGMENTS_WITH_TWO_KEYFRAMES = SEGMENTS[:2] + [{**SEGMENTS[2], "keyframe_times": [40.0, 50.0]}]


def test_on_screen_text_is_found_by_its_words_and_its_meaning_for_the_stretch_it_was_shown() -> None:
    pool = FakePool(
        responses=[
            READY_STATE,
            SEGMENTS_WITH_TWO_KEYFRAMES,
            CHAPTERS,
            frame_scores({}),
            [{"caption_count": 0}],
            [],
            [{"text_count": 2}],
            [
                {"time_seconds": 40.0, "ocr_text": "Architecture diagram", "similarity": 0.9},
                {"time_seconds": 0.0, "ocr_text": "Agenda", "similarity": 0.2},
            ],
            [
                {"time_seconds": 40.0, "ocr_text": "Architecture diagram", "similarity": 0.9},
                {"time_seconds": 0.0, "ocr_text": "Agenda", "similarity": 0.82},
            ],
        ]
    )

    result = search(pool, on_screen_text_query_encoder=lambda _: [1.0])

    # "Agenda" is below the word floor, and too far below the best text by meaning.
    [moment] = result.moments
    assert moment.sources == (OCR_WORDS, OCR_MEANING)
    assert moment.matched_ranges == (TimeRange(40.0, 50.0),)
    assert moment.on_screen_text == "Architecture diagram"
    assert moment.chapter.title == "The diagram"
    assert not result.image_match_found


def test_the_last_keyframe_of_a_segment_stands_for_the_rest_of_it() -> None:
    pool = FakePool(
        responses=[
            READY_STATE,
            SEGMENTS_WITH_TWO_KEYFRAMES,
            CHAPTERS,
            frame_scores({}),
            [{"caption_count": 0}],
            [],
            [{"text_count": 1}],
            [{"time_seconds": 50.0, "ocr_text": "Questions?", "similarity": 1.0}],
            [],
        ]
    )

    result = search(pool, on_screen_text_query_encoder=lambda _: [1.0])

    assert result.moments[0].matched_ranges == (TimeRange(50.0, 60.0),)


def test_a_video_whose_keyframes_show_no_text_is_not_searched_for_it() -> None:
    def no_model(_query):
        raise AssertionError("e5 must not load for a video with no on-screen text")

    pool = FakePool(
        responses=[READY_STATE, SEGMENTS, CHAPTERS, frame_scores({}), [{"caption_count": 0}], [], [{"text_count": 0}]]
    )

    result = search(pool, on_screen_text_query_encoder=no_model)

    assert result.moments == ()
    assert not any("word_similarity" in statement for statement in pool.statements)
