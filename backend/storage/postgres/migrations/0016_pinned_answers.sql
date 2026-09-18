-- The pinned_answers table: which assistant messages an account chose to keep.
--
-- Apply 0015_messages.sql first; every row here points at one message.
--
-- Keyed to the message and cascading with it, per the website spec's §11.5: deleting the
-- conversation a pin came from removes the pin, because deleting the conversation deletes
-- its messages, and a pin outliving the message it pinned would have nothing left to show.
-- There is no separate `user_id` or `video_id` here -- both already follow from the
-- message's conversation, and repeating them would be two more places for a pin to disagree
-- with the conversation it was pinned from.
--
-- A message is pinned or it is not, so the unique constraint is what makes "pin" idempotent:
-- pinning an already-pinned message is not a second pin.

create table if not exists public.pinned_answers (
    id uuid primary key default gen_random_uuid(),

    message_id uuid not null references public.messages (id) on delete cascade,

    created_at timestamptz not null default now(),

    constraint pinned_answers_message_unique unique (message_id)
);

comment on table public.pinned_answers is
    'An assistant message an account pinned; cascades away with the message it pins.';
