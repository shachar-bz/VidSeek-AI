"""Exercise PostgreSQL snapshot semantics using connection-local temporary tables.

Opt in with TEST_PIN_DATABASE_URL. No application tables or rows are modified.
"""
import os
from contextlib import contextmanager

import psycopg
import pytest
from psycopg.rows import dict_row

from backend.storage.postgres.pinned_answers import PostgresPinnedAnswers


def test_first_pin_returns_answer_and_repeated_pin_is_idempotent():
    url = os.environ.get("TEST_PIN_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_PIN_DATABASE_URL for the PostgreSQL regression")
    user = "11111111-1111-1111-1111-111111111111"
    video = "22222222-2222-2222-2222-222222222222"
    chat = "33333333-3333-3333-3333-333333333333"
    message = "44444444-4444-4444-4444-444444444444"
    foreign = "66666666-6666-6666-6666-666666666666"
    with psycopg.connect(url, row_factory=dict_row) as db:
        db.execute("CREATE TEMP TABLE conversations (id uuid PRIMARY KEY, user_id uuid, video_id uuid)")
        db.execute("CREATE TEMP TABLE messages (id uuid PRIMARY KEY, conversation_id uuid, role text, content text)")
        db.execute("CREATE TEMP TABLE pinned_answers (id uuid DEFAULT gen_random_uuid(), message_id uuid UNIQUE, created_at timestamptz DEFAULT now())")
        db.execute("INSERT INTO conversations VALUES (%s, %s, %s)", (chat, user, video))
        db.execute("INSERT INTO messages VALUES (%s, %s, 'assistant', 'Saved answer')", (message, chat))

        class TempConnection:
            def execute(self, sql, params=None):
                return db.execute(sql.replace("public.", "pg_temp."), params)

        class TempPool:
            @contextmanager
            def connection(self):
                yield TempConnection()

        pins = PostgresPinnedAnswers(pool=TempPool())
        first = pins.pin_for_video(user, video, message)
        assert first is not None
        assert first.content == "Saved answer"
        assert first.conversation_id == chat
        assert pins.pin_for_video(user, video, message) == first
        assert pins.pin_for_video(foreign, video, message) is None
        assert pins.pin_for_video(user, foreign, message) is None
        assert db.execute("SELECT count(*) AS n FROM pg_temp.pinned_answers").fetchone()["n"] == 1
        assert pins.unpin_for_video(user, video, message)
        assert pins.list_for_video(user, video) == []
