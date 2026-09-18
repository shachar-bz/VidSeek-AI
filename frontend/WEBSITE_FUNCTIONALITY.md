# VidSeek Web App — Functionality Specification

This document defines what the VidSeek website does. It covers functionality only: no visual
design, no layout, no component choices. Where a feature depends on something the backend does
not have yet, that dependency is named explicitly rather than assumed.

The website is a companion to the existing Chrome extension, not a replacement for it. The
extension remains the only way a video enters the system.

Three parts:

- **Part 1 — Website functionality.** What a user can do, page by page.
- **Part 2 — Agent functionality.** The conversational agent, kept separate because it is built
  after the website.
- **Part 3 — What this requires.** The endpoints, tables and pipeline wiring each feature needs.

---

## Scope decisions

| Decision | Choice |
|---|---|
| Deployment | Hosted website + hosted API, reading the same Azure Postgres and Blob Storage the local companion writes to. The local companion stays for cookie-bound downloads. |
| Audience | Personal / internal tool. No quotas, no billing, no invites, no public onboarding. |
| Adding videos | Extension only. The website has no "add video" action. |
| Video ownership | Many-to-many. One video row can belong to several accounts. |
| Conversation scope | One video per conversation. |
| Conversation history | Persisted server-side, many per video, resumable. |
| Retrieval | Tools only. The agent never receives a raw transcript. |

---

# Part 1 — Website functionality

## 1. Shared concepts

### 1.1 Account

An account is an email, a password and a display name. It is the same account the Chrome
extension signs into: **one sign-in covers both surfaces**. Signing in on the website means the
extension is signed in, and signing out everywhere signs out both.

Sessions are durable — they survive an API restart, which is not true today.

### 1.2 Library link

A video exists once in the system. A user's library is a set of **links** to videos, and each
link carries that user's own metadata for the video:

- The user's custom title, if they renamed it.
- The user's tags.
- When the user added it.

Two users can link the same video. Neither can see the other's title, tags, conversations or
pinned answers, and neither's rename affects the other's view.

Removing a video from a library deletes **the link, and that user's conversations and pinned
answers for that video**. It does not delete the video, its transcript, its chapters, its
memories, its embeddings or its blob — those are shared, and they are kept so the video can be
re-linked later at no cost.

### 1.3 Readiness stages

A video appears in the library as soon as its job starts, and moves through four states. The
website shows the stage, not a raw percentage alone.

| Stage | What exists | What the website allows |
|---|---|---|
| `downloading` | Nothing yet | Title, source and progress only. |
| `transcribing` | Video blob is being produced or uploaded; transcript is being made | Nothing browsable yet. Progress only. |
| `understanding` | Video plays, transcript exists | **Player and transcript are usable.** Chapters, summary, takeaways and suggested questions are still being produced. Chat disabled. |
| `ready` | Everything above, plus chapters, memories, embeddings and generated insights | Everything, including chat. |

Two terminal states outside that sequence:

- `failed` — the job did not produce a usable video or transcript. The video stays in the
  library with the reason shown, and can be removed.
