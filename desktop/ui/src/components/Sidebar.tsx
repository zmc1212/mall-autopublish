import type { ReactNode } from "react";
import { Cable, FileSpreadsheet, Package, Settings2, LockKeyhole } from "lucide-react";
import cn from "../utils/classnames";
export const NAV_ITEMS = [
  { id: "connect", label: "连接店铺", icon: Cable },
  { id: "workbook", label: "商品清单", icon: FileSpreadsheet },
  { id: "run", label: "执行入库", icon: Package },
  { id: "settings", label: "设置与工具", icon: Settings2 },
] as const;
export type NavId = (typeof NAV_ITEMS)[number]["id"];
export default function Sidebar({ current, onChange, className = "" }: {
  current: NavId; onChange: (id: NavId) => void; className?: string;
}) {
  return <aside className={cn("app-sidebar flex h-full shrink-0 flex-col bg-sidebar", className)}>
    <div className="app-brand">
      <Package className="h-10 w-10 shrink-0 text-primary" strokeWidth={1.65} aria-hidden="true" />
      <div><strong>千牛自动上架</strong><small><span>高效整理商品</span><span>轻松入库</span></small></div>
    </div>
    <nav className="app-nav flex-1" aria-label="功能分区">
      {NAV_ITEMS.map(({ id, label, icon: Icon }) => <button key={id} type="button" onClick={() => onChange(id)} aria-label={label} title={label} aria-current={current === id ? "page" : undefined}>
        <Icon className="h-5 w-5 shrink-0" strokeWidth={1.7} aria-hidden="true" /><span className="app-nav-label">{label}</span>
      </button>)}
    </nav>
    <div className="sidebar-note flex items-center gap-2 px-5 pb-6 text-[11px] text-sidebar-muted">
      <LockKeyhole className="h-4 w-4 shrink-0" aria-hidden="true" /><span><span className="whitespace-nowrap">仅放入仓库，</span><span className="whitespace-nowrap">不自动上架</span></span>
    </div>
  </aside>;
}
export function PanelFrame({ title, hint, actions, children }: { title: string; hint?: string; actions?: ReactNode; children: ReactNode }) {
  return <section className="panel-frame"><header className={cn("panel-heading", Boolean(actions) && "flex flex-wrap items-center justify-between gap-4")}><div className="min-w-0"><h2>{title}</h2>{hint && <p>{hint}</p>}</div>{actions && <div className="max-w-full shrink-0">{actions}</div>}</header>{children}</section>;
}
