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

/** A split or bonus the exchange announced, and what it would do to the book.
 *
 *  ⚠ `quantity_before`/`quantity_after` arrive computed. They are the arithmetic that
 *  changes a holding's size, and doing it here would do it in binary floating point. */
export type CorporateAction = {
  id: string;
  instrument_id: string;
  symbol: string;
  name: string;
  action_type: string;
  ex_date: string | null;
  purpose: string;
  status: "PENDING" | "NEEDS_REVIEW" | "APPLIED" | "IGNORED";
  source: string;
  announced_at: string;
  applied_at: string | null;
  /** Why a ratio could not be read, or what was done with the action. */
  note: string | null;
  /** null when the announcement could not be read precisely — the case needing a person. */
  ratio_text: string | null;
  quantity_change: string | null;
  quantity_before: string | null;
  quantity_after: string | null;
};

/** One foreign security's Schedule FA figures for one calendar year. */
export type ForeignHolding = {
  symbol: string;
  name: string;
  currency: string;
  acquired_on: string;
  initial_inr: string;
  peak_inr: string | null;
  peak_on: string | null;
  closing_inr: string | null;
  closing_on: string | null;
  closing_quantity: string;
  gross_income_inr: string;
  gross_proceeds_inr: string;
  /** ⚠ Coverage against the days it was HELD, not the length of the period. Comparing with
   *  the period read as missing data for a share bought mid-year. */
  days_valued: number;
  days_held: number;
  days_in_period: number;
  is_complete: boolean;
};

export type ScheduleFa = {
  year: number;
  period_start: string;
  period_end: string;
  holdings: ForeignHolding[];
  years_available: number[];
};

/** One part of the structural score, with the sentence explaining what it measured. */
export type FrameworkComponent = {
  name: string;
  points: string;
  available: string;
  detail: string;
};

/** How much durable demand the framework says a company has.
 *
 *  ⚠ `total` is null when the framework does not APPLY — a US company, or one called
 *  off-thesis. That is a different answer from "0", which means measured and found wanting.
 *  Rendering them the same way tells the reader something false. */
export type AbScore = {
  total: string | null;
  available: string;
  components: FrameworkComponent[];
  unavailable_because: string | null;
  /** The crossing count is a floor, not a ceiling — the score may be understated. */
  breadth_is_floor: boolean;
};

export type Bottleneck = {
  id: string;
  name: string;
  summary: string;
  crosses: string[];
  crossings_status: string;
  crisis: string;
  inflection_text: string;
  investability: string;
};

/** One component of the quality score. ⚠ `points` is null where the inputs were absent,
 *  which is a different answer from zero and must not render the same way. */
export type ScorePart = {
  name: string;
  points: string | null;
  available: string;
  detail: string;
  /** ⚠ False where the test does not describe this KIND of company — return on capital for
   *  a bank. THREE different renderings for three different facts: a number (did badly or
   *  well), "—" (not read), "n/a" (does not apply). Collapsing the last two is what made a
   *  fully-read bank look half-read and left it permanently unjudgeable. */
  applicable: boolean;
  /** The measured quantity where the page draws it — the margin of safety as a fraction,
   *  positive below worth and negative above. Null for parts that are only a sentence. */
  value?: string | null;
};

/** ⚠ `earned` and `available` belong together. Six on its own means nothing: six of ten is
 *  mediocre, six of six is excellent, and the difference is how many filings were read. */
export type Quality = {
  earned: string;
  available: string;
  ratio: string | null;
  parts: ScorePart[];
  unknown: string[];
  is_complete: boolean;
  /** Tests that do not apply to this kind of company. */
  not_applicable: string[];
  /** What this company's own test could offer if every filing had been read. ⚠ Ten for an
   *  industrial and ten for a bank out of an entirely different set, so `available` alone is
   *  not comparable between them — `available / possible` is. */
  possible: string;
  /** ⚠ Shown together. "1 of 5 read" and "1 of 1 possible" are opposite facts that look
   *  identical without the second number. */
  years_read: number;
  years_possible: number | null;
  /** Why the reading is as deep as it is — whether the company is too young to have more, or
   *  the exchange has not published it. Null when the reading is not thin. */
  history_note: string | null;
};

