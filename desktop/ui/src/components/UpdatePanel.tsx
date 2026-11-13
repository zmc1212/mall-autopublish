import { Download, FolderOpen, Loader2, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, nativePick } from "../api";
import { Button, InputText } from "../theme";
import type { UpdateState } from "../types";
import { pushToast } from "../utils/toasts";

import ConfirmDialog from "./ConfirmDialog";

const TRACKING = new Set(["checking", "downloading", "preparing", "waiting", "restarting"]);

const STATUS_LABELS: Record<string, string> = {
  checking: "检查中",
  downloading: "下载中",
  preparing: "准备安装",
  waiting: "等待重启",
  restarting: "正在重启",
  available: "有新版本",
  ready: "可以更新",
  current: "已是最新",
  up_to_date: "已是最新",
  success: "更新成功",
  rolled_back: "已恢复旧版本",
  rollback_failed: "恢复未完成",
  idle: "尚未检查",
  error: "检查失败",
};

export default function UpdatePanel({ update }: { update: UpdateState | null }) {
  const [feed, setFeed] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [pending, setPending] = useState(false);
  const [confirmRestart, setConfirmRestart] = useState(false);
  const [localState, setLocalState] = useState<UpdateState | null>(null);
  const [stateError, setStateError] = useState("");
  const hydrated = useRef(false);

  useEffect(() => {
    if (update && !hydrated.current) {
      hydrated.current = true;
      setFeed(update.feed_url);
    }
    // 主状态可能缓存了检查前的结果，操作期间以更新专用接口为准。
    setLocalState((current) => current && TRACKING.has(current.status) ? current : null);
  }, [update]);

  const state = localState ?? update;

  useEffect(() => {
    if (pending || !TRACKING.has(state?.status ?? "")) return;
    let stopped = false;
    let timer = 0;
    const refresh = async () => {
      try {
        const next = await api.updateState();
        if (!stopped) {
          setLocalState(next);
          setStateError("");
        }
      } catch (error) {
        if (!stopped) setStateError("读取更新状态失败，正在重试：" + (error instanceof Error ? error.message : String(error)));
      } finally {
        if (!stopped) timer = window.setTimeout(() => void refresh(), 1000);
      }
    };
    timer = window.setTimeout(() => void refresh(), 250);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [pending, state?.status]);

  const working = pending || ["checking", "downloading", "preparing", "restarting"].includes(state?.status ?? "");
  const waiting = state?.status === "waiting";
  const run = async (action: () => Promise<UpdateState>) => {
    setStateError("");
    setPending(true);
    try {
      setLocalState(await action());
    } catch (error) {
      pushToast("error", error instanceof Error ? error.message : String(error));
    } finally {
      setPending(false);
    }
  };

  const statusLabel = state?.status ? (STATUS_LABELS[state.status] ?? state.status) : "尚未检查";
  const statusTone = state?.status === "available" || state?.status === "ready"
    ? "bg-emerald-50 text-emerald-700"
    : state?.status === "error"
      ? "bg-red-50 text-red-700"
      : "bg-muted text-slate-600";

  return (
    <article className="rounded-xl border border-border bg-white p-4" data-testid="app-update">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-primary">
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <h3 className="text-sm font-semibold text-foreground">程序更新</h3>
            <p className="mt-1 break-words text-xs leading-5 text-slate-500">
              当前版本 {state?.current_version || "读取中…"}。校验完成后可立即重启安装，也可等当前任务结束、结果保存后自动重启；保留登录态和设置，新版启动失败会自动回滚。
            </p>
          </div>
        </div>
        <span className={"rounded-full px-2.5 py-1 text-xs font-medium " + statusTone} role="status">
          {statusLabel}
        </span>
      </div>

      <div className="mt-4 rounded-lg border border-border bg-muted/60 p-3">
        <label className="block text-sm font-medium text-foreground" htmlFor="update-feed">更新地址</label>
        <div className="mt-2 flex flex-wrap gap-2">
          <InputText
            id="update-feed"
            className="min-w-0 flex-1"
            value={feed}
            placeholder="https://下载域名/latest.json"
            disabled={working || waiting}
            onChange={(event) => setFeed(event.target.value)}
          />
          <Button
            variant="secondary"
            disabled={working || waiting}
            onClick={() => void run(async () => {
              await api.saveSettings({ update_feed_url: feed.trim() });
              if (!feed.trim()) {
                pushToast("success", "已清除更新地址，仍可导入本地更新包");
                return api.updateState();
              }
              return api.checkUpdate();
            })}
          >
            {working ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <RefreshCw className="h-4 w-4" aria-hidden="true" />}
            保存地址并检查
          </Button>
        </div>
        <p className="mt-2 text-xs leading-5 text-slate-500">填写发布方提供的版本信息地址；配置后每次启动会自动检查。</p>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {state?.status === "available" ? (
          <Button disabled={working} onClick={() => void run(api.downloadUpdate)}>
            <Download className="h-4 w-4" aria-hidden="true" />下载 {state.version}
          </Button>
        ) : null}
        {state?.status === "ready" || waiting ? (
          <Button disabled={working || !state?.can_restart} onClick={() => setConfirmRestart(true)}>
            {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <RefreshCw className="h-4 w-4" aria-hidden="true" />}
            立即重启更新
          </Button>
        ) : null}
        {state?.status === "ready" ? (
          <Button variant="secondary" disabled={working || !state.can_restart} onClick={() => void run(api.scheduleUpdate)}>
            任务结束后重启更新
          </Button>
        ) : null}
        {waiting ? <Button variant="secondary" disabled={pending} onClick={() => void run(api.cancelUpdate)}>取消自动重启</Button> : null}
      </div>

      {state?.message ? <p className="mt-3 break-words text-sm text-slate-700" role="status">{state.message}</p> : null}
      {state?.status === "downloading" ? (
        <div className="mt-3 rounded-lg border border-border bg-muted/60 p-3">
          <div className="flex items-center justify-between text-xs text-slate-600">
            <span>下载进度</span>
            <span className="font-medium tabular-nums text-foreground">{state.progress}%</span>
          </div>
          <progress className="mt-2 h-2 w-full accent-primary" max={100} value={state.progress} aria-label="更新下载进度" />
        </div>
      ) : null}
      {state?.notes ? <p className="mt-3 break-words whitespace-pre-wrap text-xs leading-5 text-slate-500">{state.notes}</p> : null}
      {state?.error || stateError ? <p className="mt-3 break-words rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700" role="alert">{state?.error || stateError}</p> : null}
      {state && !state.can_restart ? <p className="mt-3 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">当前为源码开发模式，可检查和校验更新；自动替换及重启在安装后的客户端启用。</p> : null}

      <div className="mt-4 border-t border-border pt-4">
        <label className="block text-sm font-medium text-foreground" htmlFor="local-update-path">本地更新 ZIP</label>
        <div className="mt-2 flex flex-wrap gap-2">
          <InputText
            id="local-update-path"
            className="min-w-40 flex-1"
            value={localPath}
            placeholder="选择更新 ZIP，或填写完整路径"
            disabled={working || waiting}
            onChange={(event) => setLocalPath(event.target.value)}
          />
          <Button
            variant="secondary"
            disabled={working || waiting}
            onClick={async () => {
              try {
                const picked = await nativePick("pick_update");
                if (picked) setLocalPath(picked);
                else if (!window.pywebview?.api) pushToast("info", "请在左侧填写更新 ZIP 的完整路径");
              } catch (error) {
                pushToast("error", error instanceof Error ? error.message : String(error));
              }
            }}
          >
            <FolderOpen className="h-4 w-4" aria-hidden="true" />选择 ZIP
          </Button>
          <Button
            variant="secondary"
            disabled={working || waiting || !localPath.trim()}
            onClick={() => void run(() => api.importUpdate(localPath.trim()))}
          >
            校验并导入
          </Button>
        </div>
      </div>

      <ConfirmDialog
        open={confirmRestart}
        title="立即重启更新"
        destructive
        confirmLabel="立即重启更新"
        cancelLabel="取消"
        onConfirm={() => {
          setConfirmRestart(false);
          void run(api.restartUpdateNow);
        }}
        onClose={() => setConfirmRestart(false)}
      >
        将立即关闭程序并安装版本 {state?.version || ""}。正在执行的任务会被中断，已完成条目会保留，未完成条目可在重启后继续。确定继续吗？
      </ConfirmDialog>
    </article>
  );
}
