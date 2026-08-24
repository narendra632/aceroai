/* Whether the device believes it has a connection.
 *
 * `navigator.onLine` is famously weak — it reports whether there is *a* network, not
 * whether this app's API is reachable, so it is false-negative-free but not
 * false-positive-free. That is the right trade for what this is used for: when it says
 * offline, we are certainly offline and can say so instead of spinning. When it says
 * online and the request still fails, the view's existing error state handles it.
 */

import { useEffect, useState } from "react";

export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine);

  useEffect(() => {
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  return online;
}
