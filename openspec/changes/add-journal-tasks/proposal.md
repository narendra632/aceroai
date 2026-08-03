## Why

The assistant can converse and remember Narendra, but it can't yet help him **act**
on his life. Two core surfaces of any personal assistant — **tasks** (what to do)
and a **journal** (what happened / how he felt) — have tables from Phase 0 but no
API, no UI, and no way for the assistant to touch them. This change turns them into
a real, **mobile-first** product surface, and takes the step up in capability that
makes Acero an *assistant* rather than a chatbot: it can **create, read, update, and
complete** tasks and journal entries from chat via **function-calling**, on web and
Telegram alike (the "one brain"). It is also the foundation for the later MCP module
— the same tool pattern, local tools first.

## What Changes

- **Shared service layer** (`services/tasks.py`, `services/journal.py`) — the single
  source of truth for task/journal logic. **Both** the REST API and the AI tools call
  it, so a task created by tapping "＋" and one created by the assistant are identical
  and validated the same way. No duplicated logic.
- **REST API**: user-scoped CRUD for tasks (`/api/tasks…`) and journal
  (`/api/journal…`), behind the existing auth.
- **Assistant tools** (`core/tools.py`) wired into `handle_message`:
  `create_task` / `list_tasks` / `update_task` / `complete_task`,
  `add_journal_entry` / `list_journal`. The model emits a tool call within a chat
  turn; the backend runs it through the service layer and feeds the result back (the
  **tool-use loop**). Because it lives in the one brain, it works on **web and
  Telegram** with no channel-specific code.
- **Action policy** (in `SOUL.md` + guardrails): the assistant **acts on clear
  requests, offers on vague ones**; **destructive / bulk actions confirm first**; the
  loop is **bounded** (max tool rounds) and **fault-tolerant** (a malformed or failed
  tool call is reported back to the model to self-correct, never crashes the turn);
  tools operate **only on the current user's data**.
- **Frontend**: a **mobile-first Tasks view** (quick-add, tap-to-complete, priority,
  due dates, sorted by *derived* urgency) and **Journal view** (dated entries, mood,
  tags), plus a simple **nav shell** between Chat / Tasks / Journal (the app is
  chat-only today). Great UX, thumb-friendly, PWA-*ready*; desktop stays first-class.
- Chat SSE stream gains a brief **"working…"** signal when a turn includes a tool step.

## Capabilities

### New Capabilities
- `tasks`: task lifecycle (todo/in_progress/done/dropped), read-time **derived
  urgency**, user-scoped REST CRUD, and assistant management via tools.
- `journal`: dated entries with optional mood and tags, user-scoped REST CRUD, and
  assistant journaling via tools.
- `assistant-tools`: the assistant takes actions within a single chat turn via
  function-calling — user-scoped, action/confirm policy, bounded, fault-tolerant,
  identical across web and Telegram.

### Modified Capabilities
<!-- Chat streaming keeps its contract (a turn may now include a tool step, captured
     under the new `assistant-tools` capability). No existing requirement changes. -->

## Impact

- **Backend:** new `services/{tasks,journal}.py`, `api/{tasks,journal}.py`,
  `core/tools.py`; `core/handler.handle_message` gains the bounded tool-use loop;
  additions to `api/schemas.py`. **No DB migration** — the `tasks` and
  `journal_entries` tables already exist (journal pgvector embedding stays deferred).
- **Frontend:** new Tasks + Journal pages/components, a nav shell, and api-client
  methods; reuses the existing Claude-inspired design system.
- **Config / persona:** a small `tools_max_iters` guardrail setting; the action-policy
  wording lives in `SOUL.md`.
- **Cost:** tool turns add model calls per message — fine on the paid tier, heavy on
  the free ~20/day.
- **Testing:** services, REST CRUD, and the tool loop (fake LLM emitting tool calls),
  including guardrails (user scoping, bounded iterations, failed-call recovery).
- **Dependencies:** none expected — the `openai` SDK already supports `tools`. Ask
  before adding any.

## Non-goals (this change)

- **PWA packaging + push notifications** — mobile-first UI now; installable/offline +
  web-push is a dedicated follow-up (push pairs naturally with the day-end scheduler).
- **Semantic journal search** (pgvector embedding on journal entries) — deferred.
- **External/MCP tools** — only local tasks/journal tools here; MCP is a later module.
- **Recurring tasks, reminders/notifications, sub-tasks, shared/multi-user** — later.
