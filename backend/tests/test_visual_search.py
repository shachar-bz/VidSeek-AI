"""Tests for the two visual searches: what counts as a hit, how hits become moments, and what comes back.

The stores are answered by a `FakePool`, in the order the searches read them -- the index state,
the segments, the chapters, the count of unread keyframes, the keyframe texts, then (for
`search_visual_moments`) the frame scores and the keyframe-text scores, and last the transcript
of each moment in the order returned. The query encoders are stood in for, so each test says
exactly what matched and checks what the search made of it.
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
    TRANSCRIPT_CHARACTERS,
    merge_into_ranges,
    normalized,
    reciprocal_rank_fusion,
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


def moments_pool(
    *,
    frames: list[dict],
    segments: list[dict] = SEGMENTS,
    texts: dict[float, str] | None = None,
    text_scores: dict[float, float] | None = None,
    unread: int = 0,
    transcripts: list[list[dict]] = (),
) -> FakePool:
    """A pool answering `search_visual_moments`'s reads in the order it makes them."""
    texts = texts or {}
    responses = [
        READY_STATE,
        segments,
        CHAPTERS,
        [{"unread_count": unread}],
        [{"time_seconds": time, "ocr_text": text} for time, text in texts.items()],
        frames,
    ]
    if texts:
        scores = text_scores or {}
        responses.append(
            [
                {"time_seconds": time, "ocr_text": texts[time], "similarity": score}
                for time, score in sorted(scores.items(), key=lambda item: -item[1])
            ]
        )
    responses.extend(transcripts)
    return FakePool(responses=responses)


def text_pool(
    texts: dict[float, str],
    *,
    segments: list[dict] = SEGMENTS,
    unread: int = 0,
    transcripts: list[list[dict]] = (),
) -> FakePool:
    """A pool answering `search_visual_text`'s reads in the order it makes them."""
    return FakePool(
        responses=[
            READY_STATE,
            segments,
            CHAPTERS,
            [{"unread_count": unread}],
            [{"time_seconds": time, "ocr_text": text} for time, text in texts.items()],
            *transcripts,
        ]
    )


def search(pool: FakePool, **options):
    return search_visual_moments(
        VIDEO_ID,
        "the architecture diagram",
        pool=pool,
        image_query_encoder=lambda _: [1.0],
        on_screen_text_query_encoder=lambda _: [1.0],
        **options,
    )


def transcript_reads(pool: FakePool) -> list[tuple]:
    """The windows the transcript was read by time for, in order."""
    return [
        item.parameters
        for item in pool.recorded
        if "from public.transcript_segments" in item.statement
    ]


# --- what counts as a hit ------------------------------------------------------------------


def test_a_frame_is_a_hit_from_a_z_score_of_one_and_a_half() -> None:
    # z-scores of the last three: 1.40, 1.60 and 3.59.
    scores = [0.0] * 17 + [0.45, 0.5, 1.0]

    standouts = standout_frames(range(20), scores, z_threshold=1.5, present_similarity=2.0)

    assert [frame.time_seconds for frame in standouts] == [18.0, 19.0]
    assert standouts[0].z_score == pytest.approx(1.602, abs=1e-3)


def test_a_frame_that_stands_out_is_a_hit_however_low_it_scores() -> None:
    # "A dog" on a padel match: there is no floor any more; the sub-agent's look decides.
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


# --- search_visual_moments: the index ------------------------------------------------------


@pytest.mark.parametrize("run", ["moments", "text"])
def test_a_video_whose_index_is_not_ready_is_not_searched(run: str) -> None:
    pool = FakePool(responses=[[{"visual_status": "indexing", "visual_error": None, "visual_index_version": None}]])

    result = search(pool) if run == "moments" else search_visual_text(VIDEO_ID, ["kafka"], pool=pool)

    assert (result.index_status, result.visual_status, result.moments) == (INDEX_NOT_READY, "indexing", ())
    assert len(pool.recorded) == 1


