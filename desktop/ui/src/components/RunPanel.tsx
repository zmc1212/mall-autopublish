import { Clock, FileOutput, Loader2, PauseCircle, Play } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api";
import { Button, InputText } from "../theme";
import type { JobHistoryEntry, JobState, WorkbookRow } from "../types";
import cn from "../utils/classnames";
import formatDuration from "../utils/formatDuration";
import { pushToast } from "../utils/toasts";

import ConfirmDialog from "./ConfirmDialog";
import DataTableDialog from "./DataTableDialog";
import LiveSteps from "./LiveSteps";
import { isWarehoused } from "./RunNotifications";
import ProductItemId from "./ProductItemId";
import { PanelFrame } from "./Sidebar";
import { usePagination } from "../utils/usePagination";

const FLOW_STAGE_LABELS: Record<string, string> = {
  pending: "待入库",
  filling: "正在填写",
  filled: "已填写，待提交",
  submit_pending: "提交结果待核实",
  created: "已入库，待补图",
  material_prepared: "已生成素材",
  material_upload_pending: "上传结果待核实",
  material_recognizing: "正在识别素材",
  material_reviewed: "素材已核对",
  material_adopt_pending: "采纳结果待核实",
  material_verifying: "正在核验图片",
  complete: "图片已核验",
};

function flowStageLabel(row: WorkbookRow) {
  const stage = row.flow_stage || "";
  if (stage === "complete" && row.sku_image_strategy === "both") return "两类图片已核验";
  if (stage === "complete" && row.sku_image_strategy === "slim_material") return "搜索主图已核验";
  return FLOW_STAGE_LABELS[stage] || stage || "—";
}

function imageStatusLabel(row: WorkbookRow) {
  const stage = row.flow_stage || "";
  if (stage === "complete" && row.sku_image_strategy === "both") return "两类图片已核验";
  if (row.sku_image_strategy === "both" && row.spec_image_stage === "complete") return "规格图已核验，搜索主图待核验";
  if (stage === "complete") return row.sku_image_strategy === "slim_material" ? "搜索主图已核验" : "规格图已核验";
  if (row.sku_image_strategy === "publish_page") return "规格图待核验";
  if (stage) return "待补图";
  return "—";
}

