import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/hooks/useToast";

/* Instant UI for list mutations, with the rollback that makes it honest.
 *
 * The app previously did `await create(); load();` — a full refetch after every
 * change, so the UI waited on a network round-trip before reflecting your own click.
 *
 * The rollback is not optional. An optimistic update WITHOUT a revert path shows state
 * the server rejected, which is strictly worse than a slow-but-truthful refetch: the
 * user is told their change succeeded when it did not.
 */

export type ListStatus = "loading" | "ready" | "error";

type Mutation<T> = {
  /** Pure transform applied immediately. Must not mutate the input array. */
  optimistic: (items: T[]) => T[];
  /** The network call. Resolve to reconcile, reject to roll back. */
  request: () => Promise<unknown>;
  /** Message shown (and rolled back to) if `request` rejects. */
  errorMessage: string;
  /** Applied on success, e.g. to swap a temp id for the server's real record. */
  reconcile?: (items: T[], result: unknown) => T[];
};

export function useOptimisticList<T>(load: () => Promise<T[]>, deps: unknown[] = []) {
  const [items, setItems] = useState<T[]>([]);
  const [status, setStatus] = useState<ListStatus>("loading");
  const toast = useToast();

  // Guards against a slow earlier request overwriting a newer one's result.
  const requestId = useRef(0);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const reload = useCallback(async () => {
    const id = ++requestId.current;
    setStatus("loading");
    try {
      const next = await load();
      if (!alive.current || id !== requestId.current) return;
      setItems(next);
      setStatus("ready");
    } catch {
      if (!alive.current || id !== requestId.current) return;
      // Deliberately NOT an empty list: "we couldn't load this" and "you have
      // nothing" must never look the same.
      setStatus("error");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    void reload();
  }, [reload]);

  const mutate = useCallback(
    async ({ optimistic, request, errorMessage, reconcile }: Mutation<T>) => {
      let snapshot: T[] = [];
      setItems((current) => {
        snapshot = current;
        return optimistic(current);
      });
      try {
        const result = await request();
        if (!alive.current) return true;
        if (reconcile) setItems((current) => reconcile(current, result));
        return true;
      } catch {
        if (!alive.current) return false;
        setItems(snapshot); // put it back exactly as it was
        toast.error(errorMessage);
        return false;
      }
    },
    [toast],
  );

  /** Replace one item by id — used after an edit resolves. */
  const replace = useCallback((match: (item: T) => boolean, next: T) => {
    setItems((current) => current.map((i) => (match(i) ? next : i)));
  }, []);

  return { items, setItems, status, reload, mutate, replace };
}