- `partial` — a transcript exists but is untimed (the pipeline's `untimed_transcript`
  outcome). The video is browsable and chat works, but timestamps are unreliable. See
  [Risk 3](#risk-3--untimed-transcripts-mis-seek).

**Chat is disabled before `ready`**, with a message naming the current stage and saying that
questions become available once the video is ready. This is not a soft preference: retrieval is
tools-only, and every retrieval tool except `get_video_info` returns nothing until memories,
chapters and embeddings exist.

---

## 2. Sign in / Sign up

The only pages a signed-out visitor can reach.

**Sign up** takes an email, a password and a display name, creates the account and signs the
user in. Duplicate emails are rejected with a clear message. Password length limits match the
backend's bcrypt bound.

**Sign in** takes an email and a password and returns a durable session.

Deliberately absent: email verification, and **password recovery of any kind**. A user who
forgets their password cannot reset it themselves; the account owner resets it directly against
the database. This is an accepted limitation of an internal tool and is listed in
[Out of scope](#out-of-scope).

After signing in, a user with an empty library lands on the library page and sees its empty
state (§3.1).

---

## 3. Library page

The home page for a signed-in user: every video linked to their account.

Each row shows the video's effective title (their custom title, else the captured title), its
source site, its duration, when they added it, its tags, its readiness stage, and whether it has
conversations.

### 3.1 Empty state

A user's library is empty on first sign-in, and the website cannot add anything to it. The empty
state therefore has to explain the way in: videos arrive through the Chrome extension, with a
link to install it and a one-line description of the flow. Without this, the app reads as broken
on first run.

A separate **setup page** (§6) holds the full instructions.

### 3.2 Videos still processing

Videos that are `downloading`, `transcribing` or `understanding` are listed alongside finished
ones, showing their stage and progress. Their rows **update live** without a manual refresh, and
flip to `ready` in place when they finish.

This is the only notification mechanism. There is no notification list, no browser push and no
email — a user who is not looking at the library page finds out next time they open it.

Live progress requires job state to live in the shared database rather than in the local
companion's memory; see §11.3.

### 3.3 Search and filter

- Text search over the effective title.
- Filter by tag, by source site, by readiness stage, by date added, and by whether the video has
  any conversations.
- Sort by date added and by duration.

This is metadata search only. Searching the *content* of videos is out of scope.

### 3.4 Rename and tag

A user can set their own title for a video, and manage their own tags on it. Both live on the
library link, so they are private to that user and never change what another user sees. Tags are
free text, created on first use, and offered as suggestions from the user's existing tags.

### 3.5 Remove from library

Removing a video drops the user's link, their conversations for it, and their pinned answers from
it. The video and everything derived from it survive.

The confirmation must state plainly what is and is not lost, because the asymmetry is surprising:
**re-adding the video later restores it instantly, but the conversation history is gone
permanently.**

---

## 4. Video page

Everything about one video, for one user.

### 4.1 Player

The video plays inline in the page. The bytes live in a private Azure container, so the page
plays it through a short-lived signed URL minted on demand by the API. That URL expires while a
long video is still playing, so the page refreshes it before expiry rather than letting playback
break.

If the blob is missing or unreadable, the page says the video file is unavailable and keeps the
transcript, chapters and conversations usable.

### 4.2 Transcript

The full transcript, in order, with timestamps.

- **Click a line to seek.** Any line jumps the player to that moment.
- **The line under the playhead is highlighted**, and the transcript follows playback.
- **Copy a line or a selected range**, with timestamps, for quoting elsewhere.

There is no keyword search inside the transcript. Finding things in a video is the agent's job.

### 4.3 Chapter outline

The video's chapters in order, each with its title, summary and time range. Clicking a chapter
seeks the player to its start.

Chapters do not exist for any video today — see
[Risk 1](#risk-1--the-understanding-stage-does-not-exist-yet).

### 4.4 Generated insights

Produced once when processing finishes and stored, so the page is useful before the user asks
anything:

- **A summary** of the video.
- **Key takeaways** as a short list.
- **Suggested questions** — a few starter questions derived from the video's chapters, each of
  which opens a new conversation pre-filled with that question.

These are static content on the page, not agent output. They are generated by the processing
pipeline, not on page load.

### 4.5 Conversations

A video page lists the user's conversations about that video, newest first, each with its title
and when it was last used. Opening one restores its full message history.

- **New conversation** starts a fresh context beside the existing ones. Nothing is lost; the
  agent simply starts with no memory of the other threads.
- **Auto-generated title** from the first exchange, so the list is readable.
- **Rename** a conversation.
- **Delete** a conversation. This permanently removes its messages **and any answers pinned from
  it**.

Conversations exist only on their video's page. There is no cross-video conversations view.

### 4.6 Pinned answers

Any agent answer can be pinned. A panel on the video page collects every answer the user pinned
about that video, each keeping its timestamp links and a way back to the conversation it came
from.

Pins are scoped to the video and to the user. Deleting the conversation an answer came from
removes the pin with it.

---

## 5. Account page

- Change display name.
- Change password, confirming the current one.
- **Sessions** — list the sessions signed into this account, labelled by surface (website,
  extension) and last-used time; revoke any one; sign out everywhere.
- **Delete account** — removes the user row, all their library links, all their conversations and
  all their pinned answers. Shared video data is untouched and stays available to other users.
  The confirmation states exactly that.

---

## 6. Setup page

Static instructions covering what a new user has to do outside the website: install the Chrome
extension, run the local companion, and sign in. This is the content currently spread across
`chrome-extension/README.md` and `backend/services/video_download/web/README.md`, written for
someone who has just created an account.

Reachable from the library's empty state and from the account area.

---

# Part 2 — Agent functionality

Built after the website. Until it exists, a `ready` video shows its player, transcript, chapters
and insights, and its conversation area says the agent is not available yet.

## 7. What a conversation is

One conversation belongs to one user and one video. Its context is its own message history and
nothing else — no other conversation, no other video. Starting a new conversation restarts the
agent's context from empty, which is the point of the feature.

## 8. Retrieval

**Tools only.** The agent is never given the raw transcript; it reaches the video's content
exclusively through the existing Pydantic AI tools in `backend/video_agent/tools/`:

| Tool | What it gives the agent |
|---|---|
| `get_video_info` | The video's metadata: source URL, title, transcript source and language. |
| `get_video_outline` | Every chapter in order — id, title, summary, time range — and nothing of what was said in them. |
| `memories_semantic_search` | The five moments closest in meaning to a query, each with its summary, text and time range. |
| `get_chapter_context` | One whole chapter: its title, summary, timing and every memory grouped into it. |
| `get_memory_context` | One memory with the memories around it inside its chapter, reporting each side where the window was clipped by a chapter boundary. |

Every tool is scoped to the conversation's video, so the agent cannot read another video's
content. The tools are already written and unit-tested; what does not exist is the agent itself,
its model choice, its system prompt and its runner.

Consequence of tools-only retrieval: an unsegmented video is invisible to the agent. This is why
chat is gated on `ready` rather than on the transcript.

## 9. Answering

While an answer is produced:

- **The answer streams** token by token rather than appearing after a silence.
- **A live trace shows what the agent is doing** — which tool it is calling, and with what — so a
  slow answer is legible and a retrieval miss is visible.
- **The answer can be stopped** mid-generation without losing the conversation.

The trace is stored with the message, so reopening a conversation shows how each answer was
reached.

## 10. Deliberately undecided

The **format of an answer** — whether every claim must carry a clickable timestamp, whether
sources are inline or listed, how citations render — is out of scope for this specification, and
will be decided when the agent is built.

---

# Part 3 — What this requires

The website is not a front end over an existing API. **No read API exists today**: there is no
endpoint that lists videos, returns a transcript, returns chapters, or produces a playable URL,
and there is no chat endpoint. Everything in Part 1 is new.

## 11. Data model changes

### 11.1 Durable sessions

Both bearer-token registries are in-process Python dictionaries today (`backend/core/auth.py`,
`backend/core/security.py`). They are lost on restart and cannot be validated by a second
process — so a hosted API and the local companion cannot recognise the same login.

Needed: a `sessions` table (or signed tokens verified against one) holding the token, its user,
its surface, its last-used time and its expiry. This is what makes "one sign-in covers both
surfaces", session listing and sign-out-everywhere possible.

### 11.2 Many-to-many library links

`videos.user_id` makes a video belong to exactly one account. Needed: a `user_videos` table keyed
on `(user_id, video_id)`, carrying `custom_title`, `tags` and `added_at`, with existing
`videos.user_id` values migrated into link rows and the column then dropped.

### 11.3 Persisted jobs

`JobManager` keeps jobs in an in-memory dict on a single worker, and never evicts them. A hosted
website cannot see them, and a restart loses them.

Needed: a `video_jobs` table the companion writes status, phase, progress, message and error code
to as it works, linked to the user who started it and to the resulting video. This is what the
library's live processing rows read, and it also fixes the unbounded in-memory dict.

### 11.4 Deduplication key

Needed: a normalized source URL column on `videos` with a unique index, alongside the existing
`source_video_id`, so that `youtu.be/X`, `watch?v=X` and the same URL with tracking parameters
all resolve to one video. On job creation the companion looks the video up first and, on a hit,
creates a library link and reports the job complete immediately — no download, no transcription,
no LLM cost.

### 11.5 Conversations

Needed: a `conversations` table (id, user, video, title, timestamps) and a `messages` table
(conversation, role, content, tool trace, timestamp), plus a `pinned_answers` table keyed to a
message and cascading with it.

### 11.6 Generated insights

Needed: storage for a video's summary, key takeaways and suggested questions. These are
properties of the shared video, not of a library link, so every user who links the video sees the
same ones.

## 12. Pipeline wiring

**`chapters`, `memories`, `memory_embeddings` and `chapter_embeddings` are empty in every
deployment, because nothing writes them.** The tables exist, the stores expose reads,
`backend/semantic_segmentation/` can produce memories and chapters, and
`backend/services/embeddings/` can embed them — but none of it is called from the request path.

Needed, in order:

1. `replace()` writers on the chapter and memory stores.
2. A call from `backend/services/video_download/video_record.py`, after the transcript is
   recorded: segment the transcript into memories, group memories into chapters, persist both.
3. Embed the memories and the chapters, and persist the vectors.
4. Generate and persist the summary, takeaways and suggested questions.
5. An approximate-nearest-neighbour index on both embedding columns. There is none today, so
   similarity search is a sequential scan filtered by video — acceptable while the tables are
   empty, not once they are not.

This is the `understanding` stage. Until it lands, no video can reach `ready`, which means the
chapter outline, the generated insights, the suggested questions and the entire agent are all
blocked behind it. **It is the largest prerequisite in this document.**

## 13. Endpoints

New surface the website needs. Paths are indicative.

**Auth and account**

- `POST /v1/auth/signup`, `POST /v1/auth/login`, `GET /v1/auth/me`, `POST /v1/auth/logout` —
  these exist, but must accept the website's origin and issue durable sessions.
- `GET /v1/auth/sessions`, `DELETE /v1/auth/sessions/{id}`, `POST /v1/auth/sessions/revoke-all`
- `PATCH /v1/account`, `POST /v1/account/password`, `DELETE /v1/account`

**Library**

- `GET /v1/library` — the user's videos, with search, filter, sort and pagination.
- `GET /v1/library/tags`
- `PATCH /v1/library/{video_id}` — custom title and tags.
- `DELETE /v1/library/{video_id}` — unlink, cascading the user's conversations and pins.
- A live channel for processing progress (server-sent events, or a status poll).

**Video**

- `GET /v1/videos/{id}` — metadata, readiness stage, summary, takeaways, suggested questions.
- `GET /v1/videos/{id}/playback` — a short-lived signed URL and its expiry.
- `GET /v1/videos/{id}/transcript`
- `GET /v1/videos/{id}/outline`
- `GET /v1/videos/{id}/pins`, plus `POST` and `DELETE` for a pin.

**Conversations**

- `GET` and `POST /v1/videos/{id}/conversations`
- `GET`, `PATCH`, `DELETE /v1/conversations/{id}`
- `POST /v1/conversations/{id}/messages` — streaming.
- `POST /v1/conversations/{id}/stop`

Every one of these must be scoped by the calling user. Nothing in the current storage layer
filters by user: `PostgresVideoRecords.recent()` and `find_by_source_url()` ignore `user_id`
entirely, the conversation tools are scoped only by video, and there is no row-level security. A
hosted multi-account API has to add that scoping at every read.

## 14. Deployment changes

- The API refuses any client that is not `127.0.0.1`, and CORS allows only `chrome-extension://`
  origins. A hosted website cannot call it at all. The hosted deployment drops the loopback gate
  and allows the website's origin; the local companion keeps both guards.
- Signup and login additionally check the `Origin` header against the extension allowlist. That
  check has to admit the website.
- The hosted API and the companion share a database and a session store; the companion keeps the
  filesystem download root and the heavy pipeline work.

---

## Out of scope

Named explicitly so they are not mistaken for oversights:

- Adding a video from the website — URLs, uploads, anything. Extension only.
- Password recovery, password reset and email verification. No email infrastructure at all.
- Semantic search across the whole library.
- Keyword search inside a transcript.
- YouTube comments on the video page, though the pipeline keeps collecting them.
- Notifications beyond the library page updating live: no notification list, no browser push, no
  email.
- Displaying whether the local companion is running.
- Conversation export.
- A cross-video conversations view, or a cross-video notes collection.
- Quotas, rate limits, billing, invites, teams, sharing.
- Answer formatting and citation rules (deferred to when the agent is built).

---

## Risks

### Risk 1 — the `understanding` stage does not exist yet

Chapters, memories, embeddings and generated insights are produced by no code path. The chapter
outline, the summary, the takeaways, the suggested questions and the whole agent depend on them.
Nothing that makes this app more than a video player with a transcript works until §12 lands.

### Risk 2 — remove and re-add is asymmetric

Removing a video and then adding it again returns the video instantly, and the conversation
history never. The data is intentionally kept on the video side and intentionally dropped on the
user side, so the loss is by design — but it is unrecoverable, and the confirmation has to say so.

### Risk 3 — untimed transcripts mis-seek

A video whose transcript came from an untimed source has no usable per-line timings. Click-to-seek
and any timestamp the agent produces will be wrong on it. The video page does not show timing
fidelity, so this failure is silent. Revisit if untimed transcripts turn out to be common.

### Risk 4 — one video at a time

The pipeline runs on a single worker in a single process. Several users adding videos at once
queue behind each other for minutes, and the library page will show a video sitting at
`downloading` with no indication that it is waiting rather than working. Deduplication (§11.4)
removes the repeat work, not the queue.
