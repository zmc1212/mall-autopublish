import {
  ArrowRight,
  ChevronDown,
  Download,
  FileSpreadsheet,
  FolderOpen,
  FolderSearch,
  Loader2,
  RefreshCw,
  Save,
  Upload,
  X,
} from "lucide-react";
import { useRef, useState } from "react";
import type { ReactNode } from "react";

import { Button, InputText } from "../theme";
import type { JobState, WorkspaceDefaults, WorkspaceInfo } from "../types";
import cn from "../utils/classnames";
import { useDialogBehavior } from "../utils/dialogFocus";
import { usePagination } from "../utils/usePagination";
import { useSessionState } from "../utils/useSessionState";
import { handleTabKeys } from "../utils/tabKeyboard";

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
  onContinue?: () => void;
  validatedAt?: string;
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
  onContinue,
  validatedAt = "",
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
  const viewKey = `qianniu.workbook.${job?.workspace_path || job?.workbook_path || "empty"}`;
  const [sourceMode, setSourceMode] = useSessionState<"workspace" | "excel">(`${viewKey}.source`, !hasWorkspace && Boolean(job?.workbook_path) ? "excel" : "workspace");
  const { page: tablePage, setPage: setTablePage, pageRows: tableRows, pageSize } = usePagination(rows, 15, `${viewKey}.page`);
  const normalized = (path: string) => path.trim().replace(/[\\/]+$/, "").replace(/\//g, "\\").toLowerCase();
  const sourceDraftChanged = sourceMode === "workspace"
    ? normalized(workspaceDraft) !== normalized(job?.workspace_path || "")
    : normalized(excelDraft) !== normalized(job?.workbook_path || "");
  const appliedCategories = categories.filter((item) => item.selected).map((item) => item.name);
  const categorySelectionDirty =
    categories.length > 0 &&
    [...selectedCategories].sort().join("\u0000") !== [...appliedCategories].sort().join("\u0000");
  const previewRows = rows.slice(0, 12);
  const hasRows = rows.length > 0;
  const [categoriesExpanded, setCategoriesExpanded] = useState(false);
  const visibleCategories = categoriesExpanded ? categories : categories.slice(0, 6);

  const executionTone = (execution: string) => {
    if (execution === "失败") return "bg-red-50 text-destructive";
    if (execution === "暂停" || execution === "已停止" || execution === "结果待核实" || execution === "已填写未提交") {
      return "bg-amber-50 text-amber-800";
    }
    if (execution === "已入库" || execution === "已完成") return "bg-emerald-50 text-emerald-700";
    return "bg-muted text-slate-600";
  };

  const openTable = () => {
    setTablePage(1);
    setTableOpen(true);
  };

  return (
    <PanelFrame
      title="商品清单"
      hint="先准备商品清单，再进入执行入库。默认只放入仓库，不自动上架。"
    >
      <div className={`workbook-content flex min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-y-auto ${className}`}>
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
          <div className="inline-flex rounded-lg border border-border bg-white p-1" role="tablist" aria-label="商品清单来源" onKeyDown={handleTabKeys}>
            <button
              type="button"
              role="tab"
              aria-selected={sourceMode === "workspace"}
              tabIndex={sourceMode === "workspace" ? 0 : -1}
              className={cn(
                "inline-flex min-h-9 items-center gap-2 rounded-md px-3 text-sm font-medium transition-colors",
                sourceMode === "workspace" ? "bg-primary text-on-primary" : "text-slate-600 hover:bg-muted hover:text-foreground",
              )}
              onClick={() => setSourceMode("workspace")}
            >
              <FolderOpen className="h-4 w-4" aria-hidden="true" />
              目录扫描
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={sourceMode === "excel"}
              tabIndex={sourceMode === "excel" ? 0 : -1}
              className={cn(
                "inline-flex min-h-9 items-center gap-2 rounded-md px-3 text-sm font-medium transition-colors",
                sourceMode === "excel" ? "bg-primary text-on-primary" : "text-slate-600 hover:bg-muted hover:text-foreground",
              )}
              onClick={() => setSourceMode("excel")}
            >
              <FileSpreadsheet className="h-4 w-4" aria-hidden="true" />
              Excel 导入
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-2 rounded-full border border-border bg-white px-3 py-1.5 text-xs text-slate-600">
              <span className={cn("h-2 w-2 rounded-full", hasRows ? "bg-primary" : "bg-slate-300")} aria-hidden="true" />
              {hasRows ? `${rows.length} 款已载入 · ${job?.valid || 0} 款通过校验` : "等待商品清单"}
            </span>
            {onContinue ? (
              <>
                <Button
                  variant="primary"
                  onClick={onContinue}
                  disabled={!job?.valid || busy || categorySelectionDirty || sourceDraftChanged}
                  title={categorySelectionDirty ? "分类选择尚未应用，请先点击“应用并扫描”" : undefined}
                >
                  前往执行
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </Button>
                {categorySelectionDirty ? (
                  <span className="text-xs text-amber-700" role="status">请先应用并扫描分类</span>
                ) : null}
              </>
            ) : null}
          </div>
        </div>

        {sourceMode === "workspace" ? (
          <section className="workbook-prep" aria-label="准备商品清单">
            <div className="workbook-pathbar">
              <label className="workbook-path-label" htmlFor="workspace-path" title={job?.restored ? "已恢复上次工作空间" : undefined}>
                <span>商品工作空间</span>
                {hasWorkspace ? <span className="workbook-connected"><span aria-hidden="true" />已连接</span> : null}
              </label>
              <InputText id="workspace-path" value={workspaceDraft} onChange={event => onWorkspaceDraft(event.target.value)} placeholder="选择包含各款图片夹的目录" title={workspaceDraft} />
              <Button variant="secondary" onClick={onPickWorkspace} disabled={busy}>
                {spinIcon("workbook.pickWorkspace", <FolderOpen className="h-4 w-4" aria-hidden="true" />)}选择目录
              </Button>
              <Button variant="primary" onClick={onRescan} disabled={busy || !workspaceDraft.trim()}>
                {spinIcon("workbook.rescan", <RefreshCw className="h-4 w-4" aria-hidden="true" />)}{sourceDraftChanged ? "应用并扫描" : "扫描更新"}
              </Button>
              <Button variant="ghost" className="px-3" onClick={onOpenFolder} disabled={!hasWorkspace && !workspaceDraft.trim()} aria-label="打开文件夹" title="打开文件夹">
                <FolderSearch className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
            {!hasWorkspace ? <p className="mt-2 text-xs leading-5 text-slate-500">把每款商品的主图、详情、规格图放进一级子文件夹，扫描后生成商品清单。</p> : null}
            {scanErrors.length > 0 ? <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
              扫描问题：{scanErrors.map(item => `${item.folder}（${item.error}）`).join("；")}
            </p> : null}
            <section className="workbook-categories" aria-labelledby="workbook-category-title">
              <div className="workbook-category-heading">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <h3 id="workbook-category-title" className="text-sm font-semibold text-foreground">扫描类别</h3>
                  {categories.length > 0 ? <>
                    <span className="workbook-source-note">已选 {categories.filter(category => selectedCategories.includes(category.name)).length} / {categories.length} 类</span>
                    <span className={categorySelectionDirty ? "text-xs text-amber-800" : "text-xs text-primary"}>{categorySelectionDirty ? "未应用" : "已应用"}</span>
                  </> : null}
                </div>
                {categories.length > 0 ? <div className="workbook-category-actions">
                  <Button variant="ghost" className="min-h-8 px-2 text-xs" onClick={() => onSelectedCategoriesChange(categories.map(item => item.name))} disabled={busy || selectedCategories.length === categories.length}>全选</Button>
                  <Button variant="ghost" className="min-h-8 px-2 text-xs" onClick={() => onSelectedCategoriesChange([])} disabled={busy || selectedCategories.length === 0}>全不选</Button>
                  {categorySelectionDirty ? <Button variant="secondary" className="min-h-8 px-3 text-xs" onClick={onRescan} disabled={busy || !hasWorkspace}>
                    {spinIcon("workbook.rescan", <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />)}应用并扫描
                  </Button> : null}
                </div> : null}
              </div>
              {categories.length > 0 ? <>
                <div className="workbook-category-list" role="group" aria-label="扫描类别选项">
                  {visibleCategories.map(category => {
                    const checked = selectedCategories.includes(category.name);
                    return <label key={category.name} className="workbook-category-option" data-selected={checked} data-disabled={busy}>
                      <input type="checkbox" className="h-4 w-4 shrink-0 accent-primary" checked={checked} disabled={busy}
                        onChange={event => onSelectedCategoriesChange(event.target.checked ? [...selectedCategories, category.name] : selectedCategories.filter(item => item !== category.name))} />
                      <span className="workbook-category-content">
                        <span className="workbook-category-name">{category.name}</span>
                        {!category.template_found ? <span className="workbook-category-notice">{category.notice || "未配置同名商品属性模板"}</span> : null}
                        {category.error_count > 0 ? <span className="workbook-category-notice">{category.error_count} 个问题</span> : null}
                      </span>
                      <span className="workbook-category-count">{category.product_count} 款</span>
                    </label>;
                  })}
                  {categories.length > 6 ? <button type="button" className="workbook-category-expand" aria-expanded={categoriesExpanded} onClick={() => setCategoriesExpanded(value => !value)}>
                    {categoriesExpanded ? "收起类别" : `展开其余 ${categories.length - 6} 类`}
                    <ChevronDown className={cn("h-3.5 w-3.5", categoriesExpanded && "rotate-180")} aria-hidden="true" />
                  </button> : null}
                </div>
                {categorySelectionDirty ? <p className="mt-2 text-xs text-amber-800" role="status">类别选择尚未应用，点击“应用并扫描”更新商品清单。</p> : null}
              </> : <p className="workbook-source-note mt-2">扫描工作空间后，这里会显示可筛选的商品类别。</p>}
            </section>
          </section>
        ) : (
          <section className="shrink-0 rounded-xl border border-border bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="text-base font-semibold text-foreground">使用已有商品清单</h3>
                <p className="mt-1 text-xs leading-5 text-slate-500">选择文件会立即导入并校验；修改表格后，保存并重新读取即可。</p>
              </div>
              <Button variant="ghost" onClick={onTemplate} disabled={busy}>
                {spinIcon("workbook.template", <Download className="h-4 w-4" aria-hidden="true" />)}
                下载空白模板
              </Button>
            </div>
            <div className="mt-3 grid gap-2 lg:grid-cols-[minmax(0,1fr)_auto]">
              <InputText
                value={excelDraft}
                onChange={(event) => onExcelDraft(event.target.value)}
                placeholder="选择或粘贴商品清单.xlsx"
                aria-label="Excel 清单路径"
                title={excelDraft}
              />
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" onClick={onPickExcel} disabled={busy}>
                  {spinIcon("workbook.pickExcel", <FolderOpen className="h-4 w-4" aria-hidden="true" />)}
                  选择并导入
                </Button>
                <Button variant="primary" onClick={onImportExcel} disabled={busy || !excelDraft.trim()}>
                  {spinIcon("workbook.import", <Upload className="h-4 w-4" aria-hidden="true" />)}
                  应用路径并导入
                </Button>
              </div>
            </div>
          </section>
        )}

        <div className="workbook-validation" role="status">
          <div className="min-w-0">
            <p className="truncate text-sm" title={job?.workbook_path}>当前清单：{job?.workbook_path || "尚未载入"}</p>
            <p className="mt-1 text-xs text-slate-600">{sourceDraftChanged ? "输入的来源尚未应用，请先扫描或导入。" : categorySelectionDirty ? "类别选择尚未应用，请先应用并扫描。" : validatedAt ? `最近读取并校验：${validatedAt}` : "在外部修改表格后，请先保存，再重新读取并校验。"}</p>
          </div>
          <Button variant="secondary" onClick={onValidate} disabled={busy || !job?.workbook_path || sourceDraftChanged || categorySelectionDirty}>
            {spinIcon("workbook.validate", <RefreshCw className="h-4 w-4" aria-hidden="true" />)}重新读取并校验
          </Button>
        </div>
        <details className="workbook-defaults group shrink-0">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-2 py-2.5 [&::-webkit-details-marker]:hidden">
            <span className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
              <span className="text-sm font-medium text-foreground">批次默认设置</span>
              <span className="text-xs text-slate-500">仅用于新商品，已有修改会保留</span>
            </span>
            <ChevronDown className="h-4 w-4 shrink-0 text-slate-400 transition-transform group-open:rotate-180" aria-hidden="true" />
          </summary>
          <div className="border-t border-border px-4 pb-4 pt-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-slate-500">默认值仅影响新扫描或新导入的商品。</p>
              <Button variant="secondary" className="min-h-9 px-3" onClick={onSaveDefaults} disabled={busy || !hasWorkspace}>
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
          </div>
        </details>

        <section className="workbook-products flex min-h-[320px] shrink-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-white">
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
            <div>
              <h3 className="flex items-center gap-2 text-base font-semibold text-foreground">商品明细 <span className="rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-slate-600">{rows.length}</span></h3>
              <p className="mt-1 text-xs text-slate-500">
                {hasRows
                  ? `校验通过 ${job?.valid || 0} 条 · 待处理 ${job?.pending || 0} 条${job?.failed ? ` · 校验失败 ${job.failed} 条` : ""}`
                  : "选择目录扫描或导入 Excel 后，商品明细会直接显示在这里。"}
              </p>
            </div>
            <Button variant="secondary" className="shrink-0" disabled={!hasRows} onClick={openTable}>
              查看全部字段
            </Button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            {previewRows.length === 0 ? (
              <div className="flex min-h-40 items-center justify-center px-4 py-10 text-center text-sm text-slate-500">
                尚未生成商品明细。准备好目录或 Excel 后，扫描/导入即可继续。
              </div>
            ) : (
              <table className="w-full min-w-[760px] table-fixed border-collapse text-left text-sm">
                <colgroup>
                  <col className="w-[38%]" />
                  <col className="w-[15%]" />
                  <col className="w-[21%]" />
                  <col className="w-[11%]" />
                  <col className="w-[15%]" />
                </colgroup>
                <thead className="sticky top-0 z-10 border-b border-border bg-muted text-xs text-slate-500">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">商品 / 商品编号</th>
                    <th className="px-4 py-2.5 font-medium">类别</th>
                    <th className="px-4 py-2.5 font-medium">素材</th>
                    <th className="px-4 py-2.5 font-medium">校验</th>
                    <th className="px-4 py-2.5 font-medium">执行状态</th>
                  </tr>
                </thead>
                <tbody>
                  {previewRows.map((row) => {
                    const passed = row.validation === "通过";
                    const execution = row.execution || "未执行";
                    return (
                      <tr key={`${row.row}-${row.product_id}`} className="border-b border-border last:border-b-0 hover:bg-muted/50">
                        <td className="max-w-0 px-4 py-3">
                          <div className="workbook-product-title font-medium text-foreground" title={row.title}>{row.title || "未填写标题"}</div>
                          <div className="mt-0.5 truncate text-xs text-slate-500" title={row.product_id}>{row.product_id}</div>
                        </td>
                        <td className="truncate px-4 py-3 text-slate-600" title={row.category}>{row.category || "—"}</td>
                        <td className="truncate px-4 py-3 text-slate-600" title={`主图${row.main_count} / 规格${row.sku_count} / 详情${row.detail_count}`}>
                          主图 {row.main_count} · 规格 {row.sku_count} · 详情 {row.detail_count}
                        </td>
                        <td className="px-4 py-3">
                          <span className={cn("inline-flex rounded-full px-2 py-1 text-xs", passed ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-destructive")}>
                            {row.validation || "待校验"}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className={cn("inline-flex max-w-full truncate rounded-full px-2 py-1 text-xs", executionTone(execution))} title={execution}>
                            {execution}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
          {hasRows ? (
            <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-2.5 text-xs text-slate-500">
              <span>{rows.length > previewRows.length ? `已显示前 ${previewRows.length} 条` : `共 ${rows.length} 条`}</span>
              <span>明细表支持分页查看全部字段</span>
            </div>
          ) : null}
        </section>
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
                        "bg-amber-50 text-amber-800": row.execution === "已填写未提交" || row.execution === "结果待核实" || row.execution === "暂停" || row.execution === "已停止",
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
