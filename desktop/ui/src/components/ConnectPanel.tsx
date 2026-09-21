import { ExternalLink, MonitorUp } from "lucide-react";

import { Button } from "../theme";
import type { ChromeStatus } from "../types";

import { PanelFrame } from "./Sidebar";

interface ConnectPanelProps {
  chrome: ChromeStatus | null;
  busy: boolean;
  notice?: string;
  onOpen: () => void;
  onRevealProfile: () => void;
  className?: string;
}

export default function ConnectPanel({
  chrome,
  busy,
  notice = "",
  onOpen,
  onRevealProfile,
  className = "",
}: ConnectPanelProps) {
  const loggedIn = Boolean(chrome?.logged_in);
  return (
    <PanelFrame
      title="连接千牛窗口"
      hint="未登录才弹出浏览器；登录后窗口会收起，填表过程请看执行页进度和结果。登录只需一次，保存在本机用户目录。"
    >
      <div className={`grid min-h-0 flex-1 gap-4 overflow-auto lg:grid-cols-2 ${className}`}>
        <article className="rounded-2xl border border-border bg-white p-5">
          <h3 className="text-sm font-semibold">使用步骤</h3>
          <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm leading-6 text-slate-600">
            <li>本机已安装 Google Chrome。</li>
            <li>未登录时点击「登录卖家中心」，在弹出窗口登录一次；已登录不会弹窗。</li>
            <li>登录后浏览器会收起，填表过程看执行页进度。选择工作空间一次即可，下次打开会自动恢复。</li>
            <li>出现登录页或验证码时，任务会暂停并再次弹出浏览器。</li>
          </ol>
          <div className="mt-5 flex flex-wrap gap-2">
            <Button onClick={onOpen} disabled={busy}>
              <MonitorUp className="h-4 w-4" aria-hidden="true" />
              {busy ? "正在打开…" : loggedIn ? "已登录，窗口已收起" : "登录卖家中心"}
            </Button>
            <Button variant="secondary" onClick={onRevealProfile} disabled={!chrome?.profile}>
              <ExternalLink className="h-4 w-4" aria-hidden="true" />
              打开登录目录
            </Button>
          </div>
          {notice ? (
            <p className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{notice}</p>
          ) : null}
        </article>
        <article className="rounded-2xl border border-border bg-white p-5 text-sm">
          <h3 className="text-sm font-semibold">当前状态</h3>
          <dl className="mt-3 space-y-2 text-slate-600">
            <div className="flex justify-between gap-4">
              <dt>Chrome</dt>
              <dd className="truncate text-right">{chrome?.chrome_path || "未探测到"}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt>调试端口</dt>
              <dd>{chrome?.cdp_port || 9222}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt>浏览器</dt>
              <dd>{chrome?.browser || "未连接"}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt>卖家中心</dt>
              <dd>{loggedIn ? "已登录" : chrome?.blocker || "待登录"}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt>Playwright CLI</dt>
              <dd>{chrome?.cli_js_found ? "已就绪" : "未找到"}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt>Node</dt>
              <dd className="truncate text-right">{chrome?.node_found ? chrome.node : "未找到"}</dd>
            </div>
          </dl>
        </article>
      </div>
    </PanelFrame>
  );
}
