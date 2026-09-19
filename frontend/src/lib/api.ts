// Single place that talks to the backend. Every call sends the auth cookie
// (`credentials: "include"`). Chat streams over SSE, consumed with fetch +
// a body reader because EventSource cannot POST or send cookies cleanly.

const API = import.meta.env.VITE_API_URL as string;

// The auth token is stored client-side and sent as an Authorization header. This
// works cross-site in every browser (a cross-site cookie is blocked by browser
// privacy protections when the frontend and API are on different domains).
const TOKEN_KEY = "aceroai_token";
export const getToken = (): string | null => localStorage.getItem(TOKEN_KEY);
const setToken = (t: string | null) =>
  t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY);

function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export type Session = {
  id: string;
  title: string | null;
  channel: string;
  last_active_at: string;
};

export type ChatMessage = {
  id: string;
  role: string;
  content: string;
  created_at: string;
};

export type ChatEvent = { event: string; data: string };

/** One fact recall injected into the prompt for a reply.
 *
 * `via` says WHICH search found it: "both" means the meaning search and the keyword search
 * agreed, which is the strongest signal the system has; "vector" and "lexical" mean only
 * one of them did. Shown because a memory you cannot inspect is a memory you cannot trust
 * — this whole feature exists because a fact was silently missing and there was no way to
 * notice. */
export type RecalledFact = {
  id: string;
  fact: string;
  category: FactCategory;
  via: "both" | "vector" | "lexical";
};

function req(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${API}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init.headers ?? {}),
    },
  });
}

export async function me(): Promise<string | null> {
  const r = await req("/api/auth/me");
  return r.ok ? (await r.json()).email : null;
}

