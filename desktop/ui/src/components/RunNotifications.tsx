import { CheckCircle2, CircleAlert, Info, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { JobState, WorkbookRow } from "../types";
import { Button } from "../theme";
import formatDuration from "../utils/formatDuration";
import { isRowAttention, isRowComplete } from "../utils/rowState";

export function isWarehoused(row: WorkbookRow) {
  // 旧清单可能没有 flow_stage；商品 ID 或历史“已入库”文案本身就是入库事实。
  return Boolean(String(row.taobao_item_id || "").trim()) || Boolean(row.execution?.startsWith("已入库"));
}

export default function RunNotifications({ job, busy, imageStrategy, onDetails, onEdit }: {
  job: JobState | null;
  busy: boolean;
  imageStrategy?: string;
  onDetails: (row: WorkbookRow) => void;
  onEdit: (row: WorkbookRow) => void;
}) {
  const baseline = useRef<{ source: string; seen: Set<string> } | null>(null);
  const signatureRef = useRef("");
  const [queue, setQueue] = useState<WorkbookRow[]>([]);
  useEffect(() => {
    if (!job) return;
    const source = `${job.workspace_path || ""}|${job.workbook_path}|${job.started_at || ""}`;
    const key = (row: WorkbookRow) => `${row.row}|${row.product_id}|${row.taobao_item_id}`;
    const created = job.rows.filter(isWarehoused);
    // 入库名单没变化时直接跳过，避免每轮轮询都重建集合
    const signature = `${source}|${created.map(key).join(";")}`;
    if (signature === signatureRef.current) return;
    signatureRef.current = signature;
    if (!baseline.current || baseline.current.source !== source) {
      baseline.current = { source, seen: new Set(created.map(key)) };
      setQueue([]);
      return;
    }
    const added = created.filter(row => !baseline.current!.seen.has(key(row)));
    created.forEach(row => baseline.current!.seen.add(key(row)));
    if (added.length) setQueue(current => [...current, ...added]);
  }, [job]);
  const currentRows = queue.map(source => job?.rows.find(item => item.row === source.row && item.product_id === source.product_id && item.taobao_item_id === source.taobao_item_id) || source);
  const attentionRows = currentRows.filter(isRowAttention);
  const verifiedCount = currentRows.filter(row => isRowComplete(row, imageStrategy)).length;
  useEffect(() => {
    if (!queue.length || attentionRows.length) return;
    const timer = window.setTimeout(() => setQueue([]), 8000);
    return () => window.clearTimeout(timer);
  }, [queue, attentionRows.length]);
  const first = attentionRows[0] || currentRows[currentRows.length - 1];
  if (!first) return null;
  const row = job?.rows.find(item => item.row === first.row && item.product_id === first.product_id && item.taobao_item_id === first.taobao_item_id) || first;
  const verified = verifiedCount === currentRows.length;
  const dismiss = () => setQueue([]);
  return (
    <aside className={attentionRows.length
      ? "fixed bottom-5 right-5 z-40 w-[min(390px,calc(100vw-2.5rem))] rounded-2xl border border-amber-200 bg-white p-4 shadow-xl"
      : verified
      ? "fixed bottom-5 right-5 z-40 w-[min(390px,calc(100vw-2.5rem))] rounded-2xl border border-emerald-200 bg-white p-4 shadow-xl"
      : "fixed bottom-5 right-5 z-40 w-[min(390px,calc(100vw-2.5rem))] rounded-2xl border border-blue-200 bg-white p-4 shadow-xl"} aria-label="批次入库通知">
      <div className="flex items-start gap-3">
        {attentionRows.length ? <CircleAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" aria-hidden="true" /> : verified ? (
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" aria-hidden="true" />
        ) : (
          <Info className="mt-0.5 h-5 w-5 shrink-0 text-blue-600" aria-hidden="true" />
        )}
        <div className="min-w-0 flex-1" role="status" aria-live="polite">
          <p className="font-semibold">新建档入库 {currentRows.length} 件</p>
          <p className="mt-1 text-sm leading-6 text-slate-600">{verifiedCount} 件完成图片核验{attentionRows.length ? ` · ${attentionRows.length} 件需要核对` : verifiedCount < currentRows.length ? ` · ${currentRows.length - verifiedCount} 件图片仍在处理` : ""}</p>
          <p className="mt-1 truncate text-xs" title={row.title}>{attentionRows.length ? "需核对" : "最近商品"}：{row.title || row.product_id}</p>
          <p className="mt-1 text-xs text-slate-500">{row.product_id} · 第 {row.row} 行 · ID {row.taobao_item_id}</p>
          {row.duration_seconds ? (
            <p className="mt-1 text-xs text-slate-500">本次耗时 {formatDuration(row.duration_seconds)}</p>
          ) : null}
          <p className={verified ? "mt-2 text-xs text-emerald-700" : "mt-2 text-xs text-blue-700"}>
            {attentionRows.length ? "已有商品记录已保留，请先核对结果再继续。" : verified ? "图片核验完成，商品保存在仓库中。" : "商品已建档入库；图片处理仍在继续，完成后会更新状态。"}
          </p>
        </div>
        <button className="rounded p-1 text-slate-500 hover:bg-slate-100" aria-label="关闭入库通知" onClick={dismiss}><X className="h-4 w-4" /></button>
      </div>
      <div className="mt-3 flex gap-2">
        <Button variant="secondary" className="min-h-9 text-xs" onClick={() => { onDetails(row); dismiss(); }}>{attentionRows.length ? "处理需关注商品" : "查看最近商品"}</Button>
        <Button variant="secondary" className="min-h-8 text-xs" disabled={busy || !row.edit_url} onClick={() => onEdit(row)}>编辑商品</Button>
      </div>
    </aside>
  );
}