function formatHistoryTime(seconds: number | null) {
  if (!seconds) return "—";
  const date = new Date(seconds * 1000);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

interface RunPanelProps {
  job: JobState | null;
  detailRow: WorkbookRow | null;
  retryFailed: boolean;
  limit: string;
  busy: boolean;
  pending: ReadonlySet<string>;
  onRetryFailed: (value: boolean) => void;
  onLimit: (value: string) => void;
  onStart: () => void;
  onStop: () => void;
  onOpenResult: () => void;
  onOpenItem: (row: WorkbookRow, action: "view" | "edit") => void;
  onClearItem: (row: WorkbookRow) => void;
  className?: string;
}

export default function RunPanel({
  job,
  detailRow,
  retryFailed,
  limit,
  busy,
  pending,
  onRetryFailed,
  onLimit,
  onStart,
  onStop,
  onOpenResult,
  onOpenItem,
  onClearItem,
  className = "",
}: RunPanelProps) {
  const running = job?.status === "running" || job?.status === "stopping";
  const total = job?.total || job?.valid || 0;
  const done = job?.done || 0;
  const percent = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const [clearCandidate, setClearCandidate] = useState<WorkbookRow | null>(null);
  const rowPending = (row: WorkbookRow, action: string) => pending.has(`run.${action}.${row.row}`);
  const canResume = Boolean(job?.can_resume) || (job?.rows || []).some(
    (row) => row.validation === "通过" && (row.execution === "失败" || row.execution === "暂停" || row.execution === "已停止"),
  );
  const pendingCount = job?.pending ?? job?.valid ?? 0;
  const startLabel = running ? (job?.status === "stopping" ? "正在暂停…" : "正在入库…") : retryFailed ? "重试未完成项" : canResume ? "继续入库" : "开始入库";
  const validRows = (job?.rows || []).filter((row) => row.validation === "通过");
  const [tableOpen, setTableOpen] = useState(false);
  const [highlightRow, setHighlightRow] = useState<number | null>(null);
  const { page: tablePage, setPage: setTablePage, pageRows: tableRows, pageSize } = usePagination(validRows);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyItems, setHistoryItems] = useState<JobHistoryEntry[]>([]);
  const { page: historyPage, setPage: setHistoryPage, pageRows: historyRows, pageSize: historyPageSize } = usePagination(historyItems);
  const openHistory = async () => {
    setHistoryOpen(true);
    setHistoryLoading(true);
    setHistoryPage(1);
    try {
      const data = await api.jobHistory();
      setHistoryItems(data.items || []);
    } catch (exc) {
      pushToast("error", `加载耗时统计失败：${exc instanceof Error ? exc.message : String(exc)}`);
    } finally {
      setHistoryLoading(false);
    }
  };
  useEffect(() => {
    if (!detailRow) return;
    const index = validRows.findIndex(row => row.row === detailRow.row && row.product_id === detailRow.product_id);
    setTablePage(Math.floor(Math.max(0, index) / pageSize) + 1);
    setHighlightRow(detailRow.row);
    setTableOpen(true);
  }, [detailRow]);
  const limitValid = limit === "" || (/^\d+$/.test(limit) && Number.isSafeInteger(Number(limit)) && Number(limit) >= 0);
  const warehoused = validRows.filter(isWarehoused).length;
  const complete = validRows.filter(row => row.flow_stage === "complete").length;
  const issues = validRows.filter(row => row.flow_stage !== "complete" && (["失败", "暂停", "已停止", "提交待核实"].includes(row.execution) || Boolean(row.last_error))).length;
  const batchHint = validRows.length > 1
    ? "默认逐条入库后，通过官方素材批量导入上传并核验搜索主图；销售规格图暂不上传。上一款完成后再处理下一款。"
    : "默认通过官方素材批量导入上传 SKU 搜索主图，销售规格图暂不上传；已有商品继续补图，不重复建品。";
  return (
    <PanelFrame
      title="执行入库"
      hint="逐条处理商品并提交到仓库，不会立即上架。已有商品继续补图，已完成商品自动跳过。"
    >
      <div
        className={`grid min-h-0 min-w-0 flex-1 grid-cols-1 content-start gap-3 overflow-y-auto xl:grid-cols-[minmax(0,1fr)_minmax(280px,340px)] xl:grid-rows-[minmax(0,1fr)] xl:overflow-hidden max-xl:[&>aside]:h-80 ${className}`}
      >
        <div className="flex min-w-0 flex-col gap-3 xl:min-h-0 xl:overflow-y-auto">
          <article className="shrink-0 rounded-2xl border border-border bg-white p-4">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="text-sm text-slate-500">校验通过</p>
                <p className="text-2xl font-semibold">{job?.valid || 0} 条</p>
                {pendingCount < (job?.valid || 0) ? (
                  <p className="mt-1 text-xs text-slate-500">待入库 {pendingCount} 条，已填完的会跳过</p>
                ) : null}
              </div>
              <label className="text-sm">
                本次处理上限
                <InputText
                  className="mt-1 w-28"
                  inputMode="numeric"
                  aria-label="本次处理上限"
                  aria-invalid={!limitValid}
                  value={limit}
                  onChange={(event) => onLimit(event.target.value)}
                  placeholder="全部"
                  disabled={running}
                />
              </label>
            </div>
            {!limitValid && <p className="mt-2 text-xs text-red-600" role="alert">请输入非负整数，留空或 0 表示全部。</p>}
            <div className="mt-4 grid grid-cols-4 gap-2 border-y border-border py-3 text-xs text-slate-500">
              <p>已入库 <strong className="ml-1 text-base text-foreground">{warehoused}</strong></p>
              <p>图片已核验 <strong className="ml-1 text-base text-emerald-700">{complete}</strong></p>
              <p>需关注 <strong className="ml-1 text-base text-amber-700">{issues}</strong></p>
              <p>平均每条 <strong className="ml-1 text-base text-foreground">{formatDuration(job?.avg_item_seconds)}</strong></p>
            </div>
            <p className="mt-2 text-sm text-slate-500">
              当前步骤：{job?.phase || "未开始"}
              {job?.current_id ? ` · ${job.current_id}` : ""}
            </p>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-label="本批处理进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
              <div className="h-full bg-primary transition-all duration-200" style={{ width: `${percent}%` }} />
            </div>
            <p className="mt-2 text-xs text-slate-400">
              {running
                ? `已处理 ${done} / ${total} 条 · ${percent}% · 已用时 ${formatDuration(job?.elapsed_seconds)}`
                : job?.status === "done"
                  ? `本批已结束 · 已处理 ${done} / ${total} 条 · 总耗时 ${formatDuration(job?.elapsed_seconds)}`
                  : job?.blocker
                    ? "已暂停，等待处理"
                    : "等待开始"}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button onClick={onStart} disabled={busy || running || !job?.valid || !limitValid || (!retryFailed && pendingCount === 0)}>
                {pending.has("run.start") ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Play className="h-4 w-4" aria-hidden="true" />
                )}
                {startLabel}
              </Button>
              <Button variant="secondary" onClick={onStop} disabled={busy || job?.status !== "running"}>
                {pending.has("run.stop") ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <PauseCircle className="h-4 w-4" aria-hidden="true" />
                )}
                {job?.status === "stopping" ? "正在安全暂停…" : "暂停任务"}
              </Button>
              <Button variant="ghost" onClick={onOpenResult} disabled={!job?.result_xlsx}>
                <FileOutput className="h-4 w-4" aria-hidden="true" />
                打开结果 Excel
              </Button>
              <Button variant="ghost" onClick={openHistory}>
                <Clock className="h-4 w-4" aria-hidden="true" />
                耗时统计
              </Button>
            </div>
            <div className="mt-3">
              <label className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-2.5 text-sm text-slate-800">
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4 shrink-0 accent-orange-600"
                  checked={retryFailed}
                  disabled={running}
                  onChange={(event) => onRetryFailed(event.target.checked)}
                />
                <span>
                  <strong className="font-semibold">重试未完成项</strong>
                  <span className="mt-1 block text-xs leading-5 text-slate-600 max-xl:hidden">
                    继续失败、暂停及未完成的流程，已完成商品跳过。
                  </span>
                </span>
              </label>
            </div>
            <p className="mt-3 text-xs leading-5 text-slate-500">{batchHint} 暂停会等待当前操作结束并保留进度。</p>
            {running && job?.stalled ? (
              <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="alert">
                任务已超过 20 分钟无任何进展，可能被页面弹窗或验证阻塞。已自动弹出浏览器窗口，请检查现场后选择暂停或继续等待。
              </p>
            ) : null}
            {job?.blocker ? (
              <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
                任务已暂停：{job.blocker}。请保留 Chrome 现场，按具体暂停原因处理后再继续。
              </p>
            ) : null}
          </article>
          <article className="flex shrink-0 items-center justify-between gap-4 rounded-2xl border border-border bg-white p-4">
            <div className="min-w-0">
              <h3 className="text-sm font-medium">可执行商品</h3>
              <p className="mt-1 text-xs text-slate-500">
                {validRows.length > 0 ? `共 ${validRows.length} 条通过校验的商品，分页查看并打开商品。` : "校验通过的商品会显示在分页窗口中。"}
              </p>
            </div>
            <Button
              variant="secondary"
              className="shrink-0"
              disabled={validRows.length === 0}
              onClick={() => {
                setTablePage(1);
                setHighlightRow(null);
                setTableOpen(true);
              }}
            >
              查看执行明细
            </Button>
          </article>
        </div>
        <LiveSteps job={job} />
      </div>
      <DataTableDialog
        open={tableOpen}
        title="执行明细"
        description="分页查看通过校验的商品，并从这里打开商品页面。"
        total={validRows.length}
        page={tablePage}
        pageSize={pageSize}
        onPageChange={setTablePage}
        onClose={() => setTableOpen(false)}
      >
        <table className="w-full min-w-[1060px] table-fixed border-collapse text-left text-sm">
          <colgroup>
            <col className="w-56" />
            <col className="w-44" />
            <col className="w-36" />
            <col className="w-44" />
            <col className="w-28" />
            <col className="w-20" />
            <col className="w-64" />
          </colgroup>
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              <th className="whitespace-nowrap px-4 py-3 font-medium">商品</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">淘宝商品ID</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">执行</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">入库状态</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">图片状态</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">耗时</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {tableRows.length === 0 ? (
              <tr><td colSpan={7} className="px-4 py-10 text-center text-slate-400">暂无可执行商品</td></tr>
            ) : (
              tableRows.map((row) => (
                <tr key={`run-${row.row}`} className={cn("border-t border-border", highlightRow === row.row && "bg-orange-50")}>
                  <td className="truncate whitespace-nowrap px-4 py-3" title={`${row.product_id} · 第${row.row}行`}>
                    {row.product_id}<span className="ml-2 text-xs text-slate-400">第{row.row}行</span>
                  </td>
                  <td className="overflow-hidden px-4 py-2"><ProductItemId value={row.taobao_item_id} /></td>
                  <td className="overflow-hidden whitespace-nowrap px-4 py-3" title={row.execution || "未执行"}>
                    <span className={cn("inline-block max-w-full truncate rounded-full px-2.5 py-1 text-xs", {
                      "bg-emerald-50 text-emerald-700": row.execution === "已填写未提交" || row.execution === "结果待核实" || row.execution === "已入库，图片已核验",
                      "bg-amber-50 text-amber-800": row.execution === "暂停" || row.execution === "已停止",
                      "bg-red-50 text-destructive": row.execution === "失败" || row.execution === "提交待核实",
                      "bg-slate-100 text-slate-600": row.execution === "未执行",
                    })}>{row.execution}</span>
                  </td>
                  <td className="overflow-hidden whitespace-nowrap px-4 py-3 text-xs text-slate-600" title={flowStageLabel(row)}>
                    {flowStageLabel(row)}
                  </td>
                  <td className="overflow-hidden whitespace-nowrap px-4 py-3">
                    <span className={cn("inline-block max-w-full truncate rounded-full px-2.5 py-1 text-xs", {
                      "bg-emerald-50 text-emerald-700": row.flow_stage === "complete",
                      "bg-amber-50 text-amber-800": imageStatusLabel(row) === "待补图" || imageStatusLabel(row) === "规格图待核验",
                      "bg-slate-100 text-slate-400": imageStatusLabel(row) === "—",
                    })}>{imageStatusLabel(row)}</span>
                  </td>
                  <td className="overflow-hidden whitespace-nowrap px-4 py-3 text-xs text-slate-600" title={row.duration_seconds ? `本次入库耗时 ${row.duration_seconds} 秒` : undefined}>
                    {formatDuration(row.duration_seconds)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      {row.view_url ? (
                        <Button type="button" variant="secondary" className="min-h-8 px-3 text-xs" disabled={busy || !row.view_url} onClick={() => onOpenItem(row, "view")}>
                          {rowPending(row, "openItem") ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : null}
                          查看商品
                        </Button>
                      ) : null}
                      {row.edit_url ? (
                        <Button type="button" variant="secondary" className="min-h-8 px-3 text-xs" disabled={busy || !row.edit_url} onClick={() => onOpenItem(row, "edit")}>
                          {rowPending(row, "openItem") ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : null}
                          编辑商品
                        </Button>
                      ) : null}
                      {!row.view_url && !row.edit_url ? (
                        <p className="truncate whitespace-nowrap text-xs text-slate-500" title={row.notice || "—"}>{row.notice || "—"}</p>
                      ) : null}
                      <Button
                        type="button"
                        variant="secondary"
                        className="min-h-8 px-3 text-xs text-red-600 hover:bg-red-50 hover:border-red-200"
                        disabled={busy || running}
                        onClick={() => setClearCandidate(row)}
                      >
                        {rowPending(row, "clearItem") ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : null}
                        清除记录
                      </Button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </DataTableDialog>
      <DataTableDialog
        open={historyOpen}
        title="入库耗时统计"
        description="最近 30 次入库任务的耗时；每次点击开始/继续入库记为一条，等待人工处理的时间不计入总时长。"
        total={historyItems.length}
        page={historyPage}
        pageSize={historyPageSize}
        onPageChange={setHistoryPage}
        onClose={() => setHistoryOpen(false)}
      >
        <table className="w-full min-w-[720px] table-fixed border-collapse text-left text-sm">
          <colgroup>
            <col className="w-48" />
            <col className="w-28" />
            <col className="w-28" />
            <col className="w-24" />
            <col className="w-20" />
            <col className="w-20" />
          </colgroup>
          <thead className="bg-slate-50 text-slate-500">
              <tr>
              <th className="whitespace-nowrap px-4 py-3 font-medium">批次时间</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">总时长</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">平均每条</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">处理条数</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">成功</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">失败</th>
            </tr>
          </thead>
          <tbody>
            {historyLoading ? (
              <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-400">正在加载…</td></tr>
            ) : historyRows.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-400">暂无历史记录</td></tr>
            ) : (
              historyRows.map((item) => (
                <tr key={item.file} className="border-t border-border">
                  <td className="whitespace-nowrap px-4 py-3 text-slate-600" title={item.source}>
                    {formatHistoryTime(item.started_at || item.finished_at)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">{formatDuration(item.duration_seconds)}</td>
                  <td className="whitespace-nowrap px-4 py-3">{formatDuration(item.avg_seconds)}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-slate-600">{item.total}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-emerald-700">{item.succeeded}</td>
                  <td className={cn("whitespace-nowrap px-4 py-3", item.failed > 0 ? "text-red-600" : "text-slate-600")}>{item.failed}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </DataTableDialog>
      <ConfirmDialog
        open={Boolean(clearCandidate)}
        title="清除执行记录"
        destructive
        confirmLabel="清除"
        onClose={() => setClearCandidate(null)}
        onConfirm={() => {
          if (clearCandidate) onClearItem(clearCandidate);
          setClearCandidate(null);
        }}
      >
        {clearCandidate ? (
          <>
            <p>
              确定要清除「{clearCandidate.product_id || `第${clearCandidate.row}行`}」的执行记录吗？
            </p>
            {clearCandidate.taobao_item_id ? (
              <>
                <p className="mt-2">将同时清除商品 ID {clearCandidate.taobao_item_id}，该商品下次执行时会重新建档入库。</p>
                <p className="mt-2 font-medium text-destructive">此操作不可撤销。</p>
              </>
            ) : (
              <p className="mt-2">该商品将恢复为「未执行」。</p>
            )}
          </>
        ) : null}
      </ConfirmDialog>
    </PanelFrame>
  );
}
