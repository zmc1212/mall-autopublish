import { ChevronLeft, ChevronRight, X } from "lucide-react";
import type { ReactNode } from "react";
import { useRef } from "react";

import { useDialogBehavior } from "../utils/dialogFocus";
import { Button } from "../theme";

interface DataTableDialogProps {
  open: boolean;
  title: string;
  description: string;
  total: number;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  onClose: () => void;
  children: ReactNode;
}

export default function DataTableDialog({
  open,
  title,
  description,
  total,
  page,
  pageSize,
  onPageChange,
  onClose,
  children,
}: DataTableDialogProps) {
  const cardRef = useRef<HTMLElement>(null);
  useDialogBehavior(open, onClose, cardRef);

  if (!open) return null;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const currentPage = Math.min(Math.max(page, 1), totalPages);

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
        className="flex max-h-[calc(100dvh-2rem)] w-[min(1180px,calc(100vw-2rem))] min-w-0 flex-col overflow-hidden rounded-2xl border border-border bg-white shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="data-table-dialog-title"
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h2 id="data-table-dialog-title" className="text-lg font-semibold text-foreground">
              {title}
            </h2>
            <p className="mt-1 text-xs text-slate-500">{description}</p>
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
        <div className="data-table-scroll min-h-0 flex-1 overflow-x-scroll overflow-y-hidden overscroll-x-contain">{children}</div>
        <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-3">
          <span className="text-xs text-slate-500">
            共 {total} 条 · 第 {currentPage} / {totalPages} 页 · 每页 {pageSize} 条
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              className="min-h-9 px-3 text-xs"
              disabled={currentPage <= 1}
              onClick={() => onPageChange(currentPage - 1)}
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              上一页
            </Button>
            <Button
              variant="secondary"
              className="min-h-9 px-3 text-xs"
              disabled={currentPage >= totalPages}
              onClick={() => onPageChange(currentPage + 1)}
            >
              下一页
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        </footer>
      </section>
    </div>
  );
}
