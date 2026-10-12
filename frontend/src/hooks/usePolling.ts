import { useCallback, useEffect, useRef, useState } from "react";

/** Calls `fn` immediately and then every `intervalMs` while `active` is true. */
export function usePolling<T>(fn: () => Promise<T>, intervalMs: number, active: (data: T | null) => boolean = () => true) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const activeRef = useRef(active);
  activeRef.current = active;

  const refresh = useCallback(async () => {
    try { const d = await fnRef.current(); setData(d); setError(null); return d; }
    catch (e: any) { setError(e?.response?.data?.detail ?? e?.message ?? "Request failed"); return null; }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      const d = await refresh();
      if (!stop && activeRef.current(d)) timer = setTimeout(tick, intervalMs);
    };
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, [refresh, intervalMs]);

  return { data, error, loading, refresh };
}
