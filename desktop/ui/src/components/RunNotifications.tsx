import { CheckCircle2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { JobState, WorkbookRow } from "../types";
import { Button } from "../theme";
import formatDuration from "../utils/formatDuration";

const CREATED_STAGES = new Set(["created", "material_prepared", "material_upload_pending", "material_recognizing", "material_reviewed", "material_adopt_pending", "material_verifying", "complete"]);
export function isWarehoused(row: WorkbookRow) {
  return Boolean(row.taobao_item_id) && CREATED_STAGES.has(row.flow_stage || "");
}

export default function RunNotifications({ job, busy, onDetails, onEdit }: {
  job: JobState | null;
  busy: boolean;
  onDetails: (row: WorkbookRow) => void;
  onEdit: (row: WorkbookRow) => void;
}) {
  const baseline = useRef<{ source: string; seen: Set<string> } | null>(null);
  const signatureRef = useRef("");
  const [queue, setQueue] = useState<WorkbookRow[]>([]);
  useEffect(() => {
    if (!job) return;
    const source = `${job.workspace_path || ""}|${job.workbook_path}`;
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
  const first = queue[0];
  if (!first) return null;
  const row = job?.rows.find(item => item.row === first.row && item.product_id === first.product_id && item.taobao_item_id === first.taobao_item_id) || first;
  const dismiss = () => setQueue(current => current.slice(1));
  return (
    <aside className="fixed bottom-5 right-5 z-40 w-[min(390px,calc(100vw-2.5rem))] rounded-2xl border border-emerald-200 bg-white p-4 shadow-xl" aria-label="入库成功通知">
      <div className="flex items-start gap-3">
        <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" aria-hidden="true" />
        <div className="min-w-0 flex-1" role="status" aria-live="polite">
          <p className="font-semibold">商品已成功入库</p>
          <p className="mt-1 break-words text-sm">{row.title || row.product_id}</p>
          <p className="mt-1 text-xs text-slate-500">{row.product_id} · 第 {row.row} 行 · ID {row.taobao_item_id}</p>
          {row.duration_seconds ? (
            <p className="mt-1 text-xs text-slate-500">本次耗时 {formatDuration(row.duration_seconds)}</p>
          ) : null}
          <p className="mt-2 text-xs text-emerald-700">{row.flow_stage === "complete" ? "图片核验完成，商品保存在仓库中。" : "商品已建档入库；图片处理尚未完成。"}</p>
        </div>
        <button className="rounded p-1 text-slate-500 hover:bg-slate-100" aria-label="关闭入库通知" onClick={dismiss}><X className="h-4 w-4" /></button>
      </div>
      <div className="mt-3 flex gap-2">
        <Button variant="secondary" className="min-h-8 text-xs" onClick={() => { onDetails(row); dismiss(); }}>查看详情</Button>
        <Button variant="secondary" className="min-h-8 text-xs" disabled={busy || !row.edit_url} onClick={() => onEdit(row)}>编辑商品</Button>
        {queue.length > 1 && <button className="ml-auto text-xs text-slate-500" onClick={dismiss}>下一条（{queue.length - 1}）</button>}
      </div>
    </aside>
  );
}
