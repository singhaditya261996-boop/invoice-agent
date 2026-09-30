import { useCallback, useEffect, useRef, useState } from "react";

/** Minimal hash router: "#/batches/B-1/invoices/DOC-0001" -> ["batches", "B-1", "invoices", "DOC-0001"]. */
export function useRoute(): string[] {
  const read = () => window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  const [parts, setParts] = useState(read);
  useEffect(() => {
    const onChange = () => {
      setParts(read());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return parts;
}

export function href(...parts: string[]): string {
  return `#/${parts.map(encodeURIComponent).join("/")}`;
}

export interface AsyncState<T> {
  data: T | undefined;
  error: string | undefined;
  loading: boolean;
  reload: () => void;
}

/** Fetch on mount and whenever deps change; optionally poll while `poll` returns true. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[], poll?: (data: T) => boolean): AsyncState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const pollRef = useRef(poll);
  pollRef.current = poll;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = () => {
      fnRef.current().then(
        (d) => {
          if (cancelled) return;
          setData(d);
          setError(undefined);
          setLoading(false);
          if (pollRef.current?.(d)) timer = setTimeout(run, 1000);
        },
        (e: Error) => {
          if (cancelled) return;
          setError(e.message);
          setLoading(false);
        },
      );
    };
    setLoading(true);
    run();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

/** A value persisted per browser (e.g. the analyst's name). Storage can be unavailable; fail soft. */
export function useStoredState(key: string, initial: string): [string, (v: string) => void] {
  const [value, setValue] = useState(() => {
    try {
      return localStorage.getItem(key) ?? initial;
    } catch {
      return initial;
    }
  });
  const set = (v: string) => {
    setValue(v);
    try {
      localStorage.setItem(key, v);
    } catch {
      /* private mode etc. */
    }
  };
  return [value, set];
}
