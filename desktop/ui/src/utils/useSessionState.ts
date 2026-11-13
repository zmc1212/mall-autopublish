import { useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

function read<T>(key: string, fallback: T): T {
  if (!key) return fallback;
  try {
    const raw = window.sessionStorage.getItem(key);
    if (raw === null) return fallback;
    const value: unknown = JSON.parse(raw);
    if (Array.isArray(fallback)) return Array.isArray(value) && value.every(item => typeof item === "string") ? value as T : fallback;
    if (typeof fallback === "number") return typeof value === "number" && Number.isFinite(value) && value > 0 ? value as T : fallback;
    if (fallback === null) return value === null || typeof value === "string" ? value as T : fallback;
    return typeof value === typeof fallback ? value as T : fallback;
  } catch { return fallback; }
}

/** 按清单保留本次会话的视图位置；切换来源时不把旧状态写入新清单。 */
export function useSessionState<T>(key: string, fallback: T): [T, Dispatch<SetStateAction<T>>] {
  const [snapshot, setSnapshot] = useState(() => ({ key, value: read(key, fallback) }));
  const value = snapshot.key === key ? snapshot.value : read(key, fallback);
  useEffect(() => {
    if (snapshot.key !== key) setSnapshot({ key, value: read(key, fallback) });
  }, [key, snapshot.key]);
  useEffect(() => {
    if (!key || snapshot.key !== key) return;
    try { window.sessionStorage.setItem(key, JSON.stringify(snapshot.value)); }
    catch { /* 会话存储不可用时仍保留当前面板内的操作状态。 */ }
  }, [key, snapshot]);
  const setValue: Dispatch<SetStateAction<T>> = update => setSnapshot(current => {
    const previous = current.key === key ? current.value : read(key, fallback);
    return { key, value: typeof update === "function" ? (update as (value: T) => T)(previous) : update };
  });
  return [value, setValue];
}
