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
  const r = await req(`/api/chat/sessions/${sessionId}/restore`, { method: "POST" });
  if (!r.ok) throw new Error("could not restore the conversation");
  return r.json();
}

export async function renameSession(sessionId: string, title: string): Promise<Session> {
  const r = await req(`/api/chat/sessions/${sessionId}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
  if (!r.ok) throw new Error("could not rename the conversation");
  return r.json();
}

/** Drop the trailing assistant reply so the turn can be sent again. */
export async function regenerate(sessionId: string): Promise<void> {
  const r = await req(`/api/chat/sessions/${sessionId}/regenerate`, { method: "POST" });
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
  const r = await req("/api/tasks", { method: "POST", body: JSON.stringify(input) });
  if (!r.ok) throw new Error("could not create task");
  return r.json();
}

export async function updateTask(id: string, patch: Partial<Task>): Promise<Task> {
  const r = await req(`/api/tasks/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
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

export async function listJournal(query: JournalQuery = {}): Promise<JournalEntry[]> {
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
  const r = await req(`/api/journal/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
  if (!r.ok) throw new Error("could not update the entry");
  return r.json();
}

/** Undo a delete. The entry returns with the same id and its original date. */
export async function restoreJournalEntry(id: string): Promise<JournalEntry> {
  const r = await req(`/api/journal/${id}/restore`, { method: "POST" });
  if (!r.ok) throw new Error("could not restore the entry");
  return r.json();
}

export async function addJournalEntry(input: JournalInput): Promise<JournalEntry> {
  const r = await req("/api/journal", { method: "POST", body: JSON.stringify(input) });
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
  const r = await req("/api/settings", { method: "PATCH", body: JSON.stringify(patch) });
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
  | "preference"
  | "health"
  | "work"
  | "finance"
  | "relationship"
  | "other";

export type Fact = {
  id: string;
  fact: string;
  category: FactCategory;
  confidence: number;
  /** "inferred" = the assistant concluded it; "stated" = you confirmed it. */
  source: "inferred" | "stated";
  status: "active" | "superseded" | "rejected";
  superseded_by: string | null;
  valid_from: string;
  created_at: string;
  updated_at: string;
};

export type FactDetail = Fact & {
  /** The conversation this was learned from, when it came from one. */
  source_session_id: string | null;
  /** The belief this one replaced, so history is reachable and not merely stored. */
  previous: Fact | null;
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
export async function setFactConfirmed(id: string, confirmed: boolean): Promise<Fact> {
  const path = confirmed ? "confirm" : "unconfirm";
  const r = await req(`/api/memory/facts/${id}/${path}`, { method: "POST" });
  if (!r.ok) throw new Error(confirmed ? "Could not confirm that fact" : "Could not undo that");
  return r.json();
}

export async function forgetFact(id: string): Promise<void> {
  const r = await req(`/api/memory/facts/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error("Could not forget that fact");
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

export type SeriesPoint = { day: string; kind: TurnKind; calls: number; cost_usd: string };

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

export async function getTurn(id: string): Promise<{ turn: TurnRow; spans: TurnSpan[] }> {
  const r = await req(`/api/insights/turns/${id}`);
  if (!r.ok) throw new Error("Could not load that call");
  return r.json();
}