@pytest.mark.parametrize("run", ["moments", "text"])
def test_an_index_built_with_other_models_is_refused_rather_than_mixed(run: str) -> None:
    pool = FakePool(responses=[[{"visual_status": "ready", "visual_error": None, "visual_index_version": "clip@1fps"}]])

    result = search(pool) if run == "moments" else search_visual_text(VIDEO_ID, ["kafka"], pool=pool)

    assert (result.index_status, result.moments) == (INDEX_OUTDATED, ())


def test_a_video_that_does_not_exist_is_not_ready() -> None:
    result = search(FakePool(responses=[[]]))

    assert (result.index_status, result.visual_status) == (INDEX_NOT_READY, None)


def test_keyframes_ocr_has_not_read_yet_are_reported() -> None:
    result = search(moments_pool(frames=flat_frames(), unread=3))

    assert result.index_status == INDEX_READY
    assert result.ocr_pending and result.unread_keyframe_count == 3
    assert not search(moments_pool(frames=flat_frames())).ocr_pending


def test_a_video_whose_keyframes_show_no_text_is_not_searched_for_it() -> None:
    def no_model(_query):
        raise AssertionError("e5 must not load for a video with no on-screen text")

    pool = moments_pool(frames=flat_frames())

    result = search_visual_moments(
        VIDEO_ID,
        "a diagram",
        pool=pool,
        image_query_encoder=lambda _: [1.0],
        on_screen_text_query_encoder=no_model,
    )

    assert result.moments == ()
    assert not any("ocr_embedding <=>" in statement for statement in pool.statements)


# --- search_visual_moments: the picture ----------------------------------------------------


def test_image_hits_come_back_as_moments_placed_in_segment_and_chapter() -> None:
    result = search(moments_pool(frames=frame_scores({32.0: 0.3, 34.0: 0.28})))

    [moment] = result.moments
    assert (moment.start_seconds, moment.end_seconds) == (32.0, 34.0)
    assert moment.found_by == (IMAGE,)
    assert moment.segment.segment_index == 1
    assert moment.chapter.title == "The diagram"
    assert moment.peak_z_score > 1.5


def test_a_picture_range_crossing_a_segment_boundary_is_two_moments() -> None:
    result = search(
        moments_pool(frames=frame_scores({16.0: 0.3, 18.0: 0.31, 20.0: 0.32, 22.0: 0.3}))
    )

    assert sorted((m.segment.segment_index, m.start_seconds, m.end_seconds) for m in result.moments) == [
        (0, 16.0, 18.0),
        (1, 20.0, 22.0),
    ]


def test_picture_moments_are_ranked_by_how_far_they_stood_out_and_cut_to_five() -> None:
    # One hit in each of seven segments, the later ones standing out less.
    segments = ten_second_segments(7)
    hits = {index * 10.0 + 4.0: 0.40 - index * 0.02 for index in range(7)}

    result = search(moments_pool(frames=frame_scores(hits, until=70), segments=segments))

    assert [moment.start_seconds for moment in result.moments] == [4.0, 14.0, 24.0, 34.0, 44.0]


def test_nothing_found_anywhere_is_an_empty_answer_not_the_least_bad_frames() -> None:
    result = search(moments_pool(frames=flat_frames()))

    assert result.index_status == INDEX_READY
    assert result.moments == ()


# --- search_visual_moments: on-screen text by meaning --------------------------------------


def test_with_few_texts_the_closest_five_are_returned_with_no_z_filter() -> None:
    segments = ten_second_segments(7)
    texts = {index * 10.0: f"slide {index}" for index in range(7)}
    # Far apart, but no z-score is taken over seven texts: the five closest come back.
    scores = {index * 10.0: 0.95 - index * 0.05 for index in range(7)}

    result = search(
        moments_pool(frames=flat_frames(70), segments=segments, texts=texts, text_scores=scores)
    )

    assert [moment.start_seconds for moment in result.moments] == [0.0, 10.0, 20.0, 30.0, 40.0]
    assert all(moment.found_by == (TEXT_MEANING,) for moment in result.moments)
    assert result.moments[0].on_screen_text == "slide 0"


