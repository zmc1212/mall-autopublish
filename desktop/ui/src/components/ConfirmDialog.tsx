import { AlertTriangle, X } from "lucide-react";
import type { ReactNode } from "react";
import { useRef } from "react";

import { useDialogBehavior } from "../utils/dialogFocus";
import { Button } from "../theme";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

export default function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel = "确定",
  cancelLabel = "取消",
  destructive = false,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  const cardRef = useRef<HTMLElement>(null);
  useDialogBehavior(open, onClose, cardRef);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={cardRef}
        className="w-[min(480px,calc(100vw-2rem))] overflow-hidden rounded-lg border border-border bg-white shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
      >
        <header className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="flex min-w-0 items-start gap-3">
            {destructive ? <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" aria-hidden="true" /> : null}
            <h2 id="confirm-dialog-title" className="text-lg font-semibold text-foreground">
              {title}
            </h2>
          </div>
          <button
            type="button"
            className="shrink-0 rounded-lg p-2 text-slate-500 transition-colors hover:bg-muted hover:text-foreground"
            aria-label="关闭弹窗"
            onClick={onClose}
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </header>
        <div className="px-5 py-4 text-sm leading-6 text-slate-600">{children}</div>
        <footer className="flex justify-end gap-2 border-t border-border px-5 py-4">
          <Button variant="secondary" onClick={onClose}>
            {cancelLabel}
          </Button>
          <Button autoFocus variant={destructive ? "danger" : "primary"} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </footer>
      </section>
    </div>
  );
}
