-- The messages table: one turn of a conversation, either side of it.
--
-- Apply 0014_conversations.sql first; every row here points at one.
--
-- Deleting a conversation takes its messages with it, the same as a video takes its
-- transcript: a conversation with no messages is not a state anything needs to keep around
-- once the conversation itself is gone.

create table if not exists public.messages (
    id uuid primary key default gen_random_uuid(),

    conversation_id uuid not null references public.conversations (id) on delete cascade,

    role text not null,
    content text not null,

    -- What the agent did to answer, when `role` is 'assistant': which tools it called and
    -- with what. Null for a user message, which called no tool. Stored so that reopening a
    -- conversation shows how each answer was reached, per the website spec's §9.
    tool_trace jsonb,

    created_at timestamptz not null default now(),

    constraint messages_role_known check (role in ('user', 'assistant'))
);

comment on table public.messages is
    'One turn of a conversation, user or assistant, with the assistant''s tool trace if any.';

-- The one thing anyone asks of this table: one conversation's messages, in the order they
-- were said.
create index if not exists messages_conversation_created_idx
    on public.messages (conversation_id, created_at);
