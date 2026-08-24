import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.tsx";
import { register as registerServiceWorker } from "./lib/push";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

/* Register the service worker after the app has mounted.
 *
 * Deliberately not awaited and deliberately unable to throw: it buys the offline shell and
 * the surface notifications land on, and neither is worth delaying first paint for. If it
 * fails, the app behaves exactly as it did before it existed.
 *
 * Note this only REGISTERS. Subscribing to notifications needs a permission prompt, which
 * browsers only honour from a user gesture — so that lives behind a button in Settings.
 */
void registerServiceWorker();
