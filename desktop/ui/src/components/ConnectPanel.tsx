import { ArrowRight, CheckCircle2, CircleAlert, Clock3, Loader2, MonitorUp } from "lucide-react";

import { Button } from "../theme";
import type { ChromeStatus } from "../types";

import { PanelFrame } from "./Sidebar";

interface ConnectPanelProps {
  chrome: ChromeStatus | null;
  busy: boolean;
  onOpen: () => void;
  onContinue?: () => void;
  className?: string;
}

export default function ConnectPanel({
  chrome,
  busy,
  onOpen,
  onContinue,
  className = "",
}: ConnectPanelProps) {
  const browserReady = Boolean(chrome?.chrome_found);
  const loggedIn = Boolean(chrome?.logged_in);
  const checking = !loggedIn && Boolean(chrome?.checking);
  const blocker = chrome?.blocker || chrome?.error || "";
  const connectionReady = browserReady && loggedIn;
  const connectionLabel = checking ? "正在检测" : connectionReady ? "已连接" : browserReady ? "需要登录" : "等待浏览器";
  return (
    <PanelFrame
      title="连接店铺"
      hint="确认浏览器已登录后，下一步准备商品清单。"
    >
      <div className={`flex min-h-0 flex-1 flex-col gap-3 overflow-auto ${className}`}>
        <section className="shrink-0 rounded-xl border border-border bg-white">
          <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-4">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.12em] text-primary">连接状态</p>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <h3 className="text-lg font-semibold text-foreground">千牛卖家中心</h3>
                <span
                  className={
                    connectionReady
                      ? "inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700"
                      : checking
                        ? "inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700"
                        : "inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800"
                  }
                >
                  <span className={connectionReady ? "h-1.5 w-1.5 rounded-full bg-emerald-500" : checking ? "h-1.5 w-1.5 rounded-full bg-blue-500" : "h-1.5 w-1.5 rounded-full bg-amber-500"} aria-hidden="true" />
                  {connectionLabel}
                </span>
              </div>
              <p className="mt-1 text-xs text-slate-500">
                {connectionReady ? "可以继续准备商品清单。" : checking ? "正在读取浏览器登录状态，请稍候。" : "首次使用只需在弹出的内置浏览器中登录一次。"}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button onClick={onOpen} disabled={busy}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <MonitorUp className="h-4 w-4" aria-hidden="true" />}
                {busy
                  ? "正在打开…"
                  : loggedIn
                    ? chrome?.debug_browser
                      ? "保持窗口显示"
                      : "打开浏览器窗口"
                    : "登录卖家中心"}
              </Button>
              {onContinue ? (
                <Button variant="secondary" onClick={onContinue} disabled={!connectionReady || busy}>
                  下一步：商品清单
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </Button>
              ) : null}
            </div>
          </div>
          <div className="grid border-t border-border sm:grid-cols-2">
            <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3 text-sm sm:border-b-0 sm:border-r">
              <span className="text-slate-500">内置浏览器</span>
              <span className={browserReady ? "inline-flex items-center gap-1.5 font-medium text-emerald-700" : "inline-flex items-center gap-1.5 font-medium text-amber-800"}>
                {browserReady ? <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> : <CircleAlert className="h-4 w-4" aria-hidden="true" />}
                {browserReady ? "已准备" : "未准备好"}
              </span>
            </div>
            <div className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
              <span className="text-slate-500">卖家中心</span>
              <span className={loggedIn ? "inline-flex items-center gap-1.5 font-medium text-emerald-700" : checking ? "inline-flex items-center gap-1.5 font-medium text-blue-700" : "inline-flex items-center gap-1.5 font-medium text-amber-800"}>
                {loggedIn ? <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> : checking ? <Clock3 className="h-4 w-4" aria-hidden="true" /> : <CircleAlert className="h-4 w-4" aria-hidden="true" />}
                {loggedIn ? "已登录" : checking ? "自动检测中" : blocker || "待登录"}
              </span>
            </div>
          </div>
          {blocker && !loggedIn ? (
            <p className="mx-4 mb-4 rounded-lg bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">{blocker}</p>
          ) : null}
        </section>

        <div className="grid shrink-0 gap-3 lg:grid-cols-[minmax(0,1.05fr)_minmax(300px,0.95fr)]">
          <section className="rounded-xl border border-border bg-white p-4">
            <h3 className="text-base font-semibold text-foreground">首次使用</h3>
            <p className="mt-1 text-xs leading-5 text-slate-500">首次使用按以下步骤完成连接。</p>
            <ol className="mt-4 space-y-3">
              <li className="flex gap-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-sm font-semibold text-primary">1</span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground">打开内置浏览器</p>
                  <p className="mt-0.5 text-xs leading-5 text-slate-500">程序会自动准备浏览器和登录环境。</p>
                </div>
              </li>
              <li className="flex gap-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-sm font-semibold text-primary">2</span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground">登录卖家中心</p>
                  <p className="mt-0.5 text-xs leading-5 text-slate-500">未登录时在弹出窗口完成登录；登录记录会保留。</p>
                </div>
              </li>
              <li className="flex gap-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-sm font-semibold text-primary">3</span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground">进入商品清单</p>
                  <p className="mt-0.5 text-xs leading-5 text-slate-500">选择目录或 Excel，校验完成后再进入执行入库。</p>
                </div>
              </li>
            </ol>
          </section>

          <section className="rounded-xl border border-border bg-white p-4">
            <h3 className="text-base font-semibold text-foreground">使用提醒</h3>
            <div className="mt-3 space-y-3 text-xs leading-5 text-slate-600">
              <p>浏览器窗口默认可以收起；需要处理登录页或验证码时，任务会暂停并再次显示窗口。</p>
              <p>执行结果会在执行入库页面查看。当前模式只把商品提交到仓库，不会自动上架。</p>
              {chrome?.notice ? <p className="rounded-lg bg-muted px-3 py-2 text-slate-600">{chrome.notice}</p> : null}
            </div>
          </section>
        </div>
      </div>
    </PanelFrame>
  );
}
