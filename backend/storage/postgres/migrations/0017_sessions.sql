-- The sessions table: the bearer token a signed-in account's requests carry, on disk.
--
-- Apply 0008_users.sql first; every row here points at a user.
--
-- Both token registries this replaces are in-process Python dictionaries
-- (`backend/core/auth.py` and `backend/core/security.py`). That was defensible while one
-- process on one machine served one Chrome extension: a restart sent the user back to the
-- login form and nothing else noticed. It stops being defensible the moment a hosted API
-- and the local companion both have to recognise the same login, because a dictionary in
-- one process cannot be read by the other. A row can.
--
-- What this table makes possible, none of which a dictionary could:
--   * one sign-in covering both surfaces, because both validate against the same rows;
--   * a session surviving an API restart;
--   * listing the sessions signed into an account, labelled and timed;
--   * revoking one session, or all of them, from anywhere.
--
-- The token itself is not stored. `token_hash` holds a SHA-256 of it, so that a leaked
-- database dump is not a set of live credentials. SHA-256 rather than bcrypt deliberately:
-- the token is 256 bits of `secrets.token_urlsafe` output, so there is no low-entropy
-- secret to slow an attacker down over, and bcrypt would be paid on every single request
-- rather than once per login. The plaintext is returned to the caller once, at signup or
-- login, and never again.

create table if not exists public.sessions (
    id uuid primary key default gen_random_uuid(),

    user_id uuid not null references public.users (id) on delete cascade,

    -- SHA-256 of the bearer token, hex encoded. Unique because a token identifies exactly
    -- one session, and a second row claiming the same one would leave every reader to pick.
    token_hash text not null,

    -- Which client this session was opened from, so the account page can label it. Free
    -- text constrained to the two surfaces that exist, rather than an enum, for the reason
    -- 0002_videos.sql gives for `source`: a third surface should not need a type change
    -- before it can sign in. The check is still worth having, because a typo here would
    -- show up as an unlabelled session rather than as an error.
    surface text not null,

    created_at timestamptz not null default now(),

    -- Bumped on every request the token authenticates, which is what the account page
    -- shows as "last used" and what an idle-session sweep would read.
    last_used_at timestamptz not null default now(),

    -- When this session stops being accepted. Written by whoever issues the token rather
    -- than defaulted here, so the lifetime stays a decision of `backend/core/` and is not
    -- silently duplicated in two places that could disagree.
    expires_at timestamptz not null,

    constraint sessions_token_hash_unique unique (token_hash),
    constraint sessions_surface_known check (surface in ('website', 'extension'))
);

comment on table public.sessions is
    'A durable signed-in session: the hashed bearer token, its account, its surface and its expiry.';

-- The account page's listing: this account's sessions, most recently used first.
create index if not exists sessions_user_last_used_idx
    on public.sessions (user_id, last_used_at desc);

-- What a sweep of expired sessions reads. Nothing prunes this table on a timer today --
-- verification already refuses an expired row -- but the rows accumulate, and deleting
-- them should not mean scanning every session ever issued.
create index if not exists sessions_expires_at_idx on public.sessions (expires_at);
