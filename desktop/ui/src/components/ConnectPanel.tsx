import { Loader2, MonitorUp } from "lucide-react";

import { Button } from "../theme";
import type { ChromeStatus } from "../types";

import { PanelFrame } from "./Sidebar";

interface ConnectPanelProps {
  chrome: ChromeStatus | null;
  busy: boolean;
  onOpen: () => void;
  className?: string;
}

export default function ConnectPanel({
  chrome,
  busy,
  onOpen,
  className = "",
}: ConnectPanelProps) {
  const loggedIn = Boolean(chrome?.logged_in);
  const checking = !loggedIn && Boolean(chrome?.checking);
  return (
    <PanelFrame
      title="连接千牛窗口"
      hint="首次使用登录一次即可。登录后按“设置”中的显示开关处理窗口，填表过程请看执行页进度和结果。"
    >
      <div className={`grid min-h-0 flex-1 gap-4 overflow-auto lg:grid-cols-2 ${className}`}>
        <article className="rounded-2xl border border-border bg-white p-5">
          <h3 className="text-sm font-semibold">使用步骤</h3>
          <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm leading-6 text-slate-600">
            <li>程序已内置自动化浏览器，无需另外安装 Google Chrome。</li>
            <li>启动时会自动检测登录状态：浏览器里保存过登录记录时直接显示「已登录」；未登录时点击「登录卖家中心」，在弹出窗口登录一次即可。</li>
            <li>登录后按“设置”中的显示开关处理浏览器窗口；默认收起。选择工作空间一次即可，下次打开会自动恢复。</li>
            <li>出现登录页或验证码时，任务会暂停并再次弹出浏览器。</li>
          </ol>
          <div className="mt-5 flex flex-wrap gap-2">
            <Button onClick={onOpen} disabled={busy}>
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <MonitorUp className="h-4 w-4" aria-hidden="true" />
              )}
              {busy
                ? "正在打开…"
                : loggedIn
                  ? chrome?.debug_browser
                    ? "已登录，窗口保持显示"
                    : "已登录，窗口已收起"
                  : "登录卖家中心"}
            </Button>
          </div>
        </article>
        <article className="rounded-2xl border border-border bg-white p-5 text-sm">
          <h3 className="text-sm font-semibold">连接状态</h3>
          <dl className="mt-3 space-y-2 text-slate-600">
            <div className="flex justify-between gap-4">
              <dt>浏览器</dt>
              <dd>{chrome?.chrome_found ? "已准备" : "未准备好"}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt>卖家中心</dt>
              <dd>{loggedIn ? "已登录" : checking ? "正在自动检测…" : chrome?.blocker || "待登录"}</dd>
            </div>
          </dl>
        </article>
      </div>
    </PanelFrame>
  );
}
