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
  return r.ok ? r.json() : [];
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
  await req(`/api/tasks/${id}`, { method: "DELETE" });
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

export async function listJournal(): Promise<JournalEntry[]> {
  const r = await req("/api/journal");
  return r.ok ? r.json() : [];
}

export async function addJournalEntry(input: JournalInput): Promise<JournalEntry> {
  const r = await req("/api/journal", { method: "POST", body: JSON.stringify(input) });
  if (!r.ok) throw new Error("could not add entry");
  return r.json();
}

export async function deleteJournalEntry(id: string): Promise<void> {
  await req(`/api/journal/${id}`, { method: "DELETE" });
}

// --- settings (provider + models) ---

export type EmbeddingInfo = {
  provider: string;
  model: string;
  dimensions: number;
  pinned: boolean;
  note: string;
};

export type Settings = {
  provider: string;
  model_chat: string;
  model_deep: string;
  available_providers: string[];
  model_catalog: Record<string, string[]>;
  defaults: Record<string, string>;
  embedding: EmbeddingInfo;
};

export type SettingsUpdate = {
  provider?: string;
  model_chat?: string;
  model_deep?: string;
};

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
