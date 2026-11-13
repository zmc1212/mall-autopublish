import { Check, ChevronDown, ChevronRight, PanelRightClose, Settings2 } from "lucide-react";

import type { ActiveWorker, JobState, WorkbookRow } from "../types";
import cn from "../utils/classnames";
import { imageStatus, isRowAttention, isRowComplete, warehouseStatus } from "../utils/rowState";

import LiveSteps from "./LiveSteps";

const STAGES = ["资料", "入库", "补图核验", "完成"];

const WORKER_STATUS_LABELS: Record<string, string> = {
  running: "处理中",
  queued: "等待中",
  completed: "已完成",
  paused: "已暂停",
  stopped: "已停止",
  error: "失败",
};

function formatWorkerTime(seconds: number | null | undefined) {
  if (!seconds) return "—";
  const date = new Date(seconds * 1000);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function findWorkerRow(job: JobState | null, worker: ActiveWorker) {
  const rows = job?.rows || [];
  if (worker.row != null && worker.product_id) {
    return rows.find((row) => row.row === worker.row && row.product_id === worker.product_id);
  }
  if (worker.row != null) return rows.find((row) => row.row === worker.row);
  if (worker.product_id) return rows.find((row) => row.product_id === worker.product_id);
  return undefined;
}

function workerStageIndex(worker: ActiveWorker, row: WorkbookRow | undefined, imageStrategy?: string) {
  if (row && isRowComplete(row, imageStrategy)) return 3;
  // A completed worker without a row snapshot can still show its terminal
  // state, but a row snapshot is authoritative and must pass isRowComplete.
  if (!row && worker.status === "completed") return 3;

  const flowStage = row?.flow_stage || "";
  if (["material_prepared", "material_upload_pending", "material_recognizing", "material_reviewed", "material_adopt_pending", "material_verifying"].includes(flowStage)) {
    return 2;
  }
  if (flowStage === "created" || Boolean(row?.taobao_item_id)) return 1;

  const phase = `${worker.phase || ""}`.toLowerCase();
  if (/(补图|素材|图片|主图|规格图|详情图|核验|识别|采纳|material|upload|recogniz|adopt|verif)/.test(phase)) return 2;
  if (/(入库|仓库|提交|warehouse|submit)/.test(phase)) return 1;
  return 0;
}

function workerStageLabel(worker: ActiveWorker, row: WorkbookRow | undefined, stageIndex: number, imageStrategy?: string) {
  if (worker.stalled) return "可能停滞，请检查浏览器现场";
  if (worker.status === "queued") return "等待执行槽";
  if (worker.status === "paused" || worker.status === "stopped") return "已暂停，等待继续";
  if (worker.status === "error") return "执行失败，需要处理";
  if (stageIndex === 3) return "已完成";
  if (stageIndex === 2) return row ? imageStatus(row, imageStrategy).label : "补图核验";
  if (stageIndex === 1) return row ? warehouseStatus(row).label : "入库";
  return worker.phase || "填写资料";
}

function workerStatusLabel(worker: ActiveWorker, stageIndex: number) {
  if (worker.stalled) return "需关注";
  if (stageIndex === 3) return "已完成";
  return WORKER_STATUS_LABELS[worker.status || "running"] || "处理中";
}

function statusClass(worker: ActiveWorker, stageIndex: number) {
  if (worker.stalled || worker.status === "error") return "text-amber-700";
  if (stageIndex === 3) return "text-primary";
  if (worker.status === "paused" || worker.status === "stopped") return "text-amber-700";
  return "text-slate-500";
}

export interface RunInspectorProps {
  job: JobState | null;
  hidden?: boolean;
  onCollapse?: () => void;
  onAttention: () => void;
  onDetails: (row: WorkbookRow) => void;
  onSettings: () => void;
  onLogs?: () => void;
  imageStrategy?: string;
}

export default function RunInspector({ job, hidden = false, onCollapse, onAttention, onDetails, onSettings, onLogs, imageStrategy }: RunInspectorProps) {
  // Older servers may expose a numeric active worker count. Only render worker
  // records that identify a real product; empty slots must not look active.
  const workers = Array.isArray(job?.active_workers)
    ? job.active_workers.filter((worker) => Boolean(worker.product_id) || worker.row != null)
    : [];
  const runningWorkerCount = workers.filter((worker) => worker.status === "running").length;
  const concurrency = job?.concurrency || Math.max(1, workers.length);
  const attentionRows = (job?.rows || []).filter((row) => row.validation === "通过").filter(isRowAttention);
  const attentionCount = attentionRows.length;
  const firstAttention = attentionRows[0];
  const firstIssue = firstAttention
    ? firstAttention.errors?.[0] || firstAttention.last_error || imageStatus(firstAttention, imageStrategy).label || "需要核对执行结果"
    : "当前没有需要处理的商品";

  return (
    <aside id="run-progress-panel" className="run-inspector" aria-label="执行详情" hidden={hidden}>
      <section data-testid="active-workers">
        <div className="inspector-title">
          <div>
            <h3>正在执行</h3>
            <span>{runningWorkerCount} / {concurrency} 个执行槽</span>
          </div>
          <div className="flex items-center gap-1">
            <button className="rounded p-2 text-slate-600 hover:bg-muted" type="button" onClick={onSettings} aria-label="打开执行设置" title="执行设置">
              <Settings2 className="h-4 w-4" aria-hidden="true" />
            </button>
            {onCollapse && <button className="rounded p-2 text-slate-600 hover:bg-muted" type="button" onClick={onCollapse} aria-label="收起执行进度" title="收起执行进度" aria-expanded="true" aria-controls="run-progress-panel">
              <PanelRightClose className="h-4 w-4" aria-hidden="true" />
            </button>}
          </div>
        </div>
        <div className="worker-list">
          {workers.length === 0 ? (
            <div className="empty-work">
              <h3>暂无活动商品</h3>
              <p>开始入库后，这里会显示实际执行槽和当前阶段。</p>
            </div>
          ) : (
            workers.map((worker) => {
              const row = findWorkerRow(job, worker);
              const stageIndex = workerStageIndex(worker, row, imageStrategy);
              const stageLabel = workerStageLabel(worker, row, stageIndex, imageStrategy);
              return (
                <article key={worker.worker_id} className="worker-card">
                  <div className="worker-card-header">
                    <strong>执行槽 {worker.worker_id}</strong>
                    <span className={cn("text-xs", statusClass(worker, stageIndex))}>
                      {workerStatusLabel(worker, stageIndex)}
                    </span>
                  </div>
                  <div className="min-w-0">
                    <strong className="block truncate text-foreground" title={row?.title || worker.product_id || undefined}>
                      {row?.title || worker.product_id || "当前商品"}
                    </strong>
                    <span className="mt-1 block truncate text-xs text-slate-500" title={worker.product_id || undefined}>
                      {worker.product_id || "未返回商品编号"}{worker.row == null ? "" : ` · 第 ${worker.row} 行`}
                    </span>
                  </div>
                  <p className="worker-phase" title={worker.phase || undefined}>当前阶段：{stageIndex === 3 || worker.status !== "running" ? stageLabel : worker.phase || stageLabel}</p>
                  <div className="worker-stages" aria-label={`执行阶段：${STAGES[stageIndex]}`}>
                    {STAGES.map((label, index) => {
                      const current = index === stageIndex;
                      const completed = index < stageIndex || stageIndex === 3;
                      return (
                        <span
                          key={label}
                          data-completed={completed ? "true" : "false"}
                          data-reached={index <= stageIndex ? "true" : "false"}
                          data-current={current ? "true" : "false"}
                          aria-current={current ? "step" : undefined}
                        >
                          <i className="stage-checkpoint" aria-hidden="true">
                            {completed ? <Check className="h-3 w-3" /> : null}
                          </i>
                          {label}
                        </span>
                      );
                    })}
                  </div>
                  <p className="mt-3 text-[11px] text-slate-500">
                    开始 {formatWorkerTime(worker.started_at)} · 最近活动 {formatWorkerTime(worker.activity_at)}
                  </p>
                </article>
              );
            })
          )}
        </div>
        {workers.length > 2 ? (
          <p className="worker-scroll-hint"><ChevronDown className="mr-1 inline h-3.5 w-3.5" aria-hidden="true" />共 {workers.length} 个任务，上下滚动查看</p>
        ) : null}
      </section>

      <section className="inspector-section">
        <div className="inspector-title">
          <h3>需要关注 <span className={cn("ml-1", attentionCount ? "text-amber-700" : "text-slate-500")}>{attentionCount}</span></h3>
          <button type="button" onClick={onAttention} disabled={attentionCount === 0}>
            查看全部 <ChevronRight className="ml-0.5 inline h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
        <div className={firstAttention ? "attention-note" : "inspector-clear"}>
          {firstAttention ? (
            <>
              <strong className="block truncate" title={firstAttention.title || firstAttention.product_id}>
                {firstAttention.title || firstAttention.product_id || `第 ${firstAttention.row} 行`}
              </strong>
              <p className="mt-1">{firstIssue}</p>
              <p className="mt-1 text-[11px] text-amber-700/80">
                入库：{warehouseStatus(firstAttention).label} · 图片：{imageStatus(firstAttention, imageStrategy).label}
              </p>
              <button type="button" className="mt-3 inline-flex items-center font-medium text-amber-900 underline-offset-2 hover:underline" onClick={() => onDetails(firstAttention)}>
                查看详情 <ChevronRight className="ml-1 h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </>
          ) : (
            <p>暂无需要处理的商品。</p>
          )}
        </div>
      </section>

      <LiveSteps job={job} onAllLogs={onLogs} />
    </aside>
  );
}