/** One checklist answer. ⚠ Every flag is a RED flag: YES is bad. */
export type Flag = {
  number: number;
  question: string;
  verdict: "YES" | "NO" | "UNKNOWN";
  evidence: string;
  computed: boolean;
};

/** One rule and what it decided. ⚠ `not_applicable` is distinct from `passed`: "not asked"
 *  and "asked and satisfied" are different facts. */
export type Gate = {
  gate: string;
  passed: boolean;
  not_applicable: boolean;
  detail: string;
};

/** What would prove the thesis wrong — a number, a comparison and a deadline. */
export type Trigger = {
  id: string;
  metric_key: string;
  comparator: string;
  threshold: string;
  unit: string;
  window_until: string;
  description: string;
  status: string;
  fired_at: string | null;
};

export type ProposalClaim = {
  id: string;
  claim_text: string;
  metric_key: string | null;
  due_by: string;
  status: string;
};

/** A suggestion, with everything it rests on frozen at the moment it was made. */
export type Proposal = {
  id: string;
  symbol: string;
  name: string;
  action: string;
  status:
    | "PENDING"
    | "APPROVED"
    | "REJECTED"
    | "MODIFIED"
    | "EXPIRED"
    | "BLOCKED";
  blocked_by: string | null;
  target_amount_inr: string | null;
  target_qty: string | null;
  horizon_days: number;
  thesis: string;
  confidence: string;
  ab_score: string | null;
  quality_earned: string | null;
  quality_available: string | null;
  reflexivity_flags_yes: number;
  quadrant: string | null;
  price_snapshot: Record<string, unknown>;
  gates: Gate[];
  triggers: Trigger[];
  claims: ProposalClaim[];
  created_at: string;
  decided_at: string | null;
  decision_reason: string | null;
};

/** One book or benchmark, valued at the same prices as all the others. */
export type BookLine = {
  kind: string;
  name: string;
  purpose: string;
  invested_inr: string;
  /** ⚠ null when even one holding lacks a price — a partial total steps whenever coverage
   *  changes, which is indistinguishable from a real movement. */
  value_inr: string | null;
  gain_inr: string | null;
  gain_pct: string | null;
  positions: number;
  is_complete: boolean;
};

export type Books = {
  lines: BookLine[];
  as_of: string | null;
  /** ⚠ false until the real book and a paper book are both fully priced. */
  readable: boolean;
  /** What you bought that the system never suggested — the one category a merged ledger
   *  would silently discard. */
  unaided: string[];
};

/** One reading of how the system is doing.
 *
 *  ⚠ `value` is null while `n` is below the minimum, and that is the honest state for a long
 *  time. A figure over six outcomes reads exactly like one over six hundred. */
export type Measure = {
  name: string;
  value: string | null;
  n: number;
  detail: string;
  /** The sample it waits for before it reports, so progress can be drawn. */
  needed?: number | null;
};

/** A condition that came true — written down before the position was taken. */
export type FiredTrigger = {
  id: string;
  symbol: string;
  description: string;
  metric_key: string;
  fired_at: string | null;
  evidence: Record<string, unknown>;
};

export type ProposalsView = {
  open: Proposal[];
  recent: Proposal[];
  /** ⚠ Includes evenings that suggested nothing, which is usually the right answer. */
  runs_recorded: number;
  last_run_at: string | null;
  /** ⚠ Outranks everything else on screen: a thesis you hold money against has been
   *  contradicted by the facts. */
  fired: FiredTrigger[];
  measures: Measure[];
};

