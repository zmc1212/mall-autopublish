import type { WorkbookRow } from "../types";

const ATTENTION = new Set(["失败", "暂停", "提交失败", "提交待核实", "结果待核实", "已停止"]);
const UNCERTAIN = new Set(["submit_pending", "material_upload_pending", "material_adopt_pending"]);
const STRATEGY_TARGETS: Record<string, Set<string>> = {
  slim_material: new Set(["slim_material"]),
  publish_page: new Set(["publish_page"]),
  both: new Set(["slim_material", "publish_page"]),
};

export function isRowAttention(row: WorkbookRow) {
  return ATTENTION.has(row.execution) || UNCERTAIN.has(row.flow_stage || "") || row.spec_image_stage === "submit_pending" || (row.flow_stage !== "complete" && Boolean(row.last_error));
}

function targetsFor(strategy: string | undefined) {
  return STRATEGY_TARGETS[strategy || ""] || new Set<string>();
}

function completedTargets(row: WorkbookRow) {
  return targetsFor(row.sku_image_strategy);
}

function targetStrategy(row: WorkbookRow, selected?: string) {
  return selected || row.sku_image_strategy || "slim_material";
}

function strategyLabel(strategy: string | undefined) {
  if (strategy === "both") return "两类图片已核验";
  if (strategy === "publish_page") return "规格图已核验";
  if (strategy === "slim_material") return "搜索主图已核验";
  return "图片已核验";
}

function pendingImageLabel(target: string, completed: string | undefined) {
  if (target === "both" && completed === "slim_material") return "规格图待核验";
  if (target === "both" && completed === "publish_page") return "搜索主图待核验";
  if (target === "publish_page" && completed !== "publish_page") return "规格图待核验";
  if (target === "slim_material" && completed !== "slim_material") return "搜索主图待核验";
  return "图片待继续";
}

/** 与后端 _row_flow_done 对齐；selected 是当前批次的图片策略。 */
export function isRowComplete(row: WorkbookRow, selected?: string) {
  if (isRowAttention(row)) return false;
  const stage = (row.flow_stage || "").trim();
  if (stage) {
    if (stage !== "complete") return false;
    if (["publish_page", "both"].includes(targetStrategy(row, selected)) && ["spec-column-v1", "both-images-v1"].includes(row.flow_version || "")) return false;
    const target = targetsFor(targetStrategy(row, selected));
    const completed = completedTargets(row);
    return target.size > 0 && [...target].every((item) => completed.has(item));
  }
  if (row.flow_version) return false;
  if (row.taobao_item_id) return false;
  return false;
}
export type RowTone = "success" | "active" | "warning" | "danger" | "neutral";
export interface RowStatus { label: string; tone: RowTone }
export function videoStatus(row: WorkbookRow): RowStatus {
  const states: Record<string, RowStatus> = {
    uploading: { label: "上传中", tone: "active" },
    bound: { label: "待保存", tone: "active" },
    uploaded: { label: "已上传", tone: "success" },
    failed: { label: "上传失败", tone: "danger" },
    uncertain: { label: "上传待核实", tone: "warning" },
    paused: { label: "已暂停", tone: "warning" },
    invalid: { label: "格式错误", tone: "danger" },
  };
  const known = row.video_status ? states[row.video_status] : undefined;
  if (known) return known;
  if (row.video_warning) return { label: "上传失败", tone: "danger" };
  if (!row.video_name) return { label: "未提供", tone: "neutral" };
  if (row.video_ok === false) return { label: "格式错误", tone: "danger" };
  if (row.taobao_item_id || row.execution?.startsWith("已入库")) return { label: "待核验", tone: "warning" };
  return { label: "待上传", tone: "neutral" };
}
export function warehouseStatus(row: WorkbookRow): RowStatus {
  if (row.taobao_item_id && row.spec_image_stage === "submit_pending") return { label: "已入库", tone: "success" };
  if (row.flow_stage === "submit_pending" || ["提交待核实", "结果待核实"].includes(row.execution)) return { label: "待核实", tone: "warning" };
  if (row.taobao_item_id || row.execution?.startsWith("已入库")) return { label: "已入库", tone: "success" };
  if (["失败", "提交失败"].includes(row.execution)) return { label: "入库失败", tone: "danger" };
  if (row.flow_stage === "filling") return { label: "填写资料", tone: "active" };
  if (row.flow_stage === "filled" || row.execution === "已填写未提交") return { label: "待提交", tone: "active" };
  if (isRowAttention(row)) return { label: row.execution || "需关注", tone: "warning" };
  return { label: "待入库", tone: "neutral" };
}
export function imageStatus(row: WorkbookRow, selected?: string): RowStatus {
  if (isRowComplete(row, selected)) return { label: strategyLabel(row.sku_image_strategy || targetStrategy(row, selected)), tone: "success" };
  const phase = row.flow_stage || "";
  if (row.spec_image_stage === "submit_pending") return { label: "规格图保存待核实", tone: "warning" };
  if (phase === "material_upload_pending") return { label: "上传待核实", tone: "warning" };
  if (phase === "material_adopt_pending") return { label: "采纳待核实", tone: "warning" };
  if (isRowAttention(row)) return { label: "需关注", tone: "warning" };
  if (phase === "complete") return { label: pendingImageLabel(targetStrategy(row, selected), row.sku_image_strategy), tone: "active" };
  if (phase === "material_recognizing") return { label: "识别素材中", tone: "active" };
  if (["material_reviewed", "material_verifying"].includes(phase)) return { label: "核验图片中", tone: "active" };
  if (row.sku_image_strategy === "both" && row.spec_image_stage === "complete") return { label: "规格图已核验", tone: "active" };
  if (row.taobao_item_id || ["created", "material_prepared"].includes(phase)) return { label: "待补图", tone: "active" };
  return { label: "待处理", tone: "neutral" };
}