def test_with_twenty_texts_or_more_only_those_that_stand_out_are_hits() -> None:
    segments = ten_second_segments(24)
    texts = {index * 10.0: f"slide {index}" for index in range(24)}
    scores = {index * 10.0: 0.80 + (index % 3) * 0.001 for index in range(24)}
    scores[70.0] = 0.95

    result = search(
        moments_pool(frames=flat_frames(240), segments=segments, texts=texts, text_scores=scores)
    )

    [moment] = result.moments
    assert (moment.start_seconds, moment.end_seconds) == (70.0, 80.0)
    assert moment.on_screen_text == "slide 7"


def test_two_keyframes_of_one_segment_matching_by_meaning_are_one_moment() -> None:
    texts = {40.0: "Architecture diagram", 50.0: "Architecture diagram, continued"}

    result = search(
        moments_pool(
            frames=flat_frames(),
            segments=SEGMENTS_WITH_TWO_KEYFRAMES,
            texts=texts,
            text_scores={40.0: 0.88, 50.0: 0.9},
        )
    )

    [moment] = result.moments
    assert (moment.start_seconds, moment.end_seconds) == (40.0, 60.0)
    # The text shown is the keyframe that matched best.
    assert moment.on_screen_text == "Architecture diagram, continued"


# --- search_visual_moments: joining the two lists ------------------------------------------


def test_a_moment_both_lists_found_appears_once_and_comes_first() -> None:
    result = search(
        moments_pool(
            # The strongest frame is in segment 0; a weaker one is in segment 2.
            frames=frame_scores({4.0: 0.35, 44.0: 0.25}),
            segments=SEGMENTS_WITH_TWO_KEYFRAMES,
            texts={40.0: "Architecture diagram", 20.0: "Agenda"},
            text_scores={40.0: 0.9, 20.0: 0.8},
        )
    )

    first, second, third = result.moments
    assert first.found_by == (IMAGE, TEXT_MEANING)
    assert (first.segment.segment_index, first.start_seconds, first.end_seconds) == (2, 40.0, 50.0)
    assert first.peak_z_score is not None
    assert first.on_screen_text == "Architecture diagram"
    # The rest alternate, picture first.
    assert (second.found_by, second.start_seconds) == ((IMAGE,), 4.0)
    assert (third.found_by, third.start_seconds) == ((TEXT_MEANING,), 20.0)


def test_the_rest_alternate_picture_first_up_to_ten() -> None:
    # Seven segments of ten seconds, each with a frame hit at +2 s and a keyframe at +5 s whose
    # text is on screen from +5 s: in the same segment, but never overlapping.
    segments = ten_second_segments(7, second_keyframe_at=5.0)
    hits = {index * 10.0 + 2.0: 0.40 - index * 0.02 for index in range(7)}
    texts = {index * 10.0 + 5.0: f"slide {index}" for index in range(7)}
    scores = {index * 10.0 + 5.0: 0.95 - index * 0.02 for index in range(7)}

    result = search(
        moments_pool(
            frames=frame_scores(hits, until=70),
            segments=segments,
            texts=texts,
            text_scores=scores,
        )
    )

    assert len(result.moments) == 10
    assert [moment.found_by for moment in result.moments] == [(IMAGE,), (TEXT_MEANING,)] * 5
    assert [moment.start_seconds for moment in result.moments[:4]] == [2.0, 5.0, 12.0, 15.0]


# --- the window ----------------------------------------------------------------------------


def test_a_window_drops_moments_outside_it() -> None:
    result = search(
        moments_pool(frames=frame_scores({4.0: 0.35, 44.0: 0.3})),
        start_seconds=40.0,
        end_seconds=60.0,
    )

    assert [moment.start_seconds for moment in result.moments] == [44.0]