export type Mapping = {
  id: string;
  instrument_id: string;
  symbol: string;
  name: string;
  sector: string | null;
  multiple: string;
  /** ⚠ No multiple exists for this sector; the default is standing in, so any margin of
   *  safety computed from it is a guess wearing the clothes of a calculation. */
  multiple_is_fallback: boolean;
  multiple_why: string;
  b_bottleneck: string | null;
  bottleneck_name: string | null;
  a_imperatives: string[];
  crosses_a_count: number;
  crossings_status: string;
  is_crisis_accelerated: boolean;
  inflection_quarter: string | null;
  investability: string | null;
  rationale: string | null;
  proposed_by: string;
  /** null = proposed and not yet agreed with. It scores nothing until it is. */
  approved_at: string | null;
  review_after: string | null;
  off_framework: boolean;
  is_held: boolean;
  score: AbScore;
  quality: Quality | null;
  flags: Flag[];
  /** ⚠ Q2 and Q4 block a purchase outright, so BORDERLINE on a thin reading is a refusal to
   *  convict rather than a missing answer. */
  quadrant: string | null;
  years_read: number;
};

export type FrameworkAttention = {
  kind:
    | "UNMAPPED"
    | "UNAPPROVED"
    | "EXPIRED"
    | "BREADTH_FLOOR"
    | "NO_MULTIPLE";
  /** So a company with no place can be placed where it is listed. */
  instrument_id: string | null;
  symbol: string;
  detail: string;
};

export type Framework = {
  version: number;
  approved_at: string | null;
  imperatives: Array<Record<string, unknown>>;
  bottlenecks: Bottleneck[];
  mappings: Mapping[];
  attention: FrameworkAttention[];
};

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
  /** ⚠ An announced split or bonus not yet in the ledger. While this is set the price and
   *  the quantity on this row count different things, so the profit and loss beside them is
   *  not reliable and must not be shown as though it were. */
  open_action: CorporateAction | null;
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
  /** The whole book, crypto included — what the headline shows. The three fields above
   *  exclude ring-fenced holdings so they stay comparable with each other. */
  market_value_all_inr: string;
  unrealised_all_inr: string;
  unrealised_all_pct: Ratio | null;
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
  /** One short line under the figure — the same fact in rupees. */
  headline: string | null;
  /** The longer note, shown behind an "i" rather than on the card. */
  explanation: string | null;
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
  /** Outstanding splits and bonuses, plus recently applied ones so they can be checked. */
  corporate_actions: CorporateAction[];
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

export type PriceRefresh = {
  /** New prices recorded. Zero is the usual, healthy answer: nothing was stale. */
  written: number;
  /** Sources that could not be reached. Their holdings keep their last price, shown stale. */
  failed: string[];
};

/** Fetch live prices for stale holdings only. The page calls this in the background on open
 *  and reloads if anything was written — figures appear at once and freshen a moment later. */