export async function login(email: string, password: string): Promise<string> {
  const r = await req("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  if (!r.ok) throw new Error("Invalid email or password");
  const data = await r.json();
  setToken(data.token);
  return data.email;
}

export async function logout(): Promise<void> {
  await req("/api/auth/logout", { method: "POST" });
  setToken(null);
}

export async function listSessions(): Promise<Session[]> {
  const r = await req("/api/chat/sessions");
  return r.ok ? r.json() : [];
}

export async function getMessages(sessionId: string): Promise<ChatMessage[]> {
  const r = await req(`/api/chat/sessions/${sessionId}/messages`);
  return r.ok ? r.json() : [];
}

export async function deleteSession(sessionId: string): Promise<void> {
  const r = await req(`/api/chat/sessions/${sessionId}`, { method: "DELETE" });
  if (!r.ok) throw new Error("could not delete the conversation");
}

/** Undo a delete. The conversation and its messages come back unchanged. */
export async function restoreSession(sessionId: string): Promise<Session> {
  const r = await req(`/api/chat/sessions/${sessionId}/restore`, {
    method: "POST",
  });
  if (!r.ok) throw new Error("could not restore the conversation");
  return r.json();
}

export async function renameSession(
  sessionId: string,
  title: string,
): Promise<Session> {
  const r = await req(`/api/chat/sessions/${sessionId}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
  if (!r.ok) throw new Error("could not rename the conversation");
  return r.json();
}

/** Drop the trailing assistant reply so the turn can be sent again. */
export async function regenerate(sessionId: string): Promise<void> {
  const r = await req(`/api/chat/sessions/${sessionId}/regenerate`, {
    method: "POST",
  });
  if (!r.ok) throw new Error("could not regenerate");
}

// --- tasks ---

export type Task = {
  id: string;
  title: string;
  notes: string | null;
  status: "todo" | "in_progress" | "done" | "dropped";
  priority: number; // 1 high · 2 mid · 3 low
  due_at: string | null;
  snoozed_until: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type TaskInput = {
  title: string;
  notes?: string | null;
  priority?: number;
  due_at?: string | null;
};

export async function listTasks(status?: string): Promise<Task[]> {
  const r = await req(`/api/tasks${status ? `?status=${status}` : ""}`);
  // Throw rather than return [] — "we couldn't load this" and "you have nothing"
  // must never look the same to the user.
  if (!r.ok) throw new Error("could not load tasks");
  return r.json();
}

export async function createTask(input: TaskInput): Promise<Task> {
  const r = await req("/api/tasks", {
    method: "POST",
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error("could not create task");
  return r.json();
}

export async function updateTask(
  id: string,
  patch: Partial<Task>,
): Promise<Task> {
  const r = await req(`/api/tasks/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error("could not update task");
  return r.json();
}

export async function completeTask(id: string): Promise<Task> {
  const r = await req(`/api/tasks/${id}/complete`, { method: "POST" });
  if (!r.ok) throw new Error("could not complete task");
  return r.json();
}

export async function deleteTask(id: string): Promise<void> {
  const r = await req(`/api/tasks/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error("could not delete the task");
}

/** Undo a delete. The task returns with the same id, so anything referring to it
 *  — including the assistant — still points at the same thing. */
export async function restoreTask(id: string): Promise<Task> {
  const r = await req(`/api/tasks/${id}/restore`, { method: "POST" });
  if (!r.ok) throw new Error("could not restore the task");
  return r.json();
}

// --- journal ---

export type JournalEntry = {
  id: string;
  entry_date: string;
  content: string;
  mood: number | null;
  tags: string[];
  channel: string;
  created_at: string;
};

export type JournalInput = {
  content: string;
  mood?: number | null;
  tags?: string[];
};

export type JournalQuery = { q?: string; limit?: number; offset?: number };

export async function listJournal(
  query: JournalQuery = {},
): Promise<JournalEntry[]> {
  const params = new URLSearchParams();
  if (query.q) params.set("q", query.q);
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  if (query.offset) params.set("offset", String(query.offset));
  const qs = params.toString();
  const r = await req(`/api/journal${qs ? `?${qs}` : ""}`);
  // Throw rather than return [] — a failed load must not be indistinguishable
  // from an empty journal.
  if (!r.ok) throw new Error("could not load the journal");
  return r.json();
}

export async function updateJournalEntry(
  id: string,
  patch: Partial<JournalInput>,
): Promise<JournalEntry> {
  const r = await req(`/api/journal/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error("could not update the entry");
  return r.json();
}

/** Undo a delete. The entry returns with the same id and its original date. */
export async function restoreJournalEntry(id: string): Promise<JournalEntry> {
  const r = await req(`/api/journal/${id}/restore`, { method: "POST" });
  if (!r.ok) throw new Error("could not restore the entry");
  return r.json();
}

export async function addJournalEntry(
  input: JournalInput,
): Promise<JournalEntry> {
  const r = await req("/api/journal", {
    method: "POST",
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error("could not add entry");
  return r.json();
}

export async function deleteJournalEntry(id: string): Promise<void> {
  const r = await req(`/api/journal/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error("could not delete the entry");
}

// --- settings (provider + models) ---

export type EmbeddingInfo = {
  provider: string;
  model: string;
  dimensions: number;
  pinned: boolean;
  note: string;
};

export type BudgetStatus = {
  /** null = no limit set. Everything else is still reported, so the UI can show what a
   *  month costs before asking you to pick a ceiling. */
  limit_usd: string | null;
  spent_usd: string;
  remaining_usd: string | null;
  used_ratio: number;
  state: "off" | "ok" | "warning" | "exceeded";
  resets_on: string;
  warn_ratio: number;
};

export type Settings = {
  provider: string;
  model_chat: string;
  model_deep: string;
  available_providers: string[];
  model_catalog: Record<string, string[]>;
  /** "provider/model" entries with no reasoning control — picking one for Deep means the
   *  "think harder" toggle changes nothing. */
  no_reasoning_control: string[];
  defaults: Record<string, string>;
  embedding: EmbeddingInfo;
  budget: BudgetStatus;
};

export type SettingsUpdate = {
  provider?: string;
  model_chat?: string;
  model_deep?: string;
  monthly_budget_usd?: string;
  /** Turning a limit off, which an omitted `monthly_budget_usd` cannot express. */
  clear_budget?: boolean;
};

/** Just the spend state — re-read after every turn, so it skips the model catalogue. */
export async function getBudget(): Promise<BudgetStatus> {
  const r = await req("/api/settings/budget");
  if (!r.ok) throw new Error("could not load budget");
  return r.json();
}

export async function getSettings(): Promise<Settings> {
  const r = await req("/api/settings");
  if (!r.ok) throw new Error("could not load settings");
  return r.json();
}

export async function updateSettings(patch: SettingsUpdate): Promise<Settings> {
  const r = await req("/api/settings", {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => null);
    throw new Error(detail?.detail ?? "could not save settings");
  }
  return r.json();
}

function parseFrame(frame: string): ChatEvent | null {
  let event: string | null = null;
  const dataParts: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      let chunk = line.slice(5);
      if (chunk.startsWith(" ")) chunk = chunk.slice(1);
      dataParts.push(chunk);
    }
  }
  return event ? { event, data: dataParts.join("\n") } : null;
}

export async function* streamChat(
  message: string,
  sessionId: string | null,
  signal?: AbortSignal,
  deep = false,
): AsyncGenerator<ChatEvent> {
  const res = await fetch(`${API}/api/chat`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    // `deep` = explicit "think harder": ask the backend for deeper reasoning.
    body: JSON.stringify({ message, session_id: sessionId, deep }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error("chat request failed");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const ev = parseFrame(frame);
      if (ev) yield ev;
    }
  }
}

// --- memory / knowledge graph ---

export type FactCategory =
  "preference" | "health" | "work" | "finance" | "relationship" | "other";

export type Fact = {
  id: string;
  fact: string;
  category: FactCategory;
  confidence: number;
  /** "inferred" = the assistant concluded it; "stated" = you confirmed it. */
  source: "inferred" | "stated";
  status: "active" | "superseded" | "rejected";
  superseded_by: string | null;
  /** Set when this fact was kept despite closely resembling another one. */
  possible_duplicate_of: string | null;
  valid_from: string;
  created_at: string;
  updated_at: string;
};

export type FactDetail = Fact & {
  /** The conversation this was learned from, when it came from one. */
  source_session_id: string | null;
  /** The belief this one replaced, so history is reachable and not merely stored. */
  previous: Fact | null;
  /** The fact this one may be repeating. A QUESTION, not a verdict — the alternative was
   *  deleting it, and closeness in meaning cannot tell a restatement from two genuinely
   *  different facts that happen to sound alike. */
  resembles: Fact | null;
};

export type GraphNode = {
  id: string;
  fact: string;
  category: FactCategory;
  confidence: number;
  source: "inferred" | "stated";
  valid_from: string;
};

/** Cosine distance: 0 = same meaning, 1 = unrelated. Never carries the vectors. */
export type GraphEdge = { source: string; target: string; distance: number };

export type Graph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** True when more facts exist than the graph draws — never truncate silently. */
  truncated: boolean;
  total: number;
  /** How many the graph will draw, sent so the UI never hard-codes a stale copy. */
  render_limit: number;
  /** Set once the memory nears that ceiling: time to move the layout to Barnes-Hut. */
  needs_faster_layout: boolean;
};

export type MemoryStats = {
  total: number;
  by_category: Record<string, number>;
  by_source: Record<string, number>;
  by_status: Record<string, number>;
  per_day: { day: string; count: number }[];
};

export type FactQuery = {
  category?: string;
  status?: string;
  source?: string;
  min_confidence?: number;
  q?: string;
  limit?: number;
  offset?: number;
};

/** One page of the fact list. Matches the server default; a page is a scrolling
 *  decision, unrelated to what the graph can draw. */
export const FACT_PAGE_SIZE = 100;

function qs(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") search.set(k, String(v));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
}

export async function listFacts(query: FactQuery = {}): Promise<Fact[]> {
  const r = await req(`/api/memory/facts${qs(query)}`);
  if (!r.ok) throw new Error("Could not load what Acero has learned");
  return r.json();
}

export async function getFact(id: string): Promise<FactDetail> {
  const r = await req(`/api/memory/facts/${id}`);
  if (!r.ok) throw new Error("Could not load that fact");
  return r.json();
}

export async function getGraph(maxDistance?: number): Promise<Graph> {
  const r = await req(`/api/memory/graph${qs({ max_distance: maxDistance })}`);
  if (!r.ok) throw new Error("Could not load the knowledge graph");
  return r.json();
}

export async function getMemoryStats(): Promise<MemoryStats> {
  const r = await req("/api/memory/stats");
  if (!r.ok) throw new Error("Could not load memory stats");
  return r.json();
}

export async function updateFact(
  id: string,
  patch: { fact?: string; category?: string; confidence?: number },
): Promise<Fact> {
  const r = await req(`/api/memory/facts/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  if (!r.ok) {
    // 503 means the re-index failed, so nothing was saved — say that rather than
    // leaving the user thinking an edit landed when it didn't.
    const msg =
      r.status === 503
        ? "Couldn't save that edit — the search index was unreachable. Try again shortly."
        : "Could not save that change";
    throw new Error(msg);
  }
  return r.json();
}

/** Confirming is a toggle: one click in, one click out, so a misclick isn't permanent. */
export async function setFactConfirmed(
  id: string,
  confirmed: boolean,
): Promise<Fact> {
  const path = confirmed ? "confirm" : "unconfirm";
  const r = await req(`/api/memory/facts/${id}/${path}`, { method: "POST" });
  if (!r.ok)
    throw new Error(
      confirmed ? "Could not confirm that fact" : "Could not undo that",
    );
  return r.json();
}

export async function forgetFact(id: string): Promise<void> {
  const r = await req(`/api/memory/facts/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error("Could not forget that fact");
}

/** Answer the duplicate question with "these are genuinely different".
 *
 * A warning with no way to dismiss it becomes permanent furniture. Merging is the other
 * answer, and that is just forgetting the one you don't want. */
export async function notDuplicate(id: string): Promise<Fact> {
  const r = await req(`/api/memory/facts/${id}/not-duplicate`, {
    method: "POST",
  });
  if (!r.ok) throw new Error("Could not clear that flag");
  return r.json();
}

export async function restoreFact(id: string): Promise<Fact> {
  const r = await req(`/api/memory/facts/${id}/restore`, { method: "POST" });
  if (!r.ok) throw new Error("Could not restore that fact");
  return r.json();
}

// --- insights (read-only) ---

export type InsightsSummary = {
  calls: number;
  cost_usd: string;
  tokens_in: number;
  tokens_out: number;
  tokens_thinking: number;
  failed: number;
  error_rate: number;
  /** Percentiles, never a mean — one slow turn would hide the typical one. */
  p50_ms: number | null;
  p95_ms: number | null;
  p50_ttft_ms: number | null;
  /** Calls whose model had no known price, so a total can admit its gaps. */
  unpriced: number;
};

export type TurnKind = "chat" | "embed" | "memory_extract" | "job";

export type SeriesPoint = {
  day: string;
  kind: TurnKind;
  calls: number;
  cost_usd: string;
};

export type ModelUsage = {
  provider: string | null;
  model: string | null;
  calls: number;
  cost_usd: string;
  tokens_in: number;
  tokens_out: number;
  /** The embedding model, which is not selectable. */
  pinned: boolean;
};

export type ProviderComparison = {
  provider: string | null;
  calls: number;
  cost_usd: string;
  cost_per_call: string;
  p50_ms: number | null;
  p50_ttft_ms: number | null;
  error_rate: number;
};

export type TurnRow = {
  id: string;
  kind: TurnKind;
  provider: string | null;
  model: string | null;
  effort: string | null;
  session_id: string | null;
  started_at: string;
  duration_ms: number | null;
  ttft_ms: number | null;
  rounds: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  tokens_thinking: number | null;
  tokens_cached: number | null;
  cost_usd: string | null;
  pricing_version: string | null;
  ok: boolean;
  error_type: string | null;
};

export type TurnSpan = {
  name: string;
  seq: number;
  duration_ms: number | null;
  meta: Record<string, unknown> | null;
};

export type InsightsOverview = {
  summary: InsightsSummary;
  series: SeriesPoint[];
  by_model: ModelUsage[];
  by_provider: ProviderComparison[];
  errors: { error_type: string; count: number }[];
  /** When recording began — the page states this so it never implies a longer history. */
  data_start: string | null;
  pricing_version: string;
};

export async function getInsights(range: {
  days?: number;
  allTime?: boolean;
}): Promise<InsightsOverview> {
  const r = await req(
    `/api/insights/overview${qs({
      days: range.allTime ? undefined : (range.days ?? 30),
      all_time: range.allTime ? "true" : undefined,
    })}`,
  );
  if (!r.ok) throw new Error("Could not load your usage");
  return r.json();
}

export async function listTurns(limit = 50, kind?: string): Promise<TurnRow[]> {
  const r = await req(`/api/insights/turns${qs({ limit, kind })}`);
  if (!r.ok) throw new Error("Could not load recent activity");
  return r.json();
}

/** What memory contributed to one past turn.
 *
 * The chat popover can only explain the conversation still open in the browser; this
 * answers the same question for any turn ever recorded. Resolved server-side from the ids
 * on the span, so traces still hold no message text. */
export type TurnDetail = {
  turn: TurnRow;
  spans: TurnSpan[];
  recalled: { id: string; fact: string; category: FactCategory }[];
};

export async function getTurn(id: string): Promise<TurnDetail> {
  const r = await req(`/api/insights/turns/${id}`);
  if (!r.ok) throw new Error("Could not load that call");
  return r.json();
}

// --- learn (read-only, derived from settings) ---

/** The tuning values the Learn section quotes.
 *
 * Fetched rather than hardcoded, because a number written into a sentence is correct on
 * the day and wrong later. `memory_recall_k` moved 12 -> 16 in a single commit; anything
 * that had typed "12" would already have been teaching something false. */
export type LearnConstants = {
  recall_k: number;
  recall_pool: number;
  rrf_k: number;
  vector_only_max: number;
  lexical_only_max: number;
  lexical_terms_max: number;
  lexical_max_df: number;
  lexical_rare_df: number;
  vector_only_max_distance: number;
  consensus_max_distance: number;
  memory_recall_timeout_s: number;
  memory_dedup_distance: number;
  embed_dim: number;
  history_limit: number;
  context_tasks_limit: number;
  tools_max_iters: number;
  tool_count: number;
  max_input_chars: number;
  graph_limit: number;
  graph_warn_at: number;
  graph_neighbours: number;
  graph_max_distance: number;
  span_retention_days: number;
  turn_retention_days: number;
  job_count: number;
  job_tick_seconds: number;
  job_catch_up_hours: number;
  notification_retention_days: number;
  quiet_hours_start: number;
  quiet_hours_end: number;
  push_ttl_digest_s: number;
  push_ttl_nudge_s: number;
  push_payload_max_bytes: number;
};

export async function getLearnConstants(): Promise<LearnConstants> {
  const r = await req("/api/learn/constants");
  if (!r.ok) throw new Error("Could not load the current settings");
  return r.json();
}

// --- notifications, jobs and briefings (migration 011) ---

/** Something Acero decided to tell you.
 *
 * `pushed_at` being null is information, not a gap: it means the notification was recorded
 * but never reached a device — quiet hours, the daily cap, no subscription, or a send that
 * failed. The record exists either way, which is the whole point of storing before
 * delivering. */
export type NotificationRow = {
  id: string;
  kind: string;
  title: string;
  body: string;
  url: string | null;
  tag: string | null;
  /** When the situation BEGAN, not when it was last mentioned. An overdue task that has been
   *  reminded about all day still reads "10:03 AM", which is the useful fact. */
  created_at: string;
  read_at: string | null;
  /** When it was LAST delivered (migration 013). */
  pushed_at: string | null;
  /** How many times this record reached a device. Greater than 1 for a reminder that repeats
   *  until acted on — the overdue nudge buzzes every two hours against one record rather than
   *  writing seven near-identical rows a day. */
  push_count: number;
};

export async function listNotifications(): Promise<{
  items: NotificationRow[];
  unread: number;
}> {
  const r = await req("/api/notifications");
  if (!r.ok) throw new Error("Could not load notifications");
  return r.json();
}

export async function unreadCount(): Promise<number> {
  const r = await req("/api/notifications/unread");
  if (!r.ok) return 0;
  return (await r.json()).unread ?? 0;
}

export async function markNotificationRead(id: string): Promise<void> {
  await req(`/api/notifications/${id}/read`, { method: "POST" });
}

export async function markAllNotificationsRead(): Promise<void> {
  await req("/api/notifications/read-all", { method: "POST" });
}

/* Removal.
 *
 * Soft on the server and undoable for the length of a toast, exactly as tasks and journal
 * entries are. What removal deliberately does NOT do is rewrite history: the nudge behind a
 * dismissed notification stays suppressed, and the day's delivered count is unchanged. See
 * docs/NOTIFICATIONS.md. */

export async function deleteNotification(id: string): Promise<void> {
  const r = await req(`/api/notifications/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error("Could not remove that notification");
}

export async function restoreNotification(id: string): Promise<void> {
  const r = await req(`/api/notifications/${id}/restore`, { method: "POST" });
  if (!r.ok) throw new Error("Could not restore that notification");
}

/** Clear everything already read, and get back exactly which ids went.
 *
 * The ids are what makes the undo correct. Restoring "everything read" would also
 * resurrect anything marked read between the clear and the undo — rows the user never
 * deleted. */
export async function clearReadNotifications(): Promise<string[]> {
  const r = await req("/api/notifications/clear-read", { method: "POST" });
  if (!r.ok) throw new Error("Could not clear those notifications");
  return (await r.json()).ids ?? [];
}

export async function restoreNotifications(ids: string[]): Promise<void> {
  const r = await req("/api/notifications/restore", {
    method: "POST",
    body: JSON.stringify({ ids }),
  });
  if (!r.ok) throw new Error("Could not restore those notifications");
}

/** What this server can do about push, and what this account has registered.
 *
 * `public_key` is a VAPID *public* key — public by design, and required by the browser to
 * subscribe. The private half never leaves the server. */
export type PushStatus = {
  configured: boolean;
  public_key: string;
  devices: number;
  quiet_hours_start: number | null;
  quiet_hours_end: number | null;
  /** 0 (and the default) means no ceiling. Kept as an escape hatch for a looping job,
   *  not as a product feature — volume is governed by repetition suppression instead. */
  daily_push_cap: number | null;
  /** How many reached a device today. A readout, not a limit — and counted from what was
   *  DELIVERED, so clearing the panel does not reset it. */
  pushed_today: number;
};

export async function getPushStatus(): Promise<PushStatus> {
  const r = await req("/api/notifications/push");
  if (!r.ok) throw new Error("Could not load notification settings");
  return r.json();
}

export async function subscribePush(sub: {
  endpoint: string;
  p256dh: string;
  auth: string;
}): Promise<void> {
  const r = await req("/api/notifications/push", {
    method: "POST",
    body: JSON.stringify(sub),
  });
  if (!r.ok) throw new Error("Could not register this device");
}

export async function unsubscribePush(endpoint: string): Promise<void> {
  await req(
    `/api/notifications/push?endpoint=${encodeURIComponent(endpoint)}`,
    {
      method: "DELETE",
    },
  );
}

/** Provoke a notification on demand.
 *
 * Returns a reason rather than throwing, because every way this can fail is something the
 * user can act on: no keys on the server, no device subscribed, or a device that refused. */
export async function sendTestNotification(): Promise<{
  ok: boolean;
  reason?: string;
}> {
  const r = await req("/api/notifications/push/test", { method: "POST" });
  if (!r.ok) return { ok: false, reason: "The request failed." };
  return r.json();
}

/** One thing Acero does on a schedule. `schedule` is the cron expression (the truth);
 *  `when` is the same thing phrased for a person, rendered server-side so there is one
 *  implementation rather than a second one here that can drift. */
export type JobRow = {
  name: string;
  description: string;
  schedule: string;
  when: string;
  uses_ai: boolean;
  default_on: boolean;
  enabled: boolean;
  last_run_at: string | null;
  last_status: string | null;
};

export async function listJobs(): Promise<JobRow[]> {
  const r = await req("/api/jobs");
  if (!r.ok) throw new Error("Could not load scheduled work");
  return r.json();
}

export async function setJobEnabled(
  name: string,
  enabled: boolean,
): Promise<JobRow> {
  const r = await req(`/api/jobs/${encodeURIComponent(name)}`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
  if (!r.ok) throw new Error("Could not change that setting");
  return r.json();
}

/** A briefing Acero wrote about a day. Read-only: editing one would make it a note the
 *  user wrote, which is what the journal is already for. */
export type Briefing = {
  id: string;
  kind: string;
  content: string;
  period_start: string;
  period_end: string;
  created_at: string;
};

export async function listBriefings(): Promise<Briefing[]> {
  const r = await req("/api/journal/briefings");
  if (!r.ok) throw new Error("Could not load briefings");
  return r.json();
}

export async function deleteBriefing(id: string): Promise<void> {
  const r = await req(`/api/journal/briefings/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error("Could not remove that briefing");
}

/** Undo. Note that deleting a briefing never causes it to be written again — `job_runs`
 *  records what has run, and the briefing is only that job's output. */
export async function restoreBriefing(id: string): Promise<void> {
  const r = await req(`/api/journal/briefings/${id}/restore`, {
    method: "POST",
  });
  if (!r.ok) throw new Error("Could not restore that briefing");
}

// --- server vital signs (migration 012) ---

export type Capacity = {
  used_bytes: number;
  total_bytes: number;
  percent: number;
};

/** What the machine is doing right now.
 *
 * Every measurement is nullable, and that is deliberate rather than defensive. `/proc` does
 * not exist on Windows, so on a development machine `memory` and `load_1m` are genuinely
 * absent — and the interface omits them rather than drawing a zero, because a zero is a
 * wrong answer wearing the same confidence as a right one.
 *
 * `last_tick` null means "the server process has not ticked yet", which is true for up to
 * one interval after a restart. Read it together with `uptime_seconds`: that pair is what
 * separates "just booted" from "the scheduler has stopped". */
export type Vitals = {
  disk: Capacity | null;
  memory: Capacity | null;
  load_1m: number | null;
  database_bytes: number | null;
  last_tick: string | null;
  uptime_seconds: number;
  tick_interval_seconds: number;
  disk_warn_percent: number;
};

export async function getVitals(): Promise<Vitals> {
  const r = await req("/api/insights/vitals");
  if (!r.ok) throw new Error("Could not read the server's condition");
  return r.json();
}

// --- investments ---
//
// ⚠ Every money field below is typed `string`, and that is deliberate rather than lazy. The
// server computes each figure in exact decimal and serialises it as a quoted string; typing
// it as `number` here would invite a component to add two of them, which is float arithmetic
// on money. If something needs to be summed, it is summed on the server.

/** A ratio, not a percentage: "0.0734" means 7.34%. Format with `formatSignedPct`. */
export type Ratio = string;

export type Mark = {
  price: string;
  currency: string;
  observed_at: string;
  source: string;
  age_text: string;
  is_stale: boolean;
};

export type SuspiciousMove = {
  on: string;
  previous: string;
  current: string;
  change: Ratio;
  gap_days: number;
  direction: "rose" | "fell";
};

export type AssetClass = "EQUITY_IN" | "EQUITY_US" | "MF_IN" | "CRYPTO";

export type Holding = {
  instrument_id: string;
  symbol: string;
  name: string;
  asset_class: AssetClass;
  currency: string;
  quantity: string;
  average_cost: string | null;
  cost_basis: string;
  cost_basis_inr: string;
  realised_inr: string;
  charges_inr: string;
  prepaid_tax_inr: string;
  /** null means "not known" — never zero, and never a stale figure shown as current. */
  market_value_inr: string | null;
  unrealised_inr: string | null;
  unrealised_pct: Ratio | null;
  mark: Mark | null;
  days_to_long_term: number | null;
  losses_ring_fenced: boolean;
  suspicious_move: SuspiciousMove | null;
  lots: number;
};

export type Totals = {
  /** ⚠ What every holding cost — what a person means by "invested". Exact whether or not
   *  anything has a price. Use THIS for a headline, never `invested_inr`. */
  cost_basis_inr: string;
  /** Cost of the priced, non-ring-fenced holdings only, so it stays comparable with
   *  `market_value_inr`. **Zero on a book with no prices** — never label it "Invested". */
  invested_inr: string;
  market_value_inr: string;
  unrealised_inr: string;
  unrealised_pct: Ratio | null;
  realised_inr: string;
  /** Crypto, kept apart: under s.115BBH its losses offset nothing, ever. */
  ring_fenced_inr: string;
  /** Named, never counted — render these beside the total they are missing from. */
  unpriced: string[];
  stale: string[];
  is_complete: boolean;
};

export type PortfolioReturn = {
  kind: "money_weighted" | "time_weighted";
  label: string;
  measures: string;
  value: Ratio | null;
  /** Present exactly when `value` is null. Show it — never hide the measure. */
  unavailable_because: string | null;
  covers_from: string | null;
  covers_to: string | null;
};

/** A subtotal, computed on the server. ⚠ Never sum holdings in the browser to get one:
 *  that is float arithmetic on money, right after the server took care to be exact. */
export type AssetTotal = {
  asset_class: AssetClass;
  holdings: number;
  invested_inr: string;
  /** null when any holding in the class has no price — the same rule as the book total. */
  market_value_inr: string | null;
};

export type InvestmentSummary = {
  portfolio_id: string;
  name: string;
  kind: string;
  as_of: string;
  holdings: Holding[];
  totals: Totals;
  by_asset_class: AssetTotal[];
  unpriced_cost_inr: string;
  returns: PortfolioReturn[];
};

export type Lot = {
  trade_date: string;
  quantity: string;
  unit_cost: string;
  fx_rate_inr: string;
  cost_inr: string;
  days_held: number;
  long_term_on: string | null;
  is_long_term: boolean;
  days_remaining: number | null;
};

export type IfSoldNow = {
  at_price: string;
  quantity: string;
  realised_inr: string;
  long_term_inr: string;
  short_term_inr: string;
  weighted_average_realised_inr: string;
  /** True on a full disposal, where both bases relieve the whole cost basis and agree. */
  bases_agree: boolean;
};

export type CurrencySplit = { local: Ratio; fx: Ratio; total_inr: Ratio };

export type InvestmentTransaction = {
  id: string;
  instrument_id: string;
  symbol: string;
  txn_type: string;
  trade_date: string;
  quantity: string;
  price: string;
  currency: string;
  fx_rate_inr: string | null;
  charges_inr: string;
  prepaid_tax_inr: string;
  net_inr: string;
  entry_source: string;
  note: string | null;
  created_at: string;
  supersedes_id: string | null;
  /** Set when a later entry replaced this one. The row stays visible, marked. */
  superseded_by_id: string | null;
};

export type Observation = {
  observed_at: string;
  price: string;
  currency: string;
  source: string;
  quality: string;
};

export type HoldingDetail = {
  holding: Holding;
  lots: Lot[];
  if_sold_now: IfSoldNow | null;
  currency_split: CurrencySplit | null;
  transactions: InvestmentTransaction[];
  observations: Observation[];
  moves: SuspiciousMove[];
};

export type CurvePoint = {
  day: string;
  invested_inr: string;
  /** null wherever a price was missing for any open holding. Never interpolate it. */
  value_inr: string | null;
  priced: number;
  open_holdings: number;
};

export type Curve = {
  points: CurvePoint[];
  covered_from: string | null;
  covered_to: string | null;
  /** ⚠ How many days actually carry a value, against how many are plotted. First-and-last
   *  is not enough: coverage can have a hole in the middle, and "covered from X to Y" would
   *  then claim a continuity the data does not have. */
  covered_days: number;
  total_days: number;
  moves: SuspiciousMove[];
};

export type DraftInput = {
  symbol: string;
  txn_type: string;
  quantity: string;
  price: string;
  trade_date: string;
  exchange?: string | null;
  name?: string | null;
  asset_class?: string | null;
  currency?: string | null;
  fx_rate_inr?: string | null;
};

export type Draft = {
  symbol: string;
  name: string;
  exchange: string;
  asset_class: string;
  txn_type: string;
  trade_date: string;
  quantity: string;
  price: string;
  currency: string;
  fx_rate_inr: string;
  charges_inr: string;
  prepaid_tax_inr: string;
  gross_inr: string;
  net_inr: string;
  warnings: string[];
  creates_instrument: boolean;
};

/** Thrown when the server rejects an entry, carrying its reason so the form can show it
 *  rather than a generic failure. */
export class EntryRejected extends Error {}

async function investmentError(r: Response, fallback: string): Promise<never> {
  let detail = fallback;
  try {
    const body = await r.json();
    if (typeof body?.detail === "string") detail = body.detail;
  } catch {
    // A non-JSON error body is still a failure; the fallback wording covers it.
  }
  throw new EntryRejected(detail);
}

export async function getInvestmentSummary(): Promise<InvestmentSummary> {
  const r = await req("/api/investments/summary");
  if (!r.ok) throw new Error("could not load the portfolio");
  return r.json();
}

export async function getHolding(symbol: string): Promise<HoldingDetail> {
  const r = await req(`/api/investments/holdings/${encodeURIComponent(symbol)}`);
  if (!r.ok) throw new Error("could not load that holding");
  return r.json();
}

export async function listInvestmentTransactions(): Promise<
  InvestmentTransaction[]
> {
  const r = await req("/api/investments/transactions");
  if (!r.ok) throw new Error("could not load the transaction history");
  return r.json();
}

export async function getInvestmentHistory(since?: string): Promise<Curve> {
  const r = await req(`/api/investments/history${since ? `?since=${since}` : ""}`);
  if (!r.ok) throw new Error("could not load the value history");
  return r.json();
}

/** Step one: what the server understood, costed and validated. Writes nothing. */
export async function draftTransaction(input: DraftInput): Promise<Draft> {
  const r = await req("/api/investments/transactions/draft", {
    method: "POST",
    body: JSON.stringify(input),
  });
  if (!r.ok) return investmentError(r, "that entry could not be costed");
  return r.json();
}

/** Step two. Sends the same raw inputs, not the draft — the server re-costs it, so a
 *  charge figure can never arrive from the client. */
export async function recordTransaction(
  input: DraftInput,
): Promise<InvestmentTransaction> {
  const r = await req("/api/investments/transactions", {
    method: "POST",
    body: JSON.stringify(input),
  });
  if (!r.ok) return investmentError(r, "that entry could not be recorded");
  return r.json();
}

/** Correct a mistaken entry. ⚠ This is not a delete and not an undo: it records a new
 *  entry that supersedes the original, and the original stays in the record. Word it that
 *  way wherever it is offered. */
export async function reverseTransaction(
  id: string,
  note?: string,
): Promise<InvestmentTransaction> {
  const r = await req(`/api/investments/transactions/${id}/reverse`, {
    method: "POST",
    body: JSON.stringify({ note: note ?? null }),
  });
  if (!r.ok) return investmentError(r, "that entry could not be reversed");
  return r.json();
}