def test_the_z_score_is_taken_over_the_whole_video_not_the_window() -> None:
    # The thing is on screen through 40-50 s, a fifth of the video: every one of those frames
    # stands out from the whole video (z 2). Against the window's ten frames alone, half of
    # them would be the thing and none would stand out (z 1).
    hits = {float(t): 0.12 for t in range(40, 52, 2)}

    result = search(moments_pool(frames=frame_scores(hits)), start_seconds=41.0, end_seconds=60.0)

    [moment] = result.moments
    # Clipped at the window's start, to the first frame seen inside it.
    assert (moment.start_seconds, moment.end_seconds) == (42.0, 50.0)


def test_a_keyframe_text_crossing_the_window_is_clipped_to_it() -> None:
    result = search(
        moments_pool(
            frames=flat_frames(),
            texts={40.0: "Architecture diagram", 0.0: "Agenda"},
            text_scores={40.0: 0.9, 0.0: 0.7},
        ),
        start_seconds=45.0,
        end_seconds=55.0,
    )

    [moment] = result.moments
    assert (moment.start_seconds, moment.end_seconds) == (45.0, 55.0)
    assert moment.on_screen_text == "Architecture diagram"


def test_a_window_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(ValueError):
        search(FakePool(), start_seconds=50.0, end_seconds=10.0)


# --- what every moment carries -------------------------------------------------------------


def test_a_short_moment_is_read_with_the_speech_five_seconds_either_side() -> None:
    pool = moments_pool(
        frames=frame_scores({32.0: 0.3, 34.0: 0.28}),
        transcripts=[
            [
                {"segment_index": 7, "start_seconds": 26.0, "end_seconds": 31.0, "text": " Here is "},
                {"segment_index": 8, "start_seconds": 31.0, "end_seconds": 36.0, "text": "the diagram."},
            ]
        ],
    )

    [moment] = search(pool).moments

    assert transcript_reads(pool) == [(VIDEO_ID, 39.0, 27.0)]
    assert moment.transcript == "Here is the diagram."


def test_a_long_moment_is_read_with_the_speech_while_it_was_on_screen() -> None:
    pool = moments_pool(
        frames=flat_frames(),
        texts={40.0: "Architecture diagram"},
        text_scores={40.0: 0.9},
    )

    [moment] = search(pool).moments

    assert (moment.start_seconds, moment.end_seconds) == (40.0, 60.0)
    assert transcript_reads(pool) == [(VIDEO_ID, 60.0, 40.0)]
    assert moment.transcript is None


def test_the_on_screen_text_and_the_transcript_are_capped() -> None:
    pool = moments_pool(
        frames=flat_frames(),
        texts={40.0: "word " * 200},
        text_scores={40.0: 0.9},
        transcripts=[[{"segment_index": 0, "start_seconds": 40.0, "end_seconds": 60.0, "text": "said " * 300}]],
    )

    [moment] = search(pool).moments

    assert len(moment.on_screen_text) <= ON_SCREEN_TEXT_CHARACTERS
    assert moment.on_screen_text.endswith("…")
    assert len(moment.transcript) <= TRANSCRIPT_CHARACTERS
    assert moment.transcript.endswith("…")


def test_a_picture_moment_shows_the_text_of_the_keyframe_covering_it() -> None:
    result = search(
        moments_pool(
            frames=frame_scores({52.0: 0.3}),
            segments=SEGMENTS_WITH_TWO_KEYFRAMES,
            # The texts have no e5 vector, so only the picture can find anything.
            texts={40.0: "First half", 50.0: "Second half"},
        )
    )

    [moment] = result.moments
    assert moment.found_by == (IMAGE,)
    assert moment.on_screen_text == "Second half"


# --- search_visual_text --------------------------------------------------------------------


def test_case_and_whitespace_are_ignored_on_both_sides() -> None:
    result = search_visual_text(
        VIDEO_ID,
        ["kafka partitions", "  LOAD\tbalancer "],
        pool=text_pool({20.0: "Kafka\nPartitions", 40.0: "Load Bal ancer"}),
    )

    assert [(m.start_seconds, m.matched_words) for m in result.moments] == [
        (20.0, ("kafka partitions",)),
        (40.0, ("  LOAD\tbalancer ",)),
    ]
    assert normalized(" Kaf ka\n PARTITIONS ") == "kafkapartitions"


