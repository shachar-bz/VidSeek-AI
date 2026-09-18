"""Tests for the `user_videos` table: an account's library links."""

import pytest

from backend.storage.postgres import PostgresUserVideos, StoredUserVideo
from backend.storage.postgres.user_videos import TABLE_NAME
from backend.tests.fake_postgres import FakePool

USER_ID = "11111111-1111-1111-1111-111111111111"
VIDEO_ID = "22222222-2222-2222-2222-222222222222"

ROW = {
    "user_id": USER_ID,
    "video_id": VIDEO_ID,
    "custom_title": None,
    "tags": [],
    "added_at": "2026-09-14T10:00:00+00:00",
}


def _user_videos(rows: list[dict] | None = None) -> tuple[PostgresUserVideos, FakePool]:
    pool = FakePool(rows=rows if rows is not None else [])
    return PostgresUserVideos(pool=pool), pool


def test_linking_a_video_inserts_and_reads_the_link_back() -> None:
    user_videos, pool = _user_videos([ROW])
    stored = user_videos.link(USER_ID, VIDEO_ID)

    assert f"insert into public.{TABLE_NAME}" in pool.statements[0]
    assert "on conflict (user_id, video_id) do nothing" in pool.statements[0]
    assert stored == StoredUserVideo(
        user_id=USER_ID, video_id=VIDEO_ID, custom_title=None, tags=[], added_at=ROW["added_at"]
    )


def test_linking_an_already_linked_video_keeps_its_existing_title_and_tags() -> None:
    # The insert conflicts and does nothing; the read afterwards is what hands back the
    # link exactly as it already was, custom title and tags included.
    existing = {**ROW, "custom_title": "My Talk", "tags": ["work"]}
    user_videos, _ = _user_videos([existing])

    stored = user_videos.link(USER_ID, VIDEO_ID)

    assert stored.custom_title == "My Talk"
    assert stored.tags == ["work"]


def test_a_link_that_was_not_accepted_is_an_error_rather_than_a_silent_success() -> None:
    user_videos, _ = _user_videos([])

    with pytest.raises(RuntimeError, match="returned no row"):
        user_videos.link(USER_ID, VIDEO_ID)


def test_unlinking_removes_only_this_accounts_link() -> None:
    user_videos, pool = _user_videos([])
    user_videos.unlink(USER_ID, VIDEO_ID)

    assert pool.statements[0].startswith(f"delete from public.{TABLE_NAME}")
    assert pool.recorded[0].parameters == (USER_ID, VIDEO_ID)


def test_a_video_this_account_never_linked_is_absence_rather_than_an_error() -> None:
    user_videos, _ = _user_videos([])

    assert user_videos.get(USER_ID, VIDEO_ID) is None


def test_a_users_library_comes_back_newest_added_first() -> None:
    user_videos, pool = _user_videos([ROW, ROW])
    found = user_videos.list_for_user(USER_ID)

    assert len(found) == 2
    assert "order by added_at desc" in pool.statements[0]


def test_renaming_sets_the_custom_title() -> None:
    user_videos, pool = _user_videos([{**ROW, "custom_title": "My Talk"}])
    stored = user_videos.rename(USER_ID, VIDEO_ID, "My Talk")

    assert stored is not None and stored.custom_title == "My Talk"
    assert pool.recorded[0].parameters == ("My Talk", USER_ID, VIDEO_ID)


def test_renaming_a_link_that_does_not_exist_is_absence_rather_than_an_error() -> None:
    user_videos, _ = _user_videos([])

    assert user_videos.rename(USER_ID, VIDEO_ID, "My Talk") is None


def test_clearing_a_custom_title_sets_it_back_to_null() -> None:
    user_videos, pool = _user_videos([ROW])
    user_videos.rename(USER_ID, VIDEO_ID, None)

    assert pool.recorded[0].parameters == (None, USER_ID, VIDEO_ID)


def test_setting_tags_replaces_the_whole_set() -> None:
    user_videos, pool = _user_videos([{**ROW, "tags": ["work", "python"]}])
    stored = user_videos.set_tags(USER_ID, VIDEO_ID, ["work", "python"])

    assert stored is not None and stored.tags == ["work", "python"]
    assert pool.recorded[0].parameters == (["work", "python"], USER_ID, VIDEO_ID)


def test_tags_for_a_user_are_distinct_and_alphabetical() -> None:
    user_videos, pool = _user_videos([{"tag": "python"}, {"tag": "work"}])
    tags = user_videos.tags_for_user(USER_ID)

    assert tags == ["python", "work"]
    assert "unnest(tags)" in pool.statements[0]
