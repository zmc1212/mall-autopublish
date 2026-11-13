import { CircleAlert, ExternalLink, FolderOpen, Play, ScrollText, X } from "lucide-react";
import { useRef } from "react";
import type { WorkbookRow } from "../types";
import { Button } from "../theme";
import { useDialogBehavior } from "../utils/dialogFocus";
import { imageStatus, isRowAttention, isRowComplete, videoStatus, warehouseStatus } from "../utils/rowState";
import ProductItemId from "./ProductItemId";
import ProductThumbnail from "./ProductThumbnail";

interface ProductDrawerProps {
  row: WorkbookRow | null;
  imageStrategy: string;
  stageLabel: string;
  busy: boolean;
  running: boolean;
  startBlockedReason: string;
  onClose: () => void;
  onOpenItem: (row: WorkbookRow, action: "view" | "edit") => void;
  onOpenPack?: (row: WorkbookRow) => void;
  onPrepare?: () => void;
  onConnect?: () => void;
  onSettings?: () => void;
  onLogs?: (productId?: string) => void;
  onInspectBrowser?: () => void;
  onResume: (row: WorkbookRow) => void;
}

export default function ProductDrawer({ row, imageStrategy, stageLabel, busy, running, startBlockedReason,
  onClose, onOpenItem, onOpenPack, onPrepare, onConnect, onSettings, onLogs, onInspectBrowser, onResume }: ProductDrawerProps) {
  const ref = useRef<HTMLElement>(null);
  useDialogBehavior(Boolean(row), onClose, ref);
  if (!row) return null;
  const warehouse = warehouseStatus(row), pictures = imageStatus(row, imageStrategy), video = videoStatus(row);
  const complete = isRowComplete(row, imageStrategy);
  const attention = isRowAttention(row) || Boolean(row.video_warning);
  const uncertain = ["submit_pending", "material_upload_pending", "material_adopt_pending"].includes(row.flow_stage || "") || row.spec_image_stage === "submit_pending";
  const reason = [row.last_error, ...(row.errors || []), row.video_warning, row.notice]
    .filter((value, index, values) => value && values.indexOf(value) === index).join("\n");
  const loginIssue = /登录|浏览器|连接/.test(reason);
  return <div className="product-drawer-overlay" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="product-drawer" ref={ref} role="dialog" aria-modal="true" aria-labelledby="product-detail-title" tabIndex={-1}>
      <header className="product-drawer-heading">
        <div><h2 id="product-detail-title">商品详情</h2><p className="mt-1 text-xs text-slate-600">第 {row.row} 行 · {row.product_id}</p></div>
        <button type="button" className="rounded-lg p-2 hover:bg-muted" aria-label="关闭商品详情" onClick={onClose}><X className="h-5 w-5" /></button>
      </header>
      <div className="product-drawer-body">
        <div className="flex items-start gap-3"><ProductThumbnail url={row.preview_url} title={row.title || row.product_id} /><h3 className="min-w-0 break-words text-base font-semibold leading-7">{row.title || row.product_id}</h3></div>
        <dl className="product-facts">
          {[{ name: "入库状态", state: warehouse }, { name: "图片状态", state: pictures }, { name: "主视频状态", state: video }].map(item => <div key={item.name}><dt>{item.name}</dt><dd className="row-state" data-tone={item.state.tone}>{item.state.label}</dd></div>)}
          <div><dt>淘宝商品 ID</dt><dd><ProductItemId value={row.taobao_item_id} /></dd></div>
          <div><dt>最近流程记录</dt><dd>{stageLabel}</dd></div>
          {row.updated_at && <div><dt>记录更新时间</dt><dd className="break-all">{row.updated_at}</dd></div>}
        </dl>
        {attention || reason ? <section className="attention-note" aria-label="当前问题">
          <h3 className="flex items-center gap-2 font-semibold"><CircleAlert className="h-4 w-4 shrink-0" />{uncertain ? "需要先核对结果" : "当前问题与原因"}</h3>
          <p className="mt-2 whitespace-pre-wrap break-words">{reason || "当前执行未完成，请检查商品页面和对应日志。"}</p>
        </section> : <p className="rounded-lg bg-muted p-3 text-sm leading-6">{complete ? "当前图片处理目标已核验，商品保存在仓库中。" : "进度会随任务更新；已有商品会沿用原商品 ID 继续处理。"}</p>}
        <section aria-label="下一步操作">
          <h3 className="text-sm font-semibold">下一步</h3>
          <p className="mt-2 text-sm leading-7 text-slate-600">{uncertain
            ? "先在浏览器核对是否已保存或采纳。确认后从断点继续，保留已有商品 ID 和执行记录。"
            : loginIssue ? "先检查浏览器连接和登录状态，再继续此商品。"
              : attention ? "检查下方商品资料、素材和对应日志，修正后继续此商品。"
                : complete ? "可打开商品页面检查内容，或关闭详情继续查看本批结果。" : "准备完成后可单独执行此商品，已保存的进度会继续保留。"}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {row.view_url && <Button variant="secondary" disabled={busy} onClick={() => onOpenItem(row, "view")}><ExternalLink className="h-4 w-4" />查看商品</Button>}
            {row.edit_url && <Button variant="secondary" disabled={busy} onClick={() => onOpenItem(row, "edit")}>编辑商品</Button>}
            {row.pack && onOpenPack && <Button variant="secondary" onClick={() => onOpenPack(row)}><FolderOpen className="h-4 w-4" />打开素材目录</Button>}
            {onLogs && <Button variant="secondary" onClick={() => onLogs(row.product_id)}><ScrollText className="h-4 w-4" />查看此商品日志</Button>}
            {attention && onPrepare && <Button variant="secondary" onClick={onPrepare}>检查商品资料与模板</Button>}
            {loginIssue && onConnect && <Button variant="secondary" onClick={onConnect}>连接店铺</Button>}
            {(uncertain || loginIssue) && onInspectBrowser && <Button variant="secondary" disabled={busy} onClick={onInspectBrowser}>查看浏览器现场</Button>}
            {onSettings && <Button variant="ghost" onClick={onSettings}>执行设置</Button>}
          </div>
        </section>
      </div>
      <footer className="product-drawer-footer">
        {startBlockedReason && <p className="mb-3 text-xs text-amber-800">{startBlockedReason}</p>}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Button variant="secondary" onClick={onClose}>返回商品列表</Button>
          {!complete && <Button disabled={busy || running || Boolean(startBlockedReason)} onClick={() => onResume(row)}><Play className="h-4 w-4" />{uncertain ? "核对后继续此商品" : "执行此商品"}</Button>}
        </div>
      </footer>
    </section>
  </div>;
}
