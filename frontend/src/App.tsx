import { useEffect, useState } from "react";

const API = import.meta.env.VITE_API_URL;

export default function App() {
  const [status, setStatus] = useState<"checking" | "ok" | "down">("checking");

  useEffect(() => {
    fetch(`${API}/health`)
      .then((r) => r.json())
      .then((d) => setStatus(d.status === "ok" ? "ok" : "down"))
      .catch(() => setStatus("down"));
  }, []);

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col items-center justify-center gap-4">
      <h1 className="text-3xl font-semibold tracking-tight">aceroai</h1>
      <p className="flex items-center gap-2 text-sm text-zinc-400">
        <span
          className={`h-2.5 w-2.5 rounded-full ${
            status === "ok"
              ? "bg-emerald-400"
              : status === "down"
                ? "bg-red-500"
                : "bg-amber-400"
          }`}
        />
        API: {status}
      </p>
      <p className="text-xs text-zinc-500">Scaffold only — real UI lands with the chat feature.</p>
    </main>
  );
}
