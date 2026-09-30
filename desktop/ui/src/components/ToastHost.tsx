import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { useEffect, useSyncExternalStore } from "react";

import cn from "../utils/classnames";
import type { ToastItem, ToastLevel } from "../utils/toasts";
import { dismissToast, getToasts, subscribeToasts, toastAutoDismissMs } from "../utils/toasts";

const LEVEL_ICONS: Record<ToastLevel, typeof Info> = {
  success: CheckCircle2,
  info: Info,
  warning: AlertTriangle,
  error: XCircle,
};

const LEVEL_STYLES: Record<ToastLevel, { box: string; icon: string }> = {
  success: { box: "border-emerald-200", icon: "text-emerald-600" },
  info: { box: "border-slate-200", icon: "text-slate-500" },
  warning: { box: "border-amber-200", icon: "text-amber-600" },
  error: { box: "border-red-200", icon: "text-destructive" },
};

function ToastCard({ toast }: { toast: ToastItem }) {
  const { level, message, id, createdAt } = toast;
  useEffect(() => {
    const timeout = toastAutoDismissMs(level);
    if (!timeout) return undefined;
    const timer = window.setTimeout(() => dismissToast(id), timeout);
    return () => window.clearTimeout(timer);
  }, [createdAt, id, level]);
  const Icon = LEVEL_ICONS[level];
  return (
    <div
      className={cn(
        "toast-item flex w-[min(420px,calc(100vw-2.5rem))] items-start gap-3 rounded-xl border bg-white px-4 py-3 shadow-lg",
        LEVEL_STYLES[level].box,
      )}
      role={level === "error" || level === "warning" ? "alert" : "status"}
    >
      <Icon className={cn("mt-0.5 h-5 w-5 shrink-0", LEVEL_STYLES[level].icon)} aria-hidden="true" />
      <p className="min-w-0 flex-1 break-words text-sm leading-6 text-foreground">{message}</p>
      <button
        type="button"
        className="shrink-0 rounded-md p-1 text-slate-400 transition-colors hover:bg-muted hover:text-foreground"
        aria-label="关闭通知"
        onClick={() => dismissToast(id)}
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}

export default function ToastHost() {
  const items = useSyncExternalStore(subscribeToasts, getToasts, getToasts);
  return (
    <div
      className="pointer-events-none fixed right-5 top-16 z-[60] flex flex-col items-end gap-2"
      role="region"
      aria-label="操作通知"
    >
      {items.map((toast) => (
        <div key={toast.id} className="pointer-events-auto">
          <ToastCard toast={toast} />
        </div>
      ))}
    </div>
  );
}
