import { CircleAlert } from "lucide-react";

import type { ChromeStatus } from "../types";
import cn from "../utils/classnames";

interface StatusBarProps {
  chrome: ChromeStatus | null;
  loading?: boolean;
  className?: string;
}

function Chip({
  ok,
  label,
  warn = false,
}: {
  ok: boolean;
  label: string;
  warn?: boolean;
}) {
  return (
    <span
      className={cn(
        "inline-flex min-h-8 items-center gap-2 rounded-full border px-3 text-xs",
        {
          "border-emerald-200 bg-emerald-50 text-emerald-800": ok,
          "border-amber-200 bg-amber-50 text-amber-800": !ok && warn,
          "border-slate-200 bg-slate-50 text-slate-600": !ok && !warn,
        },
      )}
    >
      <span
        className={cn("h-2 w-2 rounded-full", {
          "bg-success": ok,
          "bg-warning": !ok && warn,
          "bg-slate-400": !ok && !warn,
        })}
        aria-hidden="true"
      />
      {label}
    </span>
  );
}

export default function StatusBar({ chrome, loading = false, className = "" }: StatusBarProps) {
  if (loading || !chrome) {
    return (
      <div className={cn("flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-white px-6 py-3", className)}>
        <span className="text-sm text-slate-500">正在检测 Chrome 与登录态…</span>
      </div>
    );
  }
  const loggedIn = Boolean(chrome?.logged_in);
  const checking = !loggedIn && Boolean(chrome?.checking);
  const found = Boolean(chrome?.chrome_found);
  return (
    <div
      className={cn(
        "flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-white px-6 py-3",
        className,
      )}
    >
      <Chip ok={found} label={found ? "浏览器已准备" : "浏览器未准备好"} warn={!found} />
      <Chip
        ok={loggedIn}
        label={loggedIn ? "卖家中心已登录" : checking ? "正在自动检测登录状态…" : chrome?.blocker || "待登录"}
        warn={!loggedIn}
      />
      <span className="ml-auto hidden text-xs text-slate-500 lg:inline-flex">
        {checking ? "首次进入会自动检测登录状态" : loggedIn ? "填表过程看执行页进度" : "登录后即可开始"}
      </span>
      {chrome?.blocker && !loggedIn && !checking ? (
        <span className="inline-flex items-center gap-1 text-xs text-amber-700">
          <CircleAlert className="h-3.5 w-3.5" aria-hidden="true" />
          请到弹出窗口完成登录或验证码
        </span>
      ) : null}
    </div>
  );
}
