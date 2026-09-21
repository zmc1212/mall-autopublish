import { FileOutput, PauseCircle, Play } from "lucide-react";

import { Button, InputText } from "../theme";
import type { JobState, WorkbookRow } from "../types";
import cn from "../utils/classnames";

import ProductItemId from "./ProductItemId";
import { PanelFrame } from "./Sidebar";

interface RunPanelProps {
  job: JobState | null;
  confirmSubmit: boolean;
  forceNew: boolean;
  retryFailed: boolean;
  limit: string;
  busy: boolean;
  onConfirmSubmit: (value: boolean) => void;
  onForceNew: (value: boolean) => void;
  onRetryFailed: (value: boolean) => void;
  onLimit: (value: string) => void;
  onStart: () => void;
  onStop: () => void;
  onOpenResult: () => void;
  onOpenItem: (row: WorkbookRow, action: "view" | "edit") => void;
  className?: string;
}

export default function RunPanel({
  job,
  confirmSubmit,
  forceNew,
  retryFailed,
  limit,
  busy,
  onConfirmSubmit,
  onForceNew,
  onRetryFailed,
  onLimit,
  onStart,
  onStop,
  onOpenResult,
  onOpenItem,
  className = "",
}: RunPanelProps) {
  const running = job?.status === "running" || job?.status === "stopping";
  const total = job?.total || job?.valid || 0;
  const done = job?.done || 0;
  const percent = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const canResume = Boolean(job?.can_resume) || (job?.rows || []).some(
    (row) => row.validation === "通过" && (row.execution === "失败" || row.execution === "暂停" || row.execution === "已停止"),
  );
  const pending = job?.pending ?? job?.valid ?? 0;
  const startLabel = retryFailed ? "重试失败项" : forceNew ? "从头新建" : canResume ? "继续入库" : "开始入库";
  const validRows = (job?.rows || []).filter((row) => row.validation === "通过");
  const batchHint = validRows.length > 1
    ? "本批超过一条时：第一条可接着当前发布页，之后每条都会新开类目页，避免写到上一款上。"
    : "默认接着上次未填完的发布页。已填完的商品会跳过。勾选「从头新建」才会新开类目页重填。";
  return (
    <PanelFrame
      title="执行入库"
      hint={`${batchHint} 默认不点提交、只入仓库。`}
    >
      <div
        className={`grid min-h-0 min-w-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(220px,300px)] grid-rows-[minmax(0,1fr)] gap-4 overflow-hidden ${className}`}
      >
        <div className="grid h-full min-h-0 min-w-0 grid-rows-[minmax(0,min(36dvh,46%))_minmax(0,1fr)] gap-3 overflow-hidden">
          <article className="min-h-0 overflow-y-auto rounded-2xl border border-border bg-white p-3">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="text-sm text-slate-500">可通过校验</p>
                <p className="text-2xl font-semibold">{job?.valid || 0} 条</p>
                {pending < (job?.valid || 0) ? (
                  <p className="mt-1 text-xs text-slate-500">待入库 {pending} 条，已填完的会跳过</p>
                ) : null}
              </div>
              <label className="text-sm">
                本次上限
                <InputText
                  className="mt-1 w-28"
                  inputMode="numeric"
                  value={limit}
                  onChange={(event) => onLimit(event.target.value)}
                  placeholder="全部"
                  disabled={running}
                />
              </label>
            </div>
            <p className="mt-2 text-sm text-slate-500">
              当前步骤：{job?.phase || "未开始"}
              {job?.current_id ? ` · ${job.current_id}` : ""}
            </p>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
              <div className="h-full bg-primary transition-all duration-200" style={{ width: `${percent}%` }} />
            </div>
            <p className="mt-2 text-xs text-slate-400">
              {running ? `${done} / ${total}` : job?.status === "done" ? "本批已结束" : "等待开始"}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button onClick={onStart} disabled={busy || running || !job?.valid}>
                <Play className="h-4 w-4" aria-hidden="true" />
                {startLabel}
              </Button>
              <Button variant="secondary" onClick={onStop} disabled={!running}>
                <PauseCircle className="h-4 w-4" aria-hidden="true" />
                停止（当前条结束后）
              </Button>
              <Button variant="ghost" onClick={onOpenResult} disabled={!job?.result_xlsx}>
                <FileOutput className="h-4 w-4" aria-hidden="true" />
                打开结果 Excel
              </Button>
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <label className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-2.5 text-sm text-amber-950">
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4 shrink-0 accent-orange-600"
                  checked={confirmSubmit}
                  disabled={running}
                  onChange={(event) => onConfirmSubmit(event.target.checked)}
                />
                <span>
                  <strong className="font-semibold">确认提交到仓库</strong>
                  <span className="mt-1 block text-xs leading-5 text-amber-800">
                    勾选后才会点击「提交宝贝信息」，不会立刻上架。
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-2.5 text-sm text-slate-800">
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4 shrink-0 accent-orange-600"
                  checked={forceNew}
                  disabled={running}
                  onChange={(event) => onForceNew(event.target.checked)}
                />
                <span>
                  <strong className="font-semibold">从头新建</strong>
                  <span className="mt-1 block text-xs leading-5 text-slate-600">
                    关闭时第一条可接着已打开的发布页；勾选后每条都新开类目页。两条以上时，下一条本来就会新开页。
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-2.5 text-sm text-slate-800 sm:col-span-2">
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4 shrink-0 accent-orange-600"
                  checked={retryFailed}
                  disabled={running}
                  onChange={(event) => onRetryFailed(event.target.checked)}
                />
                <span>
                  <strong className="font-semibold">只重试失败 / 暂停 / 已停止</strong>
                  <span className="mt-1 block text-xs leading-5 text-slate-600">
                    已填完的商品仍会跳过，只把失败项再跑一遍。
                  </span>
                </span>
              </label>
            </div>
            {job?.blocker ? (
              <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
                任务已暂停：{job.blocker}。请到 Chrome 处理登录或验证码后再开始。
              </p>
            ) : null}
          </article>
          <article className="min-h-0 overflow-auto rounded-2xl border border-border bg-white">
            <table className="w-full table-fixed text-left text-sm">
              <thead className="sticky top-0 z-10 bg-slate-50 text-slate-500">
                <tr>
                  <th className="w-[24%] px-4 py-3 font-medium">商品</th>
                  <th className="w-[25%] px-4 py-3 font-medium">淘宝商品ID</th>
                  <th className="w-[18%] px-4 py-3 font-medium">执行</th>
                  <th className="px-4 py-3 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {validRows.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-10 text-center text-slate-400">
                      校验通过的商品会显示在这里
                    </td>
                  </tr>
                ) : (
                  validRows.map((row) => (
                    <tr key={`run-${row.row}`} className="border-t border-border">
                      <td className="truncate px-4 py-3" title={row.product_id}>
                        {row.product_id}
                        <span className="ml-2 text-xs text-slate-400">第{row.row}行</span>
                      </td>
                      <td className="px-4 py-2">
                        <ProductItemId value={row.taobao_item_id} />
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={cn("inline-block max-w-full truncate rounded-full px-2.5 py-1 text-xs", {
                            "bg-emerald-50 text-emerald-700": row.execution === "已填写未提交" || row.execution === "结果待核实",
                            "bg-amber-50 text-amber-800": row.execution === "暂停" || row.execution === "已停止",
                            "bg-red-50 text-destructive": row.execution === "失败",
                            "bg-slate-100 text-slate-600": row.execution === "未执行",
                          })}
                        >
                          {row.execution}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        {row.view_url || row.edit_url ? (
                          <div className="flex flex-wrap gap-2">
                            <Button
                              type="button"
                              variant="secondary"
                              className="min-h-8 px-3 text-xs"
                              disabled={busy || !row.view_url}
                              onClick={() => onOpenItem(row, "view")}
                            >
                              查看商品
                            </Button>
                            <Button
                              type="button"
                              variant="secondary"
                              className="min-h-8 px-3 text-xs"
                              disabled={busy || !row.edit_url}
                              onClick={() => onOpenItem(row, "edit")}
                            >
                              编辑商品
                            </Button>
                          </div>
                        ) : (
                          <p className="line-clamp-2 break-words text-xs leading-5 text-slate-500" title={row.notice || ""}>
                            {row.notice || "—"}
                          </p>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </article>
        </div>
        <aside className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-2xl border border-border bg-slate-950 text-slate-100">
          <div className="shrink-0 border-b border-white/10 px-4 py-3 text-sm font-medium">实时步骤</div>
          <div className="min-h-0 flex-1 overflow-auto p-4 font-mono text-xs leading-6" aria-live="polite">
            {(job?.logs || []).length === 0 ? (
              <p className="text-slate-500">开始入库后，这里会显示类目 / 属性 / 规格图 / 主图 / 详情 / 物流 / 提交。</p>
            ) : (
              (job?.logs || []).map((entry, index) => (
                <p
                  key={`${entry.time}-${index}`}
                  className={cn("break-words", {
                    "text-red-300": entry.level === "error",
                    "text-amber-200": entry.level === "warn",
                    "text-slate-200": entry.level === "info",
                  })}
                >
                  <span className="text-slate-500">{entry.time}</span> {entry.message}
                </p>
              ))
            )}
          </div>
        </aside>
      </div>
    </PanelFrame>
  );
}
