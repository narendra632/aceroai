/* Offering installation where the browser allows it, and explaining it where it does not.
 *
 * Chrome and Edge fire `beforeinstallprompt`, which can be saved and replayed from a real
 * button. **Safari fires nothing at all**, on any platform — so on iOS the only honest
 * option is to describe the Share → Add to Home Screen steps. Showing a dead "Install"
 * button there would be worse than showing nothing.
 *
 * That distinction matters more than it looks: on iOS, installing is also the precondition
 * for notifications working at all.
 */

import { useCallback, useEffect, useState } from "react";

import { isIos, isStandalone } from "@/lib/push";

/** The event Chrome fires. Not in TypeScript's DOM lib, because it is not standardised. */
type InstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

export type InstallState = {
  /** Already running as an installed app — offer nothing. */
  installed: boolean;
  /** A real prompt is available; call `install()`. */
  canPrompt: boolean;
  /** Manual steps, for platforms that never fire the event. Null when not applicable. */
  manualSteps: string | null;
  install: () => Promise<"accepted" | "dismissed" | "unavailable">;
};

const IOS_STEPS =
  "Tap the Share button, then “Add to Home Screen”. On iPhone and iPad this is also what makes notifications possible.";

export function useInstallPrompt(): InstallState {
  const [deferred, setDeferred] = useState<InstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(isStandalone);

  useEffect(() => {
    function onBeforeInstall(event: Event) {
      // Chrome shows its own banner unless this is prevented; we want the offer to live
      // in Settings, where it can sit beside the notification setup it enables.
      event.preventDefault();
      setDeferred(event as InstallPromptEvent);
    }
    function onInstalled() {
      setInstalled(true);
      setDeferred(null);
    }
    window.addEventListener("beforeinstallprompt", onBeforeInstall);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstall);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  const install = useCallback(async () => {
    if (!deferred) return "unavailable" as const;
    await deferred.prompt();
    const { outcome } = await deferred.userChoice;
    // The event is single-use: Chrome will fire a fresh one if the user declines and
    // becomes eligible again.
    setDeferred(null);
    return outcome;
  }, [deferred]);

  return {
    installed,
    canPrompt: Boolean(deferred) && !installed,
    manualSteps: !installed && !deferred && isIos() ? IOS_STEPS : null,
    install,
  };
}
