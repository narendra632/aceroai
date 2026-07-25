import { useEffect, useState } from "react";

import ChatLayout from "./components/ChatLayout";
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

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted">Loading…</div>
    );
  }

  if (!email) {
    return <LoginScreen onLogin={setEmail} />;
  }

  async function handleLogout() {
    await api.logout();
    setEmail(null);
  }

  return <ChatLayout email={email} onLogout={handleLogout} />;
}
