import { type FormEvent, useState } from "react";

import * as api from "../lib/api";

export default function LoginScreen({ onLogin }: { onLogin: (email: string) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onLogin(await api.login(email.trim(), password));
    } catch {
      setError("Invalid email or password.");
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm rise">
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-semibold tracking-tight">aceroai</h1>
          <p className="mt-1 text-sm text-muted">Your personal chief-of-staff.</p>
        </div>
        <form
          onSubmit={submit}
          className="rounded-2xl border border-line bg-surface p-6 shadow-sm"
        >
          <label className="block text-sm font-medium text-muted" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="mt-1 mb-4 w-full rounded-lg border border-line bg-paper px-3 py-2.5 text-ink outline-none focus:border-clay"
          />
          <label className="block text-sm font-medium text-muted" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="mt-1 w-full rounded-lg border border-line bg-paper px-3 py-2.5 text-ink outline-none focus:border-clay"
          />
          {error && <p className="mt-3 text-sm text-clay-strong">{error}</p>}
          <button
            type="submit"
            disabled={busy}
            className="mt-5 min-h-11 w-full rounded-lg bg-clay px-4 py-2.5 font-medium text-white transition hover:bg-clay-strong disabled:opacity-60"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </main>
  );
}
