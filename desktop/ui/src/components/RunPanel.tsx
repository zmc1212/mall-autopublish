import { ChevronLeft, ChevronRight, CircleAlert, FileOutput, Loader2, PackageOpen, PanelRightClose, PanelRightOpen, PauseCircle, Play, Search, SlidersHorizontal } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { api } from "../api";
import { Button, InputText } from "../theme";
import type { ExecutionLimitMode, JobHistoryEntry, JobState, WorkbookRow } from "../types";
import cn from "../utils/classnames";
import formatDuration from "../utils/formatDuration";
import { pushToast } from "../utils/toasts";

import ConfirmDialog from "./ConfirmDialog";
import DataTableDialog from "./DataTableDialog";
import RunInspector from "./RunInspector";
import { isWarehoused } from "./RunNotifications";
import ProductItemId from "./ProductItemId";
import ProductThumbnail from "./ProductThumbnail";
import { imageStatus, isRowAttention, isRowComplete, videoStatus, warehouseStatus } from "../utils/rowState";
import { usePagination } from "../utils/usePagination";
import { useSessionState } from "../utils/useSessionState";
import ProductDrawer from "./ProductDrawer";

const FLOW_STAGE_LABELS: Record<string, string> = {
  pending: "待入库",
  filling: "填写资料",
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


function flowStageLabel(row: WorkbookRow, imageStrategy?: string) {
  if (isRowAttention(row) && row.flow_stage === "complete") return "结果待核实";
  const stage = row.flow_stage || "";
  if (stage === "complete") return imageStatus(row, imageStrategy).label;
  return FLOW_STAGE_LABELS[stage] || stage || "—";
}

/** 执行明细的状态筛选桶；口径与后端 ATTENTION_EXECUTIONS 对齐。 */
type TableFilter = "all" | "attention" | "warehoused" | "idle" | "complete" | "active";

const TABLE_FILTERS: { key: TableFilter; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "complete", label: "已完成" },
  { key: "active", label: "执行中" },
  { key: "attention", label: "需关注" },
  { key: "warehoused", label: "已入库" },
  { key: "idle", label: "未执行" },
];

const INSPECTOR_COLLAPSED_KEY = "qianniu.run.inspectorCollapsed";


function matchTableFilter(row: WorkbookRow, filter: TableFilter, activeIds: Set<string> = new Set(), imageStrategy?: string) {
  if (filter === "complete") return isRowComplete(row, imageStrategy);
  if (filter === "active") return activeIds.has(row.product_id) && !isRowComplete(row, imageStrategy);
  if (filter === "warehoused") return isWarehoused(row);
  if (filter === "idle") return (!row.execution || row.execution === "未执行") && !activeIds.has(row.product_id);
  if (filter === "attention") return isRowAttention(row);
  return true;
}

/** 是否带有执行痕迹（发生过执行、建档或补图流程），用于一键清除的计数。 */
function rowHasRecord(row: WorkbookRow) {
  return Boolean(
    (row.execution && row.execution !== "未执行") ||
    row.taobao_item_id ||
    (row.flow_stage && row.flow_stage !== "pending"),
  );
}