def test_a_hebrew_word_is_found_with_a_prefix_before_it() -> None:
    result = search_visual_text(VIDEO_ID, ["כוס"], pool=text_pool({0.0: "הכוס על השולחן"}))

    [moment] = result.moments
    assert moment.found_by == (TEXT_CHARACTERS,)
    assert moment.matched_words == ("כוס",)
    assert moment.on_screen_text == "הכוס על השולחן"


def test_a_misreading_is_not_found() -> None:
    result = search_visual_text(VIDEO_ID, ["partitions"], pool=text_pool({0.0: "Kafka Partitons"}))

    assert result.index_status == INDEX_READY
    assert result.moments == ()


def test_moments_are_ordered_by_different_words_found_then_by_time() -> None:
    result = search_visual_text(
        VIDEO_ID,
        ["Kafka", "Partitions", "kafka"],
        pool=text_pool(
            {
                0.0: "kafka",
                20.0: "KAFKA and its partitions",
                40.0: "partitions, again",
            }
        ),
    )

    assert [(m.segment.segment_index, m.matched_words) for m in result.moments] == [
        # "kafka" twice is one word: found as the caller first wrote it.
        (1, ("Kafka", "Partitions")),
        (0, ("Kafka",)),
        (2, ("Partitions",)),
    ]
    assert result.moments[0].chapter.title == "Opening"
    assert result.moments[0].peak_z_score is None


def test_at_most_five_moments_come_back_the_earliest_first() -> None:
    segments = ten_second_segments(7)

    result = search_visual_text(
        VIDEO_ID,
        ["kafka"],
        pool=text_pool({index * 10.0: "kafka" for index in range(7)}, segments=segments),
    )

    assert [moment.start_seconds for moment in result.moments] == [0.0, 10.0, 20.0, 30.0, 40.0]


def test_the_words_of_one_segments_keyframes_are_one_moment() -> None:
    result = search_visual_text(
        VIDEO_ID,
        ["kafka", "partitions"],
        pool=text_pool({40.0: "Kafka", 50.0: "Kafka partitions"}, segments=SEGMENTS_WITH_TWO_KEYFRAMES),
    )

    [moment] = result.moments
    assert (moment.start_seconds, moment.end_seconds) == (40.0, 60.0)
    assert moment.matched_words == ("kafka", "partitions")
    # The keyframe that shows the most of the words.
    assert moment.on_screen_text == "Kafka partitions"


def test_the_window_limits_the_text_search_too() -> None:
    result = search_visual_text(
        VIDEO_ID,
        ["kafka"],
        start_seconds=45.0,
        pool=text_pool({0.0: "kafka", 40.0: "kafka"}),
    )

    assert [(m.start_seconds, m.end_seconds) for m in result.moments] == [(45.0, 60.0)]


def test_ocr_still_reading_is_reported_by_the_text_search() -> None:
    result = search_visual_text(VIDEO_ID, ["kafka"], pool=text_pool({}, unread=12))

    assert result.moments == ()
    assert result.ocr_pending and result.unread_keyframe_count == 12


@pytest.mark.parametrize(
    "words",
    [[], ["a", "b", "c", "d", "e", "f"], ["kafka", " \n\t "], "kafka", [3]],
)
def test_words_that_cannot_be_searched_for_are_refused(words) -> None:
    pool = FakePool()

    with pytest.raises(ValueError):
        search_visual_text(VIDEO_ID, words, pool=pool)

    assert pool.recorded == []


# --- rank fusion (removed with the redesign's deletions) -----------------------------------


def test_rank_fusion_rewards_agreement_and_lets_ties_share_a_rank() -> None:
    fused = reciprocal_rank_fusion({"image": {"a": 1, "b": 2}, "transcript": {"b": 1, "c": 1}})

    assert [item.key for item in fused] == ["b", "a", "c"]
    with pytest.raises(ValueError):
        reciprocal_rank_fusion({"image": {"a": 0}})
