import { useEffect, useState } from "react";

import { ToastProvider } from "@/components/ui/toast";
import { TooltipProvider } from "@/components/ui/tooltip";
import AppShell from "./components/AppShell";
import LoginScreen from "./components/LoginScreen";
import * as api from "./lib/api";

export default function App() {
  const [email, setEmail] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.me().then((e) => {
      setEmail(e);
      setLoading(false);
    });
  }, []);

  async function handleLogout() {
    await api.logout();
    setEmail(null);
  }

  return (
    <ToastProvider>
      <TooltipProvider delayDuration={200}>
        {loading ? (
          <div className="flex min-h-screen items-center justify-center text-muted-foreground">
            Loading…
          </div>
        ) : email ? (
          <AppShell email={email} onLogout={handleLogout} />
        ) : (
          <LoginScreen onLogin={setEmail} />
        )}
      </TooltipProvider>
    </ToastProvider>
  );
}
