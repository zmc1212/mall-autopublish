import type { ReactNode } from "react";
import { Cable, FileSpreadsheet, Play, Settings } from "lucide-react";

import cn from "../utils/classnames";

export const NAV_ITEMS = [
  { id: "connect", label: "连接", icon: Cable },
  { id: "workbook", label: "清单", icon: FileSpreadsheet },
  { id: "run", label: "执行", icon: Play },
  { id: "settings", label: "设置", icon: Settings },
] as const;

export type NavId = (typeof NAV_ITEMS)[number]["id"];

interface SidebarProps {
  current: NavId;
  onChange: (id: NavId) => void;
  className?: string;
}

export default function Sidebar({ current, onChange, className = "" }: SidebarProps) {
  return (
    <aside
      className={cn(
        "flex h-full w-56 shrink-0 flex-col bg-sidebar text-white",
        className,
      )}
    >
      <div className="border-b border-white/10 px-5 py-6">
        <p className="text-xs tracking-widest text-sidebar-muted">SELLER TOOLS</p>
        <h1 className="mt-1 text-lg font-semibold">千牛自动上架</h1>
        <p className="mt-2 text-xs leading-5 text-sidebar-muted">
          选择工作空间，校验后放入仓库。不会立刻上架。
        </p>
      </div>
      <nav className="flex flex-1 flex-col gap-1 p-3" aria-label="功能分区">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = current === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onChange(item.id)}
              className={cn(
                "flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm transition-colors duration-150",
                {
                  "bg-white/10 text-white": active,
                  "text-sidebar-muted hover:bg-white/5 hover:text-white": !active,
                },
              )}
              aria-current={active ? "page" : undefined}
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
              {item.label}
            </button>
          );
        })}
      </nav>
      <p className="px-5 py-4 text-xs text-sidebar-muted">本机控制面板 · 仅连接本机 Chrome</p>
    </aside>
  );
}

export function PanelFrame({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-hidden [@media(min-height:840px)]:gap-4">
      <header className="shrink-0">
        <h2 className="text-xl font-semibold">{title}</h2>
        {hint ? <p className="mt-1 line-clamp-2 text-sm text-slate-500" title={hint}>{hint}</p> : null}
      </header>
      {children}
    </section>
  );
}
