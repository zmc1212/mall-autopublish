import { ArrowRight, Download, FileSpreadsheet, FolderOpen, FolderSearch, Loader2, RefreshCw, Save, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import type { ReactNode } from "react";

import { Button, InputText } from "../theme";
import type { JobState, WorkspaceDefaults, WorkspaceInfo } from "../types";
import cn from "../utils/classnames";
import { useDialogBehavior } from "../utils/dialogFocus";
import { usePagination } from "../utils/usePagination";

import DataTableDialog from "./DataTableDialog";
import ProductItemId from "./ProductItemId";
import { PanelFrame } from "./Sidebar";

interface WorkbookPanelProps {
  job: JobState | null;
  workspace: WorkspaceInfo | null;
  workspaceDraft: string;
  onWorkspaceDraft: (value: string) => void;
  excelDraft: string;
  onExcelDraft: (value: string) => void;
  defaults: WorkspaceDefaults;
  onDefaultsChange: (value: WorkspaceDefaults) => void;
  selectedCategories: string[];
  onSelectedCategoriesChange: (value: string[]) => void;
  busy: boolean;
  pending: ReadonlySet<string>;
  onPickWorkspace: () => void;
  onRescan: () => void;
  onOpenFolder: () => void;
  onSaveDefaults: () => void;
  onPickExcel: () => void;
  onImportExcel: () => void;
  onValidate: () => void;
  scanDecisionOpen: boolean;
  onCloseScanDecision: () => void;
  onOpenGeneratedWorkbook: () => void;
  onUseDefaults: () => void;
  onTemplate: () => void;
  className?: string;
}

function SelectField({
  id,
  value,
  options,
  disabled,
  onChange,
}: {
  id: string;
  value: string;
  options: string[];
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const names = options.includes(value) || !value ? options : [value, ...options];
  return (
    <select
      id={id}
      className="min-h-11 w-full rounded-lg border border-border bg-white px-3 text-sm text-foreground outline-none transition-colors duration-150 focus:border-primary disabled:cursor-not-allowed disabled:opacity-50"
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
    >
      {names.map((name) => (
        <option key={name} value={name}>
          {name}
        </option>
      ))}
    </select>
  );
}

function ScanDecisionDialog({
  open,
  count,
  busy,
  onClose,
  onOpenWorkbook,
  onUseDefaults,
}: {
  open: boolean;
  count: number;
  busy: boolean;
  onClose: () => void;
  onOpenWorkbook: () => void;
  onUseDefaults: () => void;
}) {
  const cardRef = useRef<HTMLElement>(null);
  useDialogBehavior(open, onClose, cardRef);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={cardRef}
        className="w-[min(560px,calc(100vw-2rem))] overflow-hidden rounded-lg border border-border bg-white shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="scan-decision-title"
      >
        <header className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h2 id="scan-decision-title" className="text-lg font-semibold text-foreground">商品清单已生成</h2>
            <p className="mt-1 text-sm text-slate-500">本次共扫描到 {count} 款商品。</p>
          </div>
          <button
            type="button"
            className="shrink-0 rounded-lg p-2 text-slate-500 transition-colors hover:bg-muted hover:text-foreground"
            aria-label="关闭提示"
            onClick={onClose}
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </header>
        <div className="px-5 py-4 text-sm leading-6 text-slate-600">
          <p>需要调整标题、品牌或价格时，可以先打开表格补充。</p>
          <p className="mt-2">不补充时，商品标题采用图片夹名称，品牌和其他必填属性使用中性笔模板默认值。</p>
        </div>
        <footer className="flex flex-wrap justify-end gap-2 border-t border-border px-5 py-4">
          <Button variant="secondary" disabled={busy} onClick={onOpenWorkbook}>
            <FileSpreadsheet className="h-4 w-4" aria-hidden="true" />
            打开表格补充
          </Button>
          <Button disabled={busy} onClick={onUseDefaults}>
            直接使用默认值
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Button>
        </footer>
      </section>
    </div>
  );
}

export default function WorkbookPanel({
  job,
  workspace,
  workspaceDraft,
  onWorkspaceDraft,
  excelDraft,
  onExcelDraft,
  defaults,
  onDefaultsChange,
  selectedCategories,
  onSelectedCategoriesChange,
  busy,
  pending,
  onPickWorkspace,
  onRescan,
  onOpenFolder,
  onSaveDefaults,
  onPickExcel,
  onImportExcel,
  onValidate,
  scanDecisionOpen,
  onCloseScanDecision,
  onOpenGeneratedWorkbook,
  onUseDefaults,
  onTemplate,
  className = "",
}: WorkbookPanelProps) {
  const rows = job?.rows || [];
  const spinIcon = (key: string, icon: ReactNode): ReactNode =>
    pending.has(key) ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : icon;
  const registry = workspace?.registry || { attributes: [], logistics: [], sales: [] };
  const scanErrors = workspace?.scan?.errors || [];
  const categories = workspace?.scan?.categories || [];
  const hasWorkspace = Boolean(job?.workspace_path || workspace?.path);
  const [tableOpen, setTableOpen] = useState(false);
  const { page: tablePage, setPage: setTablePage, pageRows: tableRows, pageSize } = usePagination(rows);
  return (
    <PanelFrame
      title="工作空间"
      hint="一款商品一个文件夹，程序生成一张总表。改标题和价格只改这一张表。关闭软件后会恢复上次工作空间。"
    >
      <div className={`grid h-full min-h-0 min-w-0 flex-1 grid-rows-[auto_auto_minmax(0,1fr)] gap-4 overflow-hidden ${className}`}>
        <div className="grid min-h-0 gap-4 lg:grid-cols-[minmax(0,1.05fr)_minmax(360px,0.95fr)]">
          <div className="rounded-2xl border border-border bg-white p-4">
          <label className="text-sm font-medium" htmlFor="workspace-path">
            工作空间目录
          </label>
          <InputText
            id="workspace-path"
            className="mt-2"
            value={workspaceDraft}
            onChange={(event) => onWorkspaceDraft(event.target.value)}
            placeholder="选择包含各款图片夹的目录"
            title={workspaceDraft}
          />
          <div className="mt-2 flex flex-wrap gap-2">
            <Button variant="secondary" onClick={onPickWorkspace} disabled={busy}>
              {spinIcon("workbook.pickWorkspace", <FolderOpen className="h-4 w-4" aria-hidden="true" />)}
              选择工作空间
            </Button>
            <Button variant="secondary" onClick={onRescan} disabled={busy || !hasWorkspace}>
              {spinIcon("workbook.rescan", <RefreshCw className="h-4 w-4" aria-hidden="true" />)}
              扫描更新
            </Button>
            <Button variant="ghost" onClick={onOpenFolder} disabled={!hasWorkspace && !workspaceDraft.trim()}>
              <FolderSearch className="h-4 w-4" aria-hidden="true" />
              打开资源管理器
            </Button>
          </div>
          <p className="mt-3 text-sm text-slate-500">
            {job?.workspace_path || job?.workbook_path
              ? `${job?.restored ? "已恢复上次工作空间。" : ""}当前 ${job?.count || 0} 条，通过 ${job?.valid || 0} 条，失败 ${job?.failed || 0} 条`
              : "尚未选择工作空间。把每款的主图、详情、规格图直接放进一级子文件夹。"}
          </p>
          {scanErrors.length > 0 ? (
            <p className="mt-2 text-xs leading-5 text-amber-800">
              扫描问题：{scanErrors.map((item) => `${item.folder}（${item.error}）`).join("；")}
            </p>
          ) : null}
        </div>
          {categories.length > 0 ? (
            <div className="min-h-0 rounded-2xl border border-border bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-sm font-medium">扫描类别</h3>
                <p className="mt-1 text-xs text-slate-500">只把勾选类别下的商品写入总表，选择会在此工作空间中保存。</p>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="ghost"
                  onClick={() => onSelectedCategoriesChange(categories.map((item) => item.name))}
                  disabled={busy || selectedCategories.length === categories.length}
                >
                  全选
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => onSelectedCategoriesChange([])}
                  disabled={busy || selectedCategories.length === 0}
                >
                  全不选
                </Button>
              </div>
            </div>
            <div className="mt-3 grid max-h-40 gap-2 overflow-y-auto pr-1 md:grid-cols-2 xl:grid-cols-2">
              {categories.map((category) => {
                const checked = selectedCategories.includes(category.name);
                return (
                  <label
                    key={category.name}
                    className="flex min-w-0 cursor-pointer items-start gap-3 rounded-md border border-border px-3 py-2.5"
                  >
                    <input
                      type="checkbox"
                      className="mt-0.5 h-4 w-4 shrink-0 accent-slate-900"
                      checked={checked}
                      disabled={busy}
                      onChange={(event) =>
                        onSelectedCategoriesChange(
                          event.target.checked
                            ? [...selectedCategories, category.name]
                            : selectedCategories.filter((item) => item !== category.name),
                        )
                      }
                    />
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium">{category.name}</span>
                      <span className="mt-0.5 block text-xs text-slate-500">
                        {category.product_count} 款
                        {category.error_count ? `，${category.error_count} 个问题` : ""}
                      </span>
                      {!category.template_found ? (
                        <span className="mt-1 block text-xs text-amber-800">{category.notice || "未配置同名商品属性模板"}</span>
                      ) : null}
                    </span>
                  </label>
                );
              })}
            </div>
            </div>
          ) : null}
        </div>
        <div className="min-h-0 overflow-hidden rounded-2xl border border-border bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-medium">批次默认</h3>
              <p className="mt-1 text-xs text-slate-500">新扫进来的夹会用这些值；已改过的标题、价格、模板不会被覆盖。</p>
            </div>
            <Button variant="secondary" onClick={onSaveDefaults} disabled={busy || !hasWorkspace}>
              {spinIcon("workbook.saveDefaults", <Save className="h-4 w-4" aria-hidden="true" />)}
              保存默认
            </Button>
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-2 lg:grid-cols-6">
            <label className="text-sm" htmlFor="ws-brand">
              品牌
              <InputText
                id="ws-brand"
                className="mt-1"
                value={defaults.brand}
                onChange={(event) => onDefaultsChange({ ...defaults, brand: event.target.value })}
                placeholder="如 卡游"
              />
            </label>
            <label className="text-sm" htmlFor="ws-attr">
              商品属性模板
              <div className="mt-1">
                <SelectField
                  id="ws-attr"
                  value={defaults.attributes_template}
                  options={registry.attributes}
                  onChange={(value) => onDefaultsChange({ ...defaults, attributes_template: value })}
                />
              </div>
            </label>
            <label className="text-sm" htmlFor="ws-log">
              物流模板
              <div className="mt-1">
                <SelectField
                  id="ws-log"
                  value={defaults.logistics_template}
                  options={registry.logistics}
                  onChange={(value) => onDefaultsChange({ ...defaults, logistics_template: value })}
                />
              </div>
            </label>
            <label className="text-sm" htmlFor="ws-sales">
              销售模板
              <div className="mt-1">
                <SelectField
                  id="ws-sales"
                  value={defaults.sales_template}
                  options={registry.sales}
                  onChange={(value) => onDefaultsChange({ ...defaults, sales_template: value })}
                />
              </div>
            </label>
            <label className="text-sm" htmlFor="ws-price">
              默认价格
              <InputText
                id="ws-price"
                className="mt-1"
                inputMode="decimal"
                value={String(defaults.price ?? "")}
                onChange={(event) => onDefaultsChange({ ...defaults, price: event.target.value })}
              />
            </label>
            <label className="text-sm" htmlFor="ws-stock">
              默认库存
              <InputText
                id="ws-stock"
                className="mt-1"
                inputMode="numeric"
                value={String(defaults.stock ?? "")}
                onChange={(event) => onDefaultsChange({ ...defaults, stock: event.target.value })}
              />
            </label>
          </div>
          <details className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <summary className="cursor-pointer text-sm font-medium text-slate-700">高级：单独导入 Excel</summary>
            <p className="mt-2 text-xs text-slate-500">已有总表、不走文件夹扫描时可用。工作空间才是主入口。</p>
            <div className="mt-3 flex flex-col gap-2 lg:flex-row">
              <InputText
                value={excelDraft}
                onChange={(event) => onExcelDraft(event.target.value)}
                placeholder="选择或粘贴商品清单.xlsx"
              />
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" onClick={onPickExcel} disabled={busy}>
                  {spinIcon("workbook.pickExcel", <FolderOpen className="h-4 w-4" aria-hidden="true" />)}
                  选择文件
                </Button>
                <Button variant="secondary" onClick={onImportExcel} disabled={busy || !excelDraft.trim()}>
                  {spinIcon("workbook.import", <Upload className="h-4 w-4" aria-hidden="true" />)}
                  导入
                </Button>
                <Button variant="secondary" onClick={onValidate} disabled={busy || !job?.workbook_path}>
                  {spinIcon("workbook.validate", <RefreshCw className="h-4 w-4" aria-hidden="true" />)}
                  校验
                </Button>
                <Button variant="ghost" onClick={onTemplate} disabled={busy}>
                  {spinIcon("workbook.template", <Download className="h-4 w-4" aria-hidden="true" />)}
                  下载空白模板
                </Button>
              </div>
            </div>
          </details>
        </div>
        <div className="flex h-fit items-start justify-between gap-4 rounded-2xl border border-border bg-white p-4">
          <div className="min-w-0">
            <h3 className="text-sm font-medium">商品明细</h3>
            <p className="mt-1 text-xs text-slate-500">
              {rows.length > 0
                ? `共 ${rows.length} 条商品，当前通过 ${job?.valid || 0} 条、失败 ${job?.failed || 0} 条。`
                : "选择工作空间后，商品明细会显示在分页窗口中。"}
            </p>
          </div>
          <Button
            variant="secondary"
            className="shrink-0"
            disabled={rows.length === 0}
            onClick={() => {
              setTablePage(1);
              setTableOpen(true);
            }}
          >
            查看商品明细
          </Button>
        </div>
      </div>
      <DataTableDialog
        open={tableOpen}
        title="商品明细"
        description="按页查看扫描、校验和执行状态；关闭窗口不会影响当前工作空间。"
        total={rows.length}
        page={tablePage}
        pageSize={pageSize}
        onPageChange={setTablePage}
        onClose={() => setTableOpen(false)}
      >
        <table className="w-full min-w-[1320px] table-fixed border-collapse text-left text-sm">
          <colgroup>
            <col className="w-16" />
            <col className="w-56" />
            <col className="w-44" />
            <col className="w-80" />
            <col className="w-28" />
            <col className="w-52" />
            <col className="w-44" />
            <col className="w-24" />
            <col className="w-28" />
            <col className="w-80" />
          </colgroup>
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              <th className="whitespace-nowrap px-4 py-3 font-medium">行</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">标识</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">淘宝商品ID</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">标题</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">图片夹</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">图片</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">主视频</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">校验</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">执行</th>
              <th className="whitespace-nowrap px-4 py-3 font-medium">原因</th>
            </tr>
          </thead>
          <tbody>
            {tableRows.length === 0 ? (
              <tr>
                <td colSpan={10} className="px-4 py-12 text-center text-slate-400">
                  暂无商品明细
                </td>
              </tr>
            ) : (
              tableRows.map((row) => {
                const passed = row.validation === "通过";
                const packOk = row.pack_found !== false && Boolean(row.pack);
                return (
                  <tr key={`${row.row}-${row.product_id}`} className="border-t border-border">
                    <td className="px-4 py-3 text-slate-500">{row.row}</td>
                    <td className="truncate whitespace-nowrap px-4 py-3 font-medium" title={row.product_id}>{row.product_id}</td>
                    <td className="overflow-hidden px-4 py-2"><ProductItemId value={row.taobao_item_id} /></td>
                    <td className="truncate whitespace-nowrap px-4 py-3" title={row.title}>{row.title}</td>
                    <td className="overflow-hidden whitespace-nowrap px-4 py-3" title={packOk ? "已找到" : "未找到"}>
                      <span className={cn("rounded-full px-2.5 py-1 text-xs", {
                        "bg-emerald-50 text-emerald-700": packOk,
                        "bg-amber-50 text-amber-800": !packOk,
                      })}>{packOk ? "已找到" : "未找到"}</span>
                    </td>
                    <td className="truncate whitespace-nowrap px-4 py-3 text-slate-500" title={`主图${row.main_count} / 规格${row.sku_count} / 详情${row.detail_count}`}>主图{row.main_count} / 规格{row.sku_count} / 详情{row.detail_count}</td>
                    <td className="whitespace-nowrap px-4 py-3">
                      {row.video_name ? (
                        <span
                          className={cn("block truncate", {
                            "text-destructive": row.video_ok === false,
                            "text-slate-500": row.video_ok !== false,
                          })}
                          title={row.video_ok === false ? `${row.video_name}（格式错误，将不上传）` : row.video_name}
                        >
                          {row.video_ok === false ? `${row.video_name}（格式错误）` : row.video_name}
                        </span>
                      ) : null}
                    </td>
                    <td className="overflow-hidden whitespace-nowrap px-4 py-3" title={row.validation}>
                      <span className={cn("rounded-full px-2.5 py-1 text-xs", {
                        "bg-emerald-50 text-emerald-700": passed,
                        "bg-red-50 text-destructive": !passed,
                      })}>{row.validation}</span>
                    </td>
                    <td className="overflow-hidden whitespace-nowrap px-4 py-3" title={row.execution || "未执行"}>
                      <span className={cn("inline-block max-w-full truncate rounded-full px-2.5 py-1 text-xs", {
                        "bg-emerald-50 text-emerald-700": row.execution === "已填写未提交" || row.execution === "结果待核实",
                        "bg-amber-50 text-amber-800": row.execution === "暂停" || row.execution === "已停止",
                        "bg-red-50 text-destructive": row.execution === "失败",
                        "bg-slate-100 text-slate-600": !row.execution || row.execution === "未执行",
                      })}>{row.execution || "未执行"}</span>
                    </td>
                    <td className="truncate whitespace-nowrap px-4 py-3 text-xs text-slate-500" title={row.errors.join("；") || "—"}>{row.errors.join("；") || "—"}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </DataTableDialog>
      <ScanDecisionDialog
        open={scanDecisionOpen}
        count={rows.length}
        busy={busy}
        onClose={onCloseScanDecision}
        onOpenWorkbook={onOpenGeneratedWorkbook}
        onUseDefaults={onUseDefaults}
      />
    </PanelFrame>
  );
}