export async function refreshPrices(): Promise<PriceRefresh> {
  const r = await req("/api/investments/prices/refresh", { method: "POST" });
  if (!r.ok) throw new Error("could not refresh prices");
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

/** Outstanding splits and bonuses, plus recently applied ones. Also carried on the summary,
 *  so this is only for a caller that wants them without the whole fold. */
export async function listCorporateActions(): Promise<CorporateAction[]> {
  const r = await req("/api/investments/corporate-actions");
  if (!r.ok) throw new Error("could not load corporate actions");
  return r.json();
}

/** Write the announced quantity change into the ledger.
 *
 *  ⚠ Not a cosmetic acknowledgement: this appends a real transaction, which is why it is a
 *  deliberate action rather than something the page does on your behalf. It is undone by the
 *  ordinary correction path, like any other entry. */
export async function applyCorporateAction(
  id: string,
): Promise<CorporateAction> {
  const r = await req(`/api/investments/corporate-actions/${id}/apply`, {
    method: "POST",
  });
  if (!r.ok) return investmentError(r, "that action could not be applied");
  return r.json();
}

/** Mark an action as not applying to this book, clearing the holding's flag. Touches
 *  nothing in the ledger. */
export async function dismissCorporateAction(
  id: string,
): Promise<CorporateAction> {
  const r = await req(`/api/investments/corporate-actions/${id}/dismiss`, {
    method: "POST",
  });
  if (!r.ok) return investmentError(r, "that action could not be dismissed");
  return r.json();
}

/** Foreign holdings as Schedule FA asks for them. ⚠ The CALENDAR year — the one Indian tax
 *  figure not reported on the financial year. */
export async function getScheduleFa(year?: number): Promise<ScheduleFa> {
  const r = await req(
    `/api/investments/schedule-fa${year ? `?year=${year}` : ""}`,
  );
  if (!r.ok) throw new Error("could not load the foreign-holdings schedule");
  return r.json();
}

/** The framework in force, where every tracked company sits in it, and what needs you. */
export async function getFramework(): Promise<Framework> {
  const r = await req("/api/investments/framework");
  if (!r.ok) throw new Error("could not load the framework");
  return r.json();
}

/** Agree that a company clears the bottleneck it is mapped to.
 *
 *  ⚠ This one call is what lets the company score at all. Until it happens the mapping is a
 *  suggestion and the structural score is zero, however strong the company looks — that is
 *  the guard the whole score rests on, not a defect to work around. */
export async function approveMapping(
  id: string,
  note?: string,
): Promise<Mapping> {
  const r = await req(`/api/investments/framework/mappings/${id}/approve`, {
    method: "POST",
    body: JSON.stringify({ note: note ?? null }),
  });
  if (!r.ok) return investmentError(r, "that mapping could not be approved");
  return r.json();
}

/** Give a followed company with no place in the framework its first one, by hand. It arrives
 *  unapproved — choosing a bottleneck is a claim about the company, agreed with separately. */
export async function placeInstrument(
  instrumentId: string,
  input: { b_bottleneck?: string | null; off_framework?: boolean; rationale?: string },
): Promise<Mapping> {
  const r = await req(`/api/investments/framework/instruments/${instrumentId}/place`, {
    method: "POST",
    body: JSON.stringify({
      b_bottleneck: input.b_bottleneck ?? null,
      off_framework: input.off_framework ?? false,
      rationale: input.rationale ?? null,
    }),
  });
  if (!r.ok) return investmentError(r, "that company could not be placed");
  return r.json();
}

export type SuggestedPlace = {
  placed: boolean;
  bottleneck: string | null;
  confidence: number;
  why: string;
};

/** Ask the model where a followed company with no place belongs. ⚠ A billed model call; a
 *  usable answer is proposed UNAPPROVED, and an unsure one leaves the company unplaced with
 *  the reason. */
export async function suggestPlace(instrumentId: string): Promise<SuggestedPlace> {
  const r = await req(`/api/investments/framework/instruments/${instrumentId}/suggest`, {
    method: "POST",
  });
  if (!r.ok) return investmentError(r, "no suggestion could be made");
  return r.json();
}

/** One thing on the page waiting for a decision from you. */
export type Waiting = {
  tab: "holdings" | "decisions" | "companies" | "sources";
  kind: string;
  /** ⚠ Most pressing first: urgent (a disproved thesis, a split the ledger has not caught up
   *  with), then decide, then lead. */
  severity: "urgent" | "decide" | "lead";
  symbol: string | null;
  text: string;
  ref: string | null;
};

export type Attention = {
  items: Waiting[];
  counts: Partial<Record<Waiting["tab"], number>>;
};

export async function getAttention(): Promise<Attention> {
  const r = await req("/api/investments/attention");
  if (!r.ok) throw new Error("could not load what is waiting");
  return r.json();
}

/** Move a company to a different bottleneck, or out of the framework entirely. The
 *  replacement arrives unapproved, so the company drops to zero until it is confirmed. */
export async function remapInstrument(
  id: string,
  input: { b_bottleneck?: string | null; off_framework?: boolean; rationale?: string },
): Promise<Mapping> {
  const r = await req(`/api/investments/framework/mappings/${id}/remap`, {
    method: "POST",
    body: JSON.stringify({
      b_bottleneck: input.b_bottleneck ?? null,
      off_framework: input.off_framework ?? false,
      rationale: input.rationale ?? null,
    }),
  });
  if (!r.ok) return investmentError(r, "that company could not be remapped");
  return r.json();
}

/** Establish which imperatives a bottleneck actually blocks.
 *
 *  ⚠ Writes a NEW framework version: a crossing set is a claim about the country, and
 *  changing one changes the rules every later score is measured against. Companies mapped to
 *  the bottleneck keep their approval — what was agreed is that the company clears this
 *  bottleneck, and that has not changed; only how wide the bottleneck is. */
export async function reviseCrossings(
  bottleneck: string,
  crosses: string[],
  note?: string,
): Promise<Framework> {
  const r = await req(
    `/api/investments/framework/bottlenecks/${encodeURIComponent(bottleneck)}/crossings`,
    {
      method: "POST",
      body: JSON.stringify({
        crosses,
        status: "CONFIRMED",
        note: note ?? null,
      }),
    },
  );
  if (!r.ok) return investmentError(r, "those crossings could not be saved");
  return r.json();
}

/** What is waiting for you, and what recently happened — refusals included. */
export async function getProposals(): Promise<ProposalsView> {
  const r = await req("/api/investments/proposals");
  if (!r.ok) throw new Error("could not load suggestions");
  return r.json();
}

/** Approve, reject or modify a suggestion.
 *
 *  ⚠ `reason` is required by the database, not merely asked for. It is the data that
 *  eventually reveals what kinds of suggestion keep being turned down, which is the only way
 *  the system ever learns anything about its own judgement. */
export async function decideProposal(
  id: string,
  outcome: "APPROVE" | "REJECT" | "MODIFY",
  reason: string,
  modifiedAmountInr?: string,
): Promise<Proposal> {
  const r = await req(`/api/investments/proposals/${id}/decide`, {
    method: "POST",
    body: JSON.stringify({
      outcome,
      reason,
      modified_amount_inr: modifiedAmountInr ?? null,
    }),
  });
  if (!r.ok) return investmentError(r, "that decision could not be recorded");
  return r.json();
}

/** Every book side by side, valued at the same prices at the same moment. */
export async function getBooks(): Promise<Books> {
  const r = await req("/api/investments/books");
  if (!r.ok) throw new Error("could not load the books");
  return r.json();
}

// --- the reading layer -----------------------------------------------------------------

/** One place the system reads from. */
export type Source = {
  id: string;
  kind: string;
  name: string;
  handle: string;
  /** ⚠ 1 = a filing or a regulator · 2 = the press · 3 = commentary. A suggestion resting
   *  only on tier 3 fails its sourcing gate — a stock named on a channel enters the research
   *  queue, never the portfolio. */
  trust_tier: number;
  is_active: boolean;
  /** ⚠ null means nothing is read from it. Adding a source changes what the system can be
   *  talked into, so it waits for you the way a framework mapping does. */
  approved_at: string | null;
  notes: string | null;
  last_polled_at: string | null;
};

/** What one source named, and whether its directional calls worked out. */
export type Attribution = {
  source: string;
  trust_tier: number;
  /** ⚠ EVERYTHING it named, including what was never looked at. Scoring a source on the
   *  ideas you acted on measures your own filter and turns 2.5% into 33%. */
  named: number;
  directional: number;
  scored: number;
  pending: number;
  became_proposals: number;
  hit_rate: Measure;
};

/** One thing a source said about one instrument. */
export type Heard = {
  symbol: string;
  name: string;
  stance: string;
  excerpt: string | null;
  source: string;
  trust_tier: number;
  url: string | null;
  published_at: string | null;
  is_held: boolean;
};

export type Reading = {
  sources: Source[];
  heard: Heard[];
  attribution: Attribution[];
  awaiting_approval: number;
};

/** Where the system reads from, what has been said lately, and whether it was worth it. */
export async function getReading(days = 30): Promise<Reading> {
  const r = await req(`/api/investments/reading?days=${days}`);
  if (!r.ok) throw new Error("could not load the reading list");
  return r.json();
}

/** Start reading from a source.
 *
 *  ⚠ This widens what is READ, never what is acted on. The sourcing gate still refuses a
 *  suggestion resting on commentary alone, whatever that commentary says. */
export async function approveSource(id: string): Promise<Source> {
  const r = await req(`/api/investments/reading/sources/${id}/approve`, {
    method: "POST",
  });
  if (!r.ok) return investmentError(r, "that source could not be approved");
  return r.json();
}

/** Add a YouTube channel to read from.
 *
 *  ⚠ Takes whatever the address bar had — a `@handle`, a full URL, a legacy `/c/` path or a
 *  raw `UC…` id — because requiring the channel id would make adding a channel a research
 *  task, and a list that is awkward to change never gets changed.
 *
 *  ⚠ It arrives OFF and waiting for approval, like every other commentary source. Pasting a
 *  link is not the same act as deciding to be influenced by it. */
export async function addYoutubeChannel(
  pasted: string,
  notes?: string,
): Promise<Source> {
  const r = await req("/api/investments/reading/sources/youtube", {
    method: "POST",
    body: JSON.stringify({ pasted, notes: notes || null }),
  });
  if (!r.ok) return investmentError(r, "that channel could not be added");
  return r.json();
}

/** Switch a source on or off. ⚠ Off, never deleted: removing one would orphan every mention
 *  that cited it and quietly rewrite the attribution history. */
export async function setSourceActive(id: string, isActive: boolean): Promise<Source> {
  const r = await req(`/api/investments/reading/sources/${id}/active`, {
    method: "POST",
    body: JSON.stringify({ is_active: isActive }),
  });
  if (!r.ok) return investmentError(r, "that source could not be changed");
  return r.json();
}

// --- the research queue -----------------------------------------------------------------

/** One company something named that you neither hold nor watch. */
export type QueueLine = {
  id: string;
  symbol: string;
  name: string;
  status: string;
  /** ⚠ What the queue is ordered by, with the tier — not the date. A company several sources
   *  keep returning to is a different proposition from one named once in passing. */
  mention_count: number;
  best_trust_tier: number;
  first_seen_at: string;
  last_seen_at: string;
  /** How long it has sat here. The weekly review asks this by name. */
  age_days: number;
  named_by: string | null;
  stance: string | null;
  excerpt: string | null;
  proposed_bottleneck: string | null;
  dismissed_reason: string | null;
  /** ⚠ These two travel together and must be SHOWN together. "4" means nothing on its own:
   *  four out of four is excellent and four out of ten is mediocre, and the difference is
   *  entirely whether the company's filings had been read. */
  quality_earned: string | null;
  quality_available: string | null;
  price: string | null;
  bottleneck_name: string | null;
  /** Why the model placed it there, in its own words — so a wrong placement can be seen to
   *  be wrong rather than merely doubted. */
  bottleneck_why: string | null;
};

export type ResearchQueue = {
  lines: QueueLine[];
  /** ⚠ How many companies the reader can recognise. Shown because a vocabulary that failed
   *  to load would make discovery stop silently, and a zero says so immediately. */
  universe_size: number;
  universe_refreshed_at: string | null;
};

/** Companies worth a look, that you do not already follow. */
export async function getResearchQueue(includeClosed = false): Promise<ResearchQueue> {
  const r = await req(`/api/investments/research?include_closed=${includeClosed}`);
  if (!r.ok) throw new Error("could not load the research queue");
  return r.json();
}

/** Start following a candidate — it becomes priced, filed and scored.
 *
 *  ⚠ This is the moment it starts costing something. Until now it has been a name in a list. */
export async function promoteCandidate(id: string, sector?: string): Promise<QueueLine> {
  const r = await req(`/api/investments/research/${id}/promote`, {
    method: "POST",
    body: JSON.stringify({ sector: sector ?? null }),
  });
  if (!r.ok) return investmentError(r, "that company could not be promoted");
  return r.json();
}

/** Drop a candidate, with a reason.
 *
 *  ⚠ The reason is data, not politeness. It is the only record of what kinds of idea keep
 *  being refused, and the database refuses a dismissal without one. */
export async function dismissCandidate(id: string, reason: string): Promise<QueueLine> {
  const r = await req(`/api/investments/research/${id}/dismiss`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
  if (!r.ok) return investmentError(r, "that company could not be dismissed");
  return r.json();
}

// --- the inbox --------------------------------------------------------------------------

/** What came of something you dropped in.
 *
 *  ⚠ `stored: false` with a `note` is a real outcome, not an error. A page needing a browser,
 *  a PDF, or a listing naming thirty companies each produce nothing — and an inbox that
 *  swallowed them silently would train you to drop things into a void. */
export type DropResult = {
  stored: boolean;
  title: string;
  url: string | null;
  /** 1 = a filing or regulator · 2 = press or your own note. */
  trust_tier: number;
  named: string[];
  /** Companies this put into the research queue for the first time. */
  discovered: string[];
  /** Companies you already follow — filed against the holding rather than queued. */
  already_followed: string[];
  note: string | null;
};

/** Drop a link, a video or a note, filed against the companies it names.
 *
 *  ⚠ You become a measured source: what you drop is recorded the way a channel's uploads are,
 *  which is what eventually answers whether your tips beat the feed you ignore. */
export async function dropIntoInbox(input: {
  url?: string;
  text?: string;
}): Promise<DropResult> {
  const r = await req("/api/investments/inbox", {
    method: "POST",
    body: JSON.stringify({ url: input.url ?? null, text: input.text ?? null }),
  });
  if (!r.ok) return investmentError(r, "that could not be read");
  return r.json();
}

/** Read this company's filings and place it in the framework.
 *
 *  ⚠ The placement is a PROPOSAL — it scores zero until you agree with it. And this does not
 *  start following the company: that is promotion, which puts a name into the daily price
 *  loop and is what costs something every day. */
export async function analyseCandidate(id: string): Promise<QueueLine> {
  const r = await req(`/api/investments/research/${id}/analyse`, { method: "POST" });
  if (!r.ok) return investmentError(r, "that company could not be analysed");
  return r.json();
}

// --- looking backwards ------------------------------------------------------------------

/** One look backwards, as the facts that were true then.
 *
 *  ⚠ `content` is a structure of figures assembled by code, never prose written by a model.
 *  A review is almost entirely numbers, and a summary paragraph would be the one place a
 *  figure could be restated wrongly with nothing to check it against. */
export type InvestmentReview = {
  id: string;
  kind: string;
  period_start: string;
  period_end: string;
  generated_at: string;
  headline: string;
  content: {
    kind: string;
    period: { start: string; end: string };
    decisions: {
      counts: Record<string, number>;
      decisions: {
        outcome: string;
        action: string;
        thesis: string;
        reason: string;
        on: string;
      }[];
    };
    blocked: { action: string; blocked_by: string | null }[];
    approaching: {
      description: string;
      metric: string;
      value: string;
      threshold: string;
      due_by: string;
    }[];
    queue: { waiting: number; oldest_days: number; stale: { symbol: string; age_days: number }[] };
    budget: { budget_inr: string; committed_inr: string; unspent_inr: string };
    books: {
      readable: boolean;
      lines: { kind: string; name: string; gain_pct: string | null; positions: number }[];
      unaided: string[];
    };
    /** ⚠ `value` is null until the sample is big enough, and `detail` says why in words. */
    measures: { name: string; value: string | null; n: number; detail: string }[];
    sources?: {
      source: string;
      trust_tier: number;
      named: number;
      directional: number;
      hit_rate: string | null;
      n: number;
      detail: string;
    }[];
  };
};

/** The looks backwards, newest first. ⚠ Read, never regenerated. */
export async function getInvestmentReviews(limit = 12): Promise<InvestmentReview[]> {
  const r = await req(`/api/investments/reviews?limit=${limit}`);
  if (!r.ok) throw new Error("could not load the reviews");
  return (await r.json()).reviews;
}

// --- what you could have bought instead --------------------------------------------------

/** One alternative over one window.
 *
 *  ⚠ `proxy_for` is always shown. The alternative is an index FUND, not an index — an index
 *  cannot be bought — and a benchmark that is a proxy has to announce it, or a comparison
 *  against it reads as a comparison against the index itself. */
export type BenchmarkLine = {
  key: string;
  name: string;
  proxy_for: string;
  region: string;
  /** ⚠ null when the window is not covered on both sides. */
  change_pct: string | null;
  detail: string;
};

export type Benchmarks = {
  start: string;
  end: string;
  portfolio_pct: string | null;
  lines: BenchmarkLine[];
  weights: Record<string, string>;
  blended_pct: string | null;
  readable: boolean;
  detail: string;
  non_equity_share: string;
  /** ⚠ Present when the two sides measure materially different things — crypto and funds are
   *  in the portfolio's own return and no index stands in for them. Shown beside the figures
   *  rather than instead of them. */
  caveat: string | null;
};

/** The book against what you could have bought instead, over the same window. */
export async function getBenchmarks(days = 365): Promise<Benchmarks> {
  const r = await req(`/api/investments/benchmarks?days=${days}`);
  if (!r.ok) throw new Error("could not load the benchmarks");
  return r.json();
}

// --- the six criteria -------------------------------------------------------------------

/** One condition for real money, and how far off it is. */
export type Criterion = {
  key: string;
  question: string;
  /** ⚠ null means NOT YET TESTABLE, which is different from failing. A criterion with no
   *  sample behind it has not been failed; it has not been tested — and rendering those the
   *  same way would turn "we do not know" into "we fell short". */
  met: boolean | null;
  value: string;
  target: string;
  detail: string;
  n: number;
  /** ⚠ Shown beside every return statistic. A number without its error bar is the mechanism
   *  by which this system would mislead its owner. */
  standard_error: string | null;
};

export type Verdict = {
  criteria: Criterion[];
  met: number;
  failed: number;
  untested: number;
  all_met: boolean;
  headline: string;
  generated_at: string | null;
};

/** The six criteria for real money, written down in advance so they cannot be softened. */
export async function getVerdict(): Promise<Verdict> {
  const r = await req("/api/investments/verdict");
  if (!r.ok) throw new Error("could not load the criteria");
  return r.json();
}

// --- themes -----------------------------------------------------------------------------

/** One theme that got attention, and what the book has sitting on it.
 *
 *  ⚠ A theme is never evidence. It raises no proposal and changes no score — it answers one
 *  question, *what am I exposed to that just got attention*. */
export type Exposure = {
  bottleneck_id: string;
  name: string;
  /** ⚠ Approved mappings only. An unapproved mapping is a claim nobody has agreed with yet. */
  held: string[];
  queued: string[];
  mentions: number;
};

export type Themes = { themes: Exposure[]; days: number };

/** Themes the reading has been about, where the book is exposed to them. */
export async function getThemes(days = 14): Promise<Themes> {
  const r = await req(`/api/investments/themes?days=${days}`);
  if (!r.ok) throw new Error("could not load the themes");
  return r.json();
}
