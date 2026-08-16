import { type FormEvent, useState } from "react";
import { Eye, EyeOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import * as api from "@/lib/api";

export default function LoginScreen({ onLogin }: { onLogin: (email: string) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [show, setShow] = useState(false);

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
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="rise w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-semibold tracking-tight">aceroai</h1>
          <p className="mt-1 text-sm text-muted-foreground">Your personal chief-of-staff.</p>
        </div>
        <form onSubmit={submit} className="rounded-2xl border border-border bg-card p-6 shadow-sm">
          <label className="block text-sm font-medium text-muted-foreground" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="mt-1 mb-4 w-full rounded-lg border border-border bg-background px-3 py-2.5 text-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/30"
          />
          <label className="block text-sm font-medium text-muted-foreground" htmlFor="password">
            Password
          </label>
          <div className="relative mt-1">
            <input
              id="password"
              type={show ? "text" : "password"}
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full rounded-lg border border-border bg-background py-2.5 pr-12 pl-3 text-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/30"
            />
            <button
              type="button"
              onClick={() => setShow((s) => !s)}
              aria-label={show ? "Hide password" : "Show password"}
              aria-pressed={show}
              className="absolute top-1/2 right-1 grid size-10 -translate-y-1/2 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </div>
          {/* role="alert" so a screen reader announces the failure rather than
              leaving the user wondering why nothing happened */}
          {error && (
            <p role="alert" className="mt-3 text-sm text-destructive">
              {error}
            </p>
          )}
          <Button type="submit" disabled={busy} size="lg" className="mt-5 w-full">
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </div>
    </main>
  );
}
