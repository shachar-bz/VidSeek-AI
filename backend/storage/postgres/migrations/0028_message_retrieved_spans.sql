-- The moments the agent's tools returned while writing an assistant message.
--
-- Apply 0015_messages.sql first.
--
-- An answer may cite only a moment a tool returned. Each turn starts from the earlier turns'
-- spans, so a follow-up that reuses a timestamp the conversation already cited is not
-- mistaken for an invented one. Stored as (start, end) second pairs, [[12.0, 40.5], ...];
-- null for a user message and for an answer that retrieved nothing. Messages written before
-- this column have none, so their timestamps stay uncitable until a tool returns them again.

alter table public.messages
    add column if not exists retrieved_spans jsonb;

comment on column public.messages.retrieved_spans is
    'The (start, end) second spans the agent''s tools returned while answering; what later turns may still cite.';
