import { useEffect, useState } from "react";

import * as api from "@/lib/api";
import type { LearnConstants } from "@/lib/api";

/* The live tuning values, fetched once and kept for the session.
 *
 * Cached at module scope rather than in state: the numbers cannot change while the tab is
 * open (they come from server configuration, which changes on deploy), so re-fetching on
 * every visit to the page would be a request that can only ever return the same answer.
 *
 * **Fails soft on purpose.** If the fetch does not work, the section still renders — the
 * explanations are the point, and the numbers are enrichment. A page of text held hostage
 * by one small request would be a worse failure than a missing figure.
 */

let cached: LearnConstants | null = null;
let inflight: Promise<LearnConstants> | null = null;

export function useLearnConstants(): { constants: LearnConstants | null; failed: boolean } {
  const [constants, setConstants] = useState<LearnConstants | null>(cached);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (cached) return;
    let alive = true;
    inflight ??= api.getLearnConstants();
    inflight
      .then((value) => {
        cached = value;
        if (alive) setConstants(value);
      })
      .catch(() => {
        inflight = null; // let a later visit try again
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  return { constants, failed };
}