function isWarehousedRecord(row: WorkbookRow) {
  return isWarehoused(row);
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
  onStart: (rows?: WorkbookRow[]) => void;
  onStop: () => void;
  onOpenResult: () => void;
  onOpenItem: (row: WorkbookRow, action: "view" | "edit") => void;
  onClearItem: (row: WorkbookRow) => void;
  onClearItems: (rows: number[]) => void;
  onPrepare?: () => void;
  onConnect?: () => void;
  onSettings?: () => void;
  onLogs?: (productId?: string) => void;
  onOpenPack?: (row: WorkbookRow) => void;
  onInspectBrowser?: () => void;
  onDetailsConsumed?: () => void;
  limitMode: ExecutionLimitMode;
  onLimitMode: (mode: ExecutionLimitMode) => void;
  defaultLimit: number;
  configuredConcurrency: number;
  startBlockedReason?: string;
  imageStrategy?: string;
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
  onClearItems,
  onPrepare,
  onConnect,
  onSettings,
  onLogs,
  onOpenPack,
  onInspectBrowser,
  onDetailsConsumed,
  limitMode,
  onLimitMode,
  defaultLimit,
  configuredConcurrency,
  startBlockedReason = "",
  imageStrategy = "",
  className = "",
}: RunPanelProps) {
  const running = job?.status === "running" || job?.status === "stopping";
  const total = job?.total || job?.valid || 0;
  const done = job?.done || 0;
  const percent = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const [clearCandidate, setClearCandidate] = useState<WorkbookRow | null>(null);
  const [inspectorCollapsed, setInspectorCollapsed] = useState(() => {
    try { return window.localStorage.getItem(INSPECTOR_COLLAPSED_KEY) === "true"; }
    catch { return false; }
  });
  const inspectorToggleRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    try { window.localStorage.setItem(INSPECTOR_COLLAPSED_KEY, String(inspectorCollapsed)); }
    catch { /* 禁用本地存储时仍可正常展开、收起。 */ }
  }, [inspectorCollapsed]);
  const rowPending = (row: WorkbookRow, action: string) => pending.has(`run.${action}.${row.row}`);
  const canResume = Boolean(job?.can_resume) || (job?.rows || []).some(
    (row) => row.validation === "通过" && (row.execution === "失败" || row.execution === "暂停" || row.execution === "已停止"),
  );
  const pendingCount = job?.pending ?? job?.valid ?? 0;
  const startLabel = retryFailed ? "重试全部未完成项" : canResume ? "继续全部未完成项" : "开始全部未完成项";
  const validRows = (job?.rows || []).filter((row) => row.validation === "通过");
  const activeWorkers = Array.isArray(job?.active_workers) ? job.active_workers : [];
  const activeIds = new Set(activeWorkers.filter(worker => worker.status === "running").map(worker => worker.product_id));
  const viewKey = `qianniu.run.${job?.workspace_path || job?.workbook_path || "empty"}`;
  const [selectedKeys, setSelectedKeys] = useSessionState<string[]>(`${viewKey}.selection`, []);
  const selectedRows = new Set(selectedKeys);
  const setSelectedRows = (update: Set<string> | ((current: Set<string>) => Set<string>)) => setSelectedKeys(current => Array.from(typeof update === "function" ? update(new Set(current)) : update));
  const rowKey = (row: WorkbookRow) => `${row.row}|${row.product_id}`;
  const [tableOpen, setTableOpen] = useState(false);
  const [tableFilter, setTableFilter] = useSessionState<TableFilter>(`${viewKey}.filter`, "all");
  const [tableQuery, setTableQuery] = useSessionState(`${viewKey}.query`, "");
  const [drawerKey, setDrawerKey] = useSessionState<string | null>(`${viewKey}.detail`, null);
  const identity = validRows.map(row => `${rowKey(row)}|${row.pack_fingerprint || ""}`).join("\n");
  const [savedIdentity, setSavedIdentity] = useSessionState(`${viewKey}.identity`, identity);
  useEffect(() => {
    if (savedIdentity === identity) return;
    setSelectedKeys([]);
    setDrawerKey(null);
    setSavedIdentity(identity);
  }, [identity, savedIdentity]);
  const [bulkClearOpen, setBulkClearOpen] = useState(false);
  const [highlightRow, setHighlightRow] = useState<number | null>(null);
  const query = tableQuery.trim().toLowerCase();
  const tableFilterActive = tableFilter !== "all" || query !== "";
  const filteredRows = validRows.filter((row) => {
    if (!matchTableFilter(row, tableFilter, activeIds, imageStrategy)) return false;
    if (!query) return true;
    return [row.title, row.product_id, row.taobao_item_id]
      .some((value) => (value || "").toLowerCase().includes(query));
  });
  const filterCounts = Object.fromEntries(
    TABLE_FILTERS.map(({ key }) => [key, validRows.filter((row) => matchTableFilter(row, key, activeIds, imageStrategy)).length]),
  ) as Record<TableFilter, number>;
  const selectedCandidates = validRows.filter(row => selectedRows.has(rowKey(row)));
  const selectedExecutable = selectedCandidates.filter(row => !isRowComplete(row, imageStrategy));
  const incompleteCount = validRows.filter(row => !isRowComplete(row, imageStrategy)).length;
  const clearableRows = (selectedCandidates.length ? selectedCandidates : filteredRows).filter(rowHasRecord);
  const warehousedClearCount = clearableRows.filter(isWarehousedRecord).length;
  const tableScrollRef = useRef<HTMLDivElement>(null);
  const [visiblePageSize, setVisiblePageSize] = useState(8);
  useLayoutEffect(() => {
    const area = tableScrollRef.current;
    if (!area) return;
    const measurePage = () => {
      // 单列布局由整页滚动承接内容，不再在表格内部叠一层竖向滚动。
      if (window.matchMedia("(max-width: 1279px)").matches) {
        setVisiblePageSize(window.innerHeight < 780 ? 4 : 6);
        return;
      }
      const heading = area.querySelector("thead")?.getBoundingClientRect().height || 44;
      // 长标题自然换行后每行高度不同。按稳定的阅读高度估算每页条数，
      // 超长内容由表格滚动承接，避免翻页时首行高度改变导致分页跳动。
      const rowHeight = 88;
      setVisiblePageSize(Math.max(1, Math.min(8, Math.floor((area.clientHeight - heading - 2) / rowHeight))));
    };
    const observer = new ResizeObserver(measurePage);
    observer.observe(area);
    window.addEventListener("resize", measurePage);
    measurePage();
    return () => { observer.disconnect(); window.removeEventListener("resize", measurePage); };
  }, []);
  const { page: tablePage, setPage: setTablePage, pageRows: tableRows, pageSize, pageCount } = usePagination(filteredRows, visiblePageSize, `${viewKey}.page`);
  const [detailPageSize, setDetailPageSize] = useSessionState(`${viewKey}.detailPageSize`, 15);
  const { page: detailPage, setPage: setDetailPage, pageRows: detailRows } = usePagination(filteredRows, detailPageSize, `${viewKey}.detailPage`);
  useEffect(() => {
    tableScrollRef.current?.scrollTo({ top: 0 });
  }, [tablePage, tableFilter, tableQuery, pageSize]);
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
    setDrawerKey(rowKey(detailRow));
    setHighlightRow(detailRow.row);
    onDetailsConsumed?.();
  }, [detailRow]);
  const limitValid = limitMode !== "custom" || (/^\d+$/.test(limit) && Number.isSafeInteger(Number(limit)) && Number(limit) > 0);
  const effectiveLimit = limitMode === "default" ? defaultLimit : limitMode === "all" ? 0 : Number(limit);
  const applyLimit = (count: number) => effectiveLimit > 0 ? Math.min(count, effectiveLimit) : count;
  const complete = validRows.filter((row) => isRowComplete(row, imageStrategy)).length;
  const attentionRows = validRows.filter(isRowAttention);
  const attentionCount = attentionRows.length;
  // 状态分段互斥；进行中但结果待核实的商品归入需关注。
  const activeCount = validRows.filter(row => activeIds.has(row.product_id) && !isRowComplete(row, imageStrategy) && !isRowAttention(row)).length;
  const progressSegments = [
    { tone: "complete", label: "已完成", count: complete },
    { tone: "active", label: "执行中", count: activeCount },
    { tone: "pending", label: "待处理", count: validRows.length - complete - activeCount - attentionCount },
    { tone: "attention", label: "需关注", count: attentionCount },
  ];
  const concurrency = running ? job?.concurrency ?? configuredConcurrency : configuredConcurrency;
  const sourceName = (job?.workspace_path || job?.workbook_path || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop() || "尚未准备商品";
  const filterRows = (key: TableFilter) => { setTableFilter(key); setTablePage(1); setDetailPage(1); setHighlightRow(null); };
  const openDetails = (row?: WorkbookRow) => {
    if (row) {
      setDrawerKey(rowKey(row));
      setHighlightRow(row.row);
    } else setTableOpen(true);
  };
  const summary = [
    { key: "all" as const, label: "全部", value: validRows.length, color: "" },
    { key: "complete" as const, label: "已完成", value: complete, color: "text-primary" },
    { key: "active" as const, label: "执行中", value: filterCounts.active, color: "text-sky-600" },
    { key: "idle" as const, label: "未执行", value: filterCounts.idle, color: "text-slate-600" },
    { key: "attention" as const, label: "需关注", value: attentionCount, color: "text-amber-600" },
  ];
  const toggleRow = (row: WorkbookRow, checked?: boolean) => {
    setHighlightRow(null);
    setSelectedRows(current => {
      const next = new Set(current);
      const key = rowKey(row);
      if (checked ?? !current.has(key)) next.add(key); else next.delete(key);
      return next;
    });
  };
  const allPageSelected = tableRows.length > 0 && tableRows.every(row => selectedRows.has(rowKey(row)));
  return (
    <section className={`run-layout ${className}`} data-inspector-collapsed={inspectorCollapsed}>
      <div className="run-primary">
        <header className="run-heading">
          <div className="min-w-0"><h2>执行工作台</h2><p className="truncate" title={job?.workspace_path || job?.workbook_path}>{sourceName} · {validRows.length} 件可执行商品</p></div>
          <div className="run-heading-actions">
            {running ? <Button variant="secondary" onClick={onStop} disabled={busy || job?.status !== "running"}>
              {job?.status === "stopping" || pending.has("run.stop") ? <Loader2 className="h-4 w-4 animate-spin" /> : <PauseCircle className="h-4 w-4" />}
              {job?.status === "stopping" ? "正在暂停…" : "暂停任务"}
            </Button> : <Button onClick={() => onStart()} disabled={busy || !job?.valid || !limitValid || Boolean(startBlockedReason) || incompleteCount === 0}>
              {pending.has("run.start") ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}{startLabel}（{limitValid ? applyLimit(incompleteCount) : "—"} 件）
            </Button>}
            <Button variant="secondary" onClick={onOpenResult} disabled={!job?.result_xlsx}><FileOutput className="h-4 w-4" />打开结果表</Button>
            <button className="inline-flex min-h-10 items-center gap-1.5 rounded-lg px-2 text-xs text-primary hover:bg-muted" popoverTarget="run-options-popover"><SlidersHorizontal className="h-4 w-4" />执行选项</button>
            <button
              ref={inspectorToggleRef}
              type="button"
              className="inline-flex min-h-10 items-center gap-1.5 rounded-lg px-2 text-xs text-primary hover:bg-muted"
              aria-expanded={!inspectorCollapsed}
              aria-controls="run-progress-panel"
              onClick={() => setInspectorCollapsed(current => !current)}
            >
              {inspectorCollapsed ? <PanelRightOpen className="h-4 w-4" aria-hidden="true" /> : <PanelRightClose className="h-4 w-4" aria-hidden="true" />}
              {inspectorCollapsed ? "展开进度" : "收起进度"}
            </button>
          </div>
        </header>
        <div className="execution-plan" aria-label="本次执行摘要">
          <span>主按钮执行全部未完成项，筛选仅影响展示</span>
          <span>{running ? `本批计划处理 ${total} 件` : <>处理上限：{limitMode === "default" ? "沿用默认 · " : ""}{limitValid ? effectiveLimit === 0 ? "全部" : `${effectiveLimit} 件` : "请修正"}</>}</span>
          <span>同时处理 {concurrency} 件</span>
          <span>图片目标：{imageStrategy === "both" ? "搜索主图与商品规格图" : imageStrategy === "publish_page" ? "商品规格图" : "搜索主图"}</span>
          <span>仅放入仓库</span>
        </div>
        {(job?.blocker || (startBlockedReason && !running)) && <div className="attention-note flex flex-wrap items-center gap-3" role="status">
          <CircleAlert className="h-4 w-4 shrink-0" aria-hidden="true" /><span className="flex-1">{job?.blocker || startBlockedReason}</span>
          <button className="underline underline-offset-4" onClick={/登录|浏览器/.test(job?.blocker || startBlockedReason) ? onConnect : job?.blocker ? () => filterRows("attention") : onPrepare}>{/登录|浏览器/.test(job?.blocker || startBlockedReason) ? "连接店铺" : job?.blocker ? "查看需关注商品" : "前往商品清单"}</button>
        </div>}
        {running && job?.stalled && <div className="attention-note" role="alert">任务长时间没有进展，请查看浏览器现场，或暂停后检查任务。<button className="ml-2 underline" onClick={onSettings}>排障工具</button></div>}
        <div className="run-summary">
          <div className="run-counts" role="group" aria-label="筛选商品状态">{summary.map(item => <button key={item.key} aria-pressed={tableFilter === item.key} onClick={() => filterRows(item.key)} aria-label={`${item.label} ${item.value} 件，筛选商品`}><span>{item.label}</span><strong className={item.color}>{item.value}</strong></button>)}</div>
          <div className="run-summary-caption"><span>全部商品状态分布</span><span>点击上方状态筛选商品</span></div>
          <div className="run-progress" role="img" aria-label={`全部商品状态分布：${progressSegments.map(segment => `${segment.label} ${segment.count} 件`).join("，")}`}>
            {progressSegments.filter(segment => segment.count > 0).map(segment => <span key={segment.tone} data-tone={segment.tone} title={`${segment.label} ${segment.count} 件`} aria-hidden="true" style={{ width: `${segment.count / validRows.length * 100}%` }} />)}
          </div>
          {(running || Boolean(job?.started_at) || done > 0) && <>
            <div className="run-summary-caption"><span>{job?.status === "stopping" ? "正在暂停，保留当前进度" : job?.status === "done" ? "本批已结束" : job?.can_resume && !running ? "已保留进度" : "本次任务"} · 已处理 {done} / {total} · {percent}%</span><span>已用时 {formatDuration(job?.elapsed_seconds)}</span></div>
            <div className="run-progress run-task-progress" role="progressbar" aria-label="本批处理进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-valuetext={`本批已处理 ${done} / ${total}`}><span data-tone="complete" style={{ width: `${percent}%` }} /></div>
            {!running && <p className="mt-2 text-xs text-slate-600">本批需关注 {job?.attention_count || 0} 件 · 清单剩余待处理 {pendingCount} 件{job?.result_xlsx ? " · 可打开结果表查看本批记录" : ""}</p>}
          </>}
        </div>
        <div className="run-toolbar">
          <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600"><span>当前显示：{TABLE_FILTERS.find(item => item.key === tableFilter)?.label || "全部"} · {filteredRows.length} 件</span>{tableFilterActive && <button className="text-primary underline underline-offset-4" onClick={() => { filterRows("all"); setTableQuery(""); }}>清空筛选</button>}</div>
          <label className="run-search"><Search aria-hidden="true" /><InputText aria-label="搜索商品名称或 ID" placeholder="搜索商品名称或 ID" value={tableQuery} onChange={event => { setTableQuery(event.target.value); setTablePage(1); setDetailPage(1); }} /></label>
        </div>
        <div className="run-table-frame">
          <div className="run-table-scroll" ref={tableScrollRef}>
            <table className="run-table" aria-label="商品执行列表">
              <colgroup><col /><col /><col /><col /><col /><col /></colgroup>
              <thead><tr><th><input type="checkbox" aria-label="选择本页商品" checked={allPageSelected} disabled={!tableRows.length} onChange={event => { const checked = event.target.checked; setSelectedRows(current => { const next = new Set(current); tableRows.forEach(row => checked ? next.add(rowKey(row)) : next.delete(rowKey(row))); return next; }); }} /></th><th>商品 / 商品编号</th><th>入库状态</th><th>图片状态</th><th>主视频状态</th><th>操作</th></tr></thead>
              <tbody>{tableRows.map(row => {
                const warehouse = warehouseStatus(row), pictures = imageStatus(row, imageStrategy), video = videoStatus(row);
                return <tr
                  key={rowKey(row)}
                  data-selected={selectedRows.has(rowKey(row))}
                  data-highlighted={highlightRow === row.row}
                  aria-selected={selectedRows.has(rowKey(row))}
                  tabIndex={0}
                  onClick={event => {
                    if ((event.target as Element).closest("button, input, a, label, select, textarea, [role='button']")) return;
                    toggleRow(row);
                  }}
                  onKeyDown={event => {
                    if (event.target !== event.currentTarget || ![" ", "Enter"].includes(event.key)) return;
                    event.preventDefault();
                    toggleRow(row);
                  }}
                >
                  <td><input type="checkbox" aria-label={`选择 ${row.product_id}`} checked={selectedRows.has(rowKey(row))} onChange={event => toggleRow(row, event.target.checked)} /></td>
                  <td><div className="run-product"><ProductThumbnail url={row.preview_url} title={row.title || row.product_id} /><div className="min-w-0"><strong title={row.title || row.product_id}>{row.title || row.product_id}</strong><small title={row.product_id}>{row.product_id}</small></div></div></td>
                  <td><span className="row-state" data-tone={warehouse.tone} title={row.execution}><span>{warehouse.label}</span></span></td>
                  <td><span className="row-state" data-tone={pictures.tone} title={row.last_error || flowStageLabel(row, imageStrategy)}><span>{pictures.label}</span></span></td>
                  <td><span className="row-state" data-tone={video.tone} title={row.video_warning || row.video_name || video.label}><span>{video.label}</span></span></td>
                  <td><div className="flex items-center gap-2 whitespace-nowrap"><button className="text-primary hover:underline disabled:opacity-40" disabled={busy || !row.view_url} onClick={() => onOpenItem(row, "view")} aria-label={`查看商品 ${row.product_id}`}>查看</button><button className="font-medium text-primary hover:underline" aria-label={`详情 ${row.product_id}`} onClick={() => openDetails(row)}>详情</button></div></td>
                </tr>;
              })}</tbody>
            </table>
            {!tableRows.length && <div className="empty-work"><PackageOpen aria-hidden="true" /><h3>{validRows.length ? "没有符合条件的商品" : "准备好商品，就从这里开始"}</h3><p>{validRows.length ? "试试其他状态，或清空搜索关键词。" : "选择工作空间或导入 Excel，完成校验后即可执行入库。"}</p><Button variant="secondary" onClick={validRows.length ? () => { setTableFilter("all"); setTableQuery(""); } : onPrepare}>{validRows.length ? "清空筛选" : "前往商品清单"}</Button></div>}
          </div>
          <footer className="run-table-footer">
            <div className="flex flex-wrap items-center gap-3"><span>{selectedCandidates.length ? `已选 ${selectedCandidates.length} 件（当前页 ${tableRows.filter(row => selectedRows.has(rowKey(row))).length} 件） · ` : ""}共 {filteredRows.length} 件商品</span><button className="text-primary hover:underline" onClick={() => openDetails()}>查看执行明细</button><button className="text-primary hover:underline" onClick={openHistory}>耗时统计</button></div>
            <div className="flex items-center gap-3">
              {selectedCandidates.length > 0 && <>
                <Button className="min-h-9 px-3 text-xs" disabled={busy || running || !limitValid || Boolean(startBlockedReason) || !selectedExecutable.length} onClick={() => onStart(selectedCandidates)}>执行所选（{limitValid ? applyLimit(selectedExecutable.length) : "—"} 件）</Button>
                <button className="text-primary" onClick={() => setSelectedRows(new Set())}>取消选择</button>
                <button className="text-red-600 disabled:opacity-40" disabled={busy || running || !clearableRows.length} onClick={() => setBulkClearOpen(true)}>清除所选记录</button>
              </>}
              <div className="run-pagination"><button aria-label="上一页商品" disabled={tablePage <= 1} onClick={() => setTablePage(tablePage - 1)}><ChevronLeft className="h-4 w-4" /></button>{Array.from({ length: Math.min(pageCount, 5) }, (_, index) => Math.max(1, Math.min(tablePage - 2, pageCount - 4)) + index).map(page => <button key={page} aria-label={`第 ${page} 页商品`} aria-current={tablePage === page ? "page" : undefined} onClick={() => setTablePage(page)}>{page}</button>)}<button aria-label="下一页商品" disabled={tablePage >= pageCount} onClick={() => setTablePage(tablePage + 1)}><ChevronRight className="h-4 w-4" /></button></div>
            </div>
          </footer>
        </div>
        <div className="run-options-popup" popover="auto" id="run-options-popover">
          <h3 className="mb-4 text-base font-semibold">本次执行选项</h3>
          <div className="run-options">
          <label>本次上限<select className="min-h-10 rounded-lg border border-border bg-white px-2" aria-label="本次上限模式" disabled={running} value={limitMode} onChange={event => { const mode = event.target.value as ExecutionLimitMode; onLimitMode(mode); if (mode === "custom" && !limit) onLimit(String(defaultLimit || 1)); }}><option value="default">沿用默认（{defaultLimit || "全部"}）</option><option value="all">全部</option><option value="custom">指定数量</option></select></label>
          {limitMode === "custom" && <label>指定数量<InputText className="!min-h-10 !w-20 px-2 text-xs" inputMode="numeric" aria-label="本次处理上限" aria-invalid={!limitValid} value={limit} onChange={event => onLimit(event.target.value)} placeholder="正整数" disabled={running} /></label>}
          <label title="继续失败、暂停及未完成流程，已完成商品自动跳过"><input type="checkbox" checked={retryFailed} disabled={running} onChange={event => onRetryFailed(event.target.checked)} />重试未完成项</label>
          </div>
          <p className="mt-4 text-xs leading-6 text-slate-600">沿用默认会使用最近保存的设置；全部会覆盖默认上限。上限分别应用于“全部未完成项”或“执行所选”。已完成商品自动跳过，暂停会保留进度。</p>
          {!limitValid && <p className="mt-2 text-xs text-red-600" role="alert">指定数量请输入正整数；处理全部请选择“全部”。</p>}
        </div>
        {!limitValid && <p className="text-xs text-red-600" role="alert">执行选项中的处理上限无效，请输入非负整数。</p>}
      </div>
      <RunInspector
        job={job && !running ? { ...job, concurrency: configuredConcurrency } : job}
        imageStrategy={imageStrategy}
        hidden={inspectorCollapsed}
        onCollapse={() => { setInspectorCollapsed(true); inspectorToggleRef.current?.focus(); }}
        onAttention={() => filterRows("attention")}
        onDetails={openDetails}
        onSettings={onSettings || (() => {})}
        onLogs={() => onLogs?.()}
      />
      <ProductDrawer
        row={validRows.find(row => rowKey(row) === drawerKey) || null}
        imageStrategy={imageStrategy}
        stageLabel={flowStageLabel(validRows.find(row => rowKey(row) === drawerKey) || {} as WorkbookRow, imageStrategy)}
        busy={busy} running={running} startBlockedReason={startBlockedReason || (!limitValid ? "请先在执行选项中修正本次处理上限。" : "")}
        onClose={() => setDrawerKey(null)} onOpenItem={onOpenItem} onOpenPack={onOpenPack}
        onPrepare={onPrepare} onConnect={onConnect} onSettings={onSettings} onLogs={onLogs}
        onInspectBrowser={onInspectBrowser}
        onResume={row => { onStart([row]); }}
      />
      <DataTableDialog
        open={tableOpen}
        title="执行明细"
        description="分页查看通过校验的商品，并从这里打开商品页面。"
        total={filteredRows.length}
        page={detailPage}
        pageSize={detailPageSize}
        onPageChange={setDetailPage}
        onClose={() => setTableOpen(false)}
        toolbar={
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-xs text-slate-600">每页显示<select aria-label="明细每页条数" className="min-h-9 rounded border border-border bg-white px-2" value={detailPageSize} onChange={event => { setDetailPageSize(Number(event.target.value)); setDetailPage(1); }}><option value={10}>10 条</option><option value={15}>15 条</option><option value={30}>30 条</option></select></label>
            <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="按状态筛选执行明细">
              {TABLE_FILTERS.map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  className={cn(
                    "rounded-full px-3 py-1.5 text-xs transition-colors",
                    tableFilter === key
                      ? "bg-primary text-white"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200",
                  )}
                  onClick={() => {
                    setTableFilter(key);
                    setTablePage(1);
                    setDetailPage(1);
                  }}
                >
                  {label}
                  <span className={cn("ml-1", tableFilter === key ? "text-white/80" : "text-slate-400")}>
                    {filterCounts[key]}
                  </span>
                </button>
              ))}
            </div>
            <label className="relative ml-auto flex items-center">
              <Search className="pointer-events-none absolute left-2.5 h-4 w-4 text-slate-400" aria-hidden="true" />
              <InputText
                className="w-56 pl-8 text-xs"
                placeholder="搜索商品名称 / ID / 淘宝ID"
                aria-label="搜索执行明细"
                value={tableQuery}
                onChange={(event) => {
                  setTableQuery(event.target.value);
                  setTablePage(1);
                  setDetailPage(1);
                }}
              />
            </label>
            <Button
              type="button"
              variant="secondary"
              className="min-h-9 shrink-0 px-3 text-xs text-red-600 hover:bg-red-50 hover:border-red-200"
              disabled={busy || running || clearableRows.length === 0}
              onClick={() => setBulkClearOpen(true)}
            >
              {pending.has("run.clearItems") ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : null}
              {selectedCandidates.length ? `清除所选记录(${clearableRows.length})` : tableFilterActive ? `清除筛选记录(${clearableRows.length})` : "一键清除全部"}
            </Button>
          </div>
        }
      >
        <table className="w-full min-w-[1160px] table-fixed border-collapse text-left text-sm">
          <colgroup>
            <col className="w-52" />
            <col className="w-44" />
            <col className="w-36" />
            <col className="w-44" />
            <col className="w-28" />
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
              <th className="whitespace-nowrap px-4 py-3 font-medium">主视频状态</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">耗时</th>
              <th className="sticky right-0 z-20 whitespace-nowrap border-l border-border bg-slate-50 px-4 py-3 font-medium shadow-[-8px_0_14px_-12px_rgba(22,62,53,0.55)]" data-column="actions">操作</th>
            </tr>
          </thead>
          <tbody>
            {detailRows.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-10 text-center text-slate-400">
                  {validRows.length === 0 ? "暂无可执行商品" : tableFilterActive ? "没有符合筛选条件的记录" : "暂无可执行商品"}
                </td>
              </tr>
            ) : (
              detailRows.map((row) => {
                const complete = isRowComplete(row, imageStrategy);
                const pictures = imageStatus(row, imageStrategy);
                const video = videoStatus(row);
                return (
                <tr key={`run-${row.row}`} className={cn("border-t border-border", highlightRow === row.row && "bg-emerald-50")}>
                  <td className="px-4 py-3" title={`${row.product_id} · 第${row.row}行`}>
                    <span className="run-product-title">{row.product_id}<span className="ml-2 text-xs text-slate-400">第{row.row}行</span></span>
                  </td>
                  <td className="overflow-hidden px-4 py-2"><ProductItemId value={row.taobao_item_id} /></td>
                  <td className="overflow-hidden whitespace-nowrap px-4 py-3" title={row.execution || "未执行"}>
                    <span className={cn("inline-block max-w-full truncate rounded-full px-2.5 py-1 text-xs", {
                      "bg-emerald-50 text-emerald-700": complete,
                      "bg-sky-50 text-sky-700": !isRowAttention(row) && !complete && ((row.execution || "").startsWith("已入库") || row.execution === "已填写未提交"),
                      "bg-amber-50 text-amber-800": isRowAttention(row) && !["失败", "提交失败"].includes(row.execution),
                      "bg-red-50 text-destructive": ["失败", "提交失败"].includes(row.execution),
                      "bg-slate-100 text-slate-600": row.execution === "未执行",
                    })}>{row.execution}</span>
                  </td>
                  <td className="overflow-hidden whitespace-nowrap px-4 py-3 text-xs text-slate-600" title={warehouseStatus(row).label}>
                    {warehouseStatus(row).label}
                  </td>
                  <td className="overflow-hidden whitespace-nowrap px-4 py-3">
                    <span className={cn("inline-block max-w-full truncate rounded-full px-2.5 py-1 text-xs", {
                      "bg-emerald-50 text-emerald-700": pictures.tone === "success",
                      "bg-amber-50 text-amber-800": pictures.tone === "warning" || pictures.tone === "active",
                      "bg-red-50 text-destructive": pictures.tone === "danger",
                      "bg-slate-100 text-slate-400": pictures.tone === "neutral",
                    })}>{pictures.label}</span>
                  </td>
                  <td className="overflow-hidden whitespace-nowrap px-4 py-3">
                    <span className="row-state" data-tone={video.tone} title={row.video_warning || row.video_name || video.label}><span>{video.label}</span></span>
                  </td>
                  <td className="overflow-hidden whitespace-nowrap px-4 py-3 text-xs text-slate-600" title={row.duration_seconds ? `本次入库耗时 ${row.duration_seconds} 秒` : undefined}>
                    {formatDuration(row.duration_seconds)}
                  </td>
                  <td className={cn(
                    "sticky right-0 z-10 border-l border-border bg-white px-4 py-3 shadow-[-8px_0_14px_-12px_rgba(22,62,53,0.55)]",
                    highlightRow === row.row && "bg-emerald-50",
                  )} data-column="actions">
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
                );
              })
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
      <ConfirmDialog
        open={bulkClearOpen}
        title="一键清除执行记录"
        destructive
        confirmLabel="清除"
        onClose={() => setBulkClearOpen(false)}
        onConfirm={() => {
          const rows = clearableRows.map((row) => row.row);
          setBulkClearOpen(false);
          setSelectedRows(new Set());
          if (rows.length > 0) onClearItems(rows);
        }}
      >
        <p>
          确定要清除 {clearableRows.length} 条执行记录吗？
          {selectedCandidates.length ? "（仅清除所选商品中的记录）" : tableFilterActive ? "（仅清除当前筛选和搜索结果中的记录）" : ""}
        </p>
        {warehousedClearCount > 0 ? (
          <p className="mt-2">
            其中 {warehousedClearCount} 条已入库（含淘宝商品 ID），清除后下次执行会重新建档入库，可能产生重复商品。
          </p>
        ) : (
          <p className="mt-2">清除后对应商品将恢复为「未执行」，下次执行时重新入库。</p>
        )}
        <p className="mt-2 font-medium text-destructive">此操作不可撤销。</p>
      </ConfirmDialog>
    </section>
  );
}
