export type ToastLevel = "success" | "info" | "warning" | "error";

export interface ToastItem {
  id: number;
  level: ToastLevel;
  message: string;
  createdAt: number;
}

const AUTO_DISMISS_MS: Record<ToastLevel, number> = { success: 6000, info: 10000, warning: 12000, error: 0 };
const MAX_TOASTS = 5;

let toasts: ToastItem[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of [...listeners]) listener();
}

export function toastAutoDismissMs(level: ToastLevel) {
  return AUTO_DISMISS_MS[level];
}

export function pushToast(level: ToastLevel, message: string) {
  const latest = toasts[toasts.length - 1];
  if (latest && latest.level === level && latest.message === message) {
    // 相同通知只刷新计时，不重复堆叠
    toasts = toasts.map((item) => (item.id === latest.id ? { ...item, createdAt: Date.now() } : item));
  } else {
    toasts = [...toasts, { id: nextId++, level, message, createdAt: Date.now() }].slice(-MAX_TOASTS);
  }
  emit();
}

export function dismissToast(id: number) {
  if (!toasts.some((item) => item.id === id)) return;
  toasts = toasts.filter((item) => item.id !== id);
  emit();
}

export function subscribeToasts(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getToasts() {
  return toasts;
}
