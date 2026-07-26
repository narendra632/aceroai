import { useCallback, useEffect, useRef, useState } from "react";

// Reveals streamed text at a steady, readable pace regardless of how the network
// chunks arrive — so a reply that lands in one big chunk still "types out".
// Speed adapts up when the backlog grows, so we never fall far behind, and
// flushes fully when the stream ends.
export function useSmoothReveal() {
  const [text, setText] = useState("");
  const pending = useRef("");
  const shown = useRef("");
  const done = useRef(false);
  const raf = useRef<number | null>(null);
  const last = useRef(0);
  const onComplete = useRef<((full: string) => void) | null>(null);

  const stop = () => {
    if (raf.current != null) cancelAnimationFrame(raf.current);
    raf.current = null;
  };

  const loop = useCallback((now: number) => {
    const dt = last.current ? (now - last.current) / 1000 : 0;
    last.current = now;

    if (pending.current.length > 0) {
      const cps = 90 * (1 + pending.current.length / 60); // accelerate on backlog
      const n = Math.min(Math.max(1, Math.floor(cps * dt) || 1), pending.current.length);
      shown.current += pending.current.slice(0, n);
      pending.current = pending.current.slice(n);
      setText(shown.current);
      raf.current = requestAnimationFrame(loop);
    } else if (!done.current) {
      raf.current = requestAnimationFrame(loop); // idle, waiting for more
    } else {
      stop();
      const cb = onComplete.current;
      onComplete.current = null;
      cb?.(shown.current);
    }
  }, []);

  const begin = useCallback(() => {
    stop();
    pending.current = "";
    shown.current = "";
    done.current = false;
    last.current = 0;
    setText("");
    raf.current = requestAnimationFrame(loop);
  }, [loop]);

  const push = useCallback((delta: string) => {
    pending.current += delta;
  }, []);

  const finish = useCallback((cb: (full: string) => void) => {
    onComplete.current = cb;
    done.current = true;
  }, []);

  // hard stop (user pressed Stop): keep what's shown, drop the rest
  const cancel = useCallback((): string => {
    stop();
    done.current = true;
    onComplete.current = null;
    pending.current = "";
    return shown.current;
  }, []);

  useEffect(() => () => stop(), []);

  return { text, begin, push, finish, cancel };
}
