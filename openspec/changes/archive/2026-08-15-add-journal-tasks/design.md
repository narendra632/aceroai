## Context

Acero is a FastAPI backend (sync SQLAlchemy on Postgres 17 + pgvector, `openai` SDK
→ Gemini) and a React/Vite SPA, deployed on GCP + Vercel. Today the assistant only
**chats**: `handle_message` builds context (persona + recalled memory + last ~20
messages), streams tokens from the model, and persists the turn. The `tasks` and
`journal_entries` tables exist (Phase 0) but are unused — no API, no UI, and the
model has no way to act on them. This change adds the product surface **and** gives
the model the ability to operate that surface through **function-calling**, within
the same one-brain chat flow, on every channel.

## Goals / Non-Goals

**Goals:** a robust, mobile-first Tasks + Journal product; a shared service layer that
is the single source of truth for both the UI and the assistant; full assistant
control (create/read/update/complete) via a bounded, fault-tolerant tool-use loop
that keeps the "one brain" invariant; genuinely useful behavior, not features for
their own sake.

**Non-Goals (this change):** PWA packaging + push, semantic journal search, external/
MCP tools, recurring tasks / reminders, multi-user. (See proposal Non-goals.)

## Decisions

**1. One shared service layer; API and tools both call it.**
`services/tasks.py` and `services/journal.py` hold *all* create/read/update logic
(validation, status transitions, user scoping, derived urgency). `api/tasks.py` /
`api/journal.py` are thin HTTP wrappers; `core/tools.py` are thin tool wrappers. This
is the key robustness decision: task-creation logic exists in exactly one place, so
the UI and the assistant can never drift. *Alternative rejected:* tools call the REST
API over HTTP (needless self-request, auth juggling) or duplicate the logic.

**2. The tool-use loop lives in the one brain; channels stay thin.**
`handle_message` gains a bounded loop: build context **with tool definitions** →
ask the model → if it returns tool call(s), execute them via the services, append the
results to the running messages, and loop → when the model returns text instead, that
is the answer. Because this is in `core/`, web *and* Telegram get assistant task/
journal management for free (golden rule 1). The loop is **bounded** to
`settings.tools_max_iters` (default ~5) so it can never spin forever.

**3. Streaming + tools: stream normal turns; a tool turn shows a brief "working…"
then streams its answer.**
Normal chat (no tool call) must keep today's smooth token streaming. So the handler
streams the model's first response and inspects it: if it resolves to **text**, it has
already streamed to the user (unchanged behavior); if it resolves to **tool calls**
(`finish_reason == "tool_calls"`), the handler emits a `tool` SSE event (the UI shows
"working…"), runs the tools, appends results, and continues the loop — the eventual
text answer streams normally. Accumulating streamed `tool_call` fragments is the one
genuinely fiddly part. **Fallback if Gemini's OpenAI-compat endpoint streams tool
calls unreliably:** run tool-decision rounds **non-streamed** (`llm.complete(...,
tools=...)`) and stream only the final answer. We verify against the live endpoint
during apply and pick whichever is reliable; the user-visible contract is identical.

**4. Action policy — helpful, not presumptuous.**
Encoded in `SOUL.md` and enforced by tool design: the assistant **acts on clear
requests** ("add a task to…", "log that I…") and **offers on vague ones** ("I keep
forgetting X" → "want me to add that?") rather than silently writing. **Single
creates/updates apply immediately** (instantly visible + undoable in the UI);
**destructive or bulk actions** (delete, "clear all done") **confirm first**. This
keeps Narendra in control while still feeling like an assistant.

**5. Tools are user-scoped by construction.**
Every tool closes over the authenticated `user`; the model never supplies a `user_id`.
A tool can only ever read/write the current user's rows. Ids the model passes
(e.g. a task id to complete) are validated to belong to that user or the call fails
safely. This is the core data-safety guarantee.

**6. Fault-tolerant tool calls.**
Tool arguments are validated (Pydantic). A malformed call, an unknown id, or a service
error is returned to the model as a structured tool result describing the problem, so
the model self-corrects or tells the user plainly — a bad tool call never 500s the
chat turn. Combined with the iteration cap, the loop degrades gracefully.

**7. Derived urgency, never stored (honoring the schema's existing note).**
Read paths compute urgency from `due_at`, `priority`, and `snoozed_until` at read
time: overdue > due-soon > by priority; a task snoozed into the future sorts to the
bottom until `snoozed_until`. The API returns tasks in this order so the UI and the
assistant share one notion of "what's urgent."

**8. Journal shape.**
Entries are timestamped items carrying `entry_date`, `content`, optional `mood`
(1–5), `tags[]`, and `channel` (records origin: `web` / `telegram` / `assistant`).
Multiple entries per day are allowed. Semantic search (a pgvector embedding on
entries) is explicitly deferred to a later change.

**9. Frontend: a nav shell + mobile-first Tasks/Journal, reusing the design system.**
The app is chat-only today, so we add lightweight navigation (Chat / Tasks / Journal)
that collapses well on phones. Tasks: grouped/sorted by derived urgency, one-tap
complete, quick-add, an edit sheet for priority/due/notes. Journal: a dated timeline
with a composer (content + mood + tags). Same warm Claude-inspired tokens, tap targets
≥44px, no horizontal overflow, verified phone→desktop. Built PWA-ready; packaging is a
later step.

## Risks / Trade-offs

- **Streaming through tool calls is the main technical risk** → mitigated by the
  stream-then-inspect design with a documented non-streamed fallback (decision 3).
- **Gemini function-calling on the compat endpoint can be less crisp than native** →
  strict arg validation + self-correction + the iteration cap (decisions 5–6).
- **Extra model calls per tool turn cost more** → fine on the paid tier; acknowledged
  as heavy on the free ~20/day (this is why billing was enabled).
- **Over-eager assistant feels intrusive** → the offer-don't-impose policy
  (decision 4); tune the `SOUL.md` wording during apply.
- **Scope creep** → PWA/push, semantic journal, recurring tasks all explicitly
  deferred to keep this module robust *and* focused.

## Migration Plan

Additive and safe. **No DB schema change** — `tasks` and `journal_entries` already
exist; the journal embedding column stays deferred. New settings default to current
behavior. New API routes and frontend pages are purely additive; chat's existing
streaming contract is unchanged for non-tool turns. Rollback = revert the change; no
data migration to undo.

## Open Questions

- **Does Gemini stream `tool_call` fragments reliably** over the OpenAI-compat
  endpoint? Verified during apply; if not, use the non-streamed tool-round fallback
  (decision 3).
- **Exact confirmation boundary** — recommend: single create/update = immediate;
  delete + any bulk = confirm. Confirm with Narendra during review if he wants a
  tighter or looser line.
- **Action-policy wording** in `SOUL.md` — drafted during apply, easy to tune.
