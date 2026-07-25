// Single place that talks to the backend. Every call sends the auth cookie
// (`credentials: "include"`). Chat streams over SSE, consumed with fetch +
// a body reader because EventSource cannot POST or send cookies cleanly.

const API = import.meta.env.VITE_API_URL as string;

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

function req(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
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
  return (await r.json()).email;
}

export async function logout(): Promise<void> {
  await req("/api/auth/logout", { method: "POST" });
}

export async function listSessions(): Promise<Session[]> {
  const r = await req("/api/chat/sessions");
  return r.ok ? r.json() : [];
}

export async function getMessages(sessionId: string): Promise<ChatMessage[]> {
  const r = await req(`/api/chat/sessions/${sessionId}/messages`);
  return r.ok ? r.json() : [];
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
): AsyncGenerator<ChatEvent> {
  const res = await fetch(`${API}/api/chat`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
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
