import { Download, FolderOpen, FolderSearch, RefreshCw, Save, Upload } from "lucide-react";

import { Button, InputText } from "../theme";
import type { JobState, WorkspaceDefaults, WorkspaceInfo } from "../types";
import cn from "../utils/classnames";

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
  busy: boolean;
  onPickWorkspace: () => void;
  onRescan: () => void;
  onOpenFolder: () => void;
  onSaveDefaults: () => void;
  onPickExcel: () => void;
  onImportExcel: () => void;
  onValidate: () => void;
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

export default function WorkbookPanel({
  job,
  workspace,
  workspaceDraft,
  onWorkspaceDraft,
  excelDraft,
  onExcelDraft,
  defaults,
  onDefaultsChange,
  busy,
  onPickWorkspace,
  onRescan,
  onOpenFolder,
  onSaveDefaults,
  onPickExcel,
  onImportExcel,
  onValidate,
  onTemplate,
  className = "",
}: WorkbookPanelProps) {
  const rows = job?.rows || [];
  const registry = workspace?.registry || { attributes: [], logistics: [], sales: [] };
  const scanErrors = workspace?.scan?.errors || [];
  const hasWorkspace = Boolean(job?.workspace_path || workspace?.path);
  return (
    <PanelFrame
      title="工作空间"
      hint="一款商品一个文件夹，程序生成一张总表。改标题和价格只改这一张表。关闭软件后会恢复上次工作空间。"
    >
      <div className={`grid h-full min-h-0 min-w-0 flex-1 grid-rows-[minmax(0,min(40dvh,48%))_minmax(0,1fr)] gap-3 overflow-hidden ${className}`}>
        <div className="min-h-0 overflow-y-auto space-y-3">
          <div className="rounded-2xl border border-border bg-white p-4">
          <label className="text-sm font-medium" htmlFor="workspace-path">
            工作空间目录
          </label>
          <div className="mt-2 flex flex-col gap-2 lg:flex-row">
            <InputText
              id="workspace-path"
              value={workspaceDraft}
              onChange={(event) => onWorkspaceDraft(event.target.value)}
              placeholder="选择包含各款图片夹的目录"
            />
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" onClick={onPickWorkspace} disabled={busy}>
                <FolderOpen className="h-4 w-4" aria-hidden="true" />
                选择工作空间
              </Button>
              <Button variant="secondary" onClick={onRescan} disabled={busy || !hasWorkspace}>
                <RefreshCw className="h-4 w-4" aria-hidden="true" />
                扫描更新
              </Button>
              <Button variant="ghost" onClick={onOpenFolder} disabled={!hasWorkspace && !workspaceDraft.trim()}>
                <FolderSearch className="h-4 w-4" aria-hidden="true" />
                打开资源管理器
              </Button>
            </div>
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
        <div className="rounded-2xl border border-border bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-medium">批次默认</h3>
            <Button variant="secondary" onClick={onSaveDefaults} disabled={busy || !hasWorkspace}>
              <Save className="h-4 w-4" aria-hidden="true" />
              保存默认
            </Button>
          </div>
          <p className="mt-1 text-xs text-slate-500">新扫进来的夹会用这些值；已改过的标题、价格、模板不会被覆盖。</p>
          <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
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
          <details className="rounded-2xl border border-border bg-white p-4">
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
                  <FolderOpen className="h-4 w-4" aria-hidden="true" />
                  选择文件
                </Button>
                <Button variant="secondary" onClick={onImportExcel} disabled={busy || !excelDraft.trim()}>
                  <Upload className="h-4 w-4" aria-hidden="true" />
                  导入
                </Button>
                <Button variant="secondary" onClick={onValidate} disabled={busy || !job?.workbook_path}>
                  <RefreshCw className="h-4 w-4" aria-hidden="true" />
                  校验
                </Button>
                <Button variant="ghost" onClick={onTemplate} disabled={busy}>
                  <Download className="h-4 w-4" aria-hidden="true" />
                  下载空白模板
                </Button>
              </div>
            </div>
          </details>
        </div>
        <div className="min-h-0 overflow-auto rounded-2xl border border-border bg-white">
          <table className="w-full min-w-[1080px] border-collapse text-left text-sm">
            <thead className="sticky top-0 z-10 bg-slate-50 text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">行</th>
                <th className="px-4 py-3 font-medium">标识</th>
                <th className="px-4 py-3 font-medium">淘宝商品ID</th>
                <th className="px-4 py-3 font-medium">标题</th>
                <th className="px-4 py-3 font-medium">图片夹</th>
                <th className="px-4 py-3 font-medium">图片</th>
                <th className="px-4 py-3 font-medium">校验</th>
                <th className="px-4 py-3 font-medium">执行</th>
                <th className="px-4 py-3 font-medium">原因</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-4 py-12 text-center text-slate-400">
                    选择工作空间后，一级子文件夹会出现在这里
                  </td>
                </tr>
              ) : (
                rows.map((row) => {
                  const passed = row.validation === "通过";
                  const packOk = row.pack_found !== false && Boolean(row.pack);
                  return (
                    <tr key={`${row.row}-${row.product_id}`} className="border-t border-border">
                      <td className="px-4 py-3 text-slate-500">{row.row}</td>
                      <td className="px-4 py-3 font-medium">{row.product_id}</td>
                      <td className="px-4 py-2">
                        <ProductItemId value={row.taobao_item_id} />
                      </td>
                      <td className="max-w-xs truncate px-4 py-3">{row.title}</td>
                      <td className="px-4 py-3">
                        <span
                          className={cn("rounded-full px-2.5 py-1 text-xs", {
                            "bg-emerald-50 text-emerald-700": packOk,
                            "bg-amber-50 text-amber-800": !packOk,
                          })}
                        >
                          {packOk ? "已找到" : "未找到"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-500">
                        主图{row.main_count} / 规格{row.sku_count} / 详情{row.detail_count}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={cn("rounded-full px-2.5 py-1 text-xs", {
                            "bg-emerald-50 text-emerald-700": passed,
                            "bg-red-50 text-destructive": !passed,
                          })}
                        >
                          {row.validation}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={cn("inline-block max-w-full truncate rounded-full px-2.5 py-1 text-xs", {
                            "bg-emerald-50 text-emerald-700":
                              row.execution === "已填写未提交" || row.execution === "结果待核实",
                            "bg-amber-50 text-amber-800": row.execution === "暂停" || row.execution === "已停止",
                            "bg-red-50 text-destructive": row.execution === "失败",
                            "bg-slate-100 text-slate-600": !row.execution || row.execution === "未执行",
                          })}
                        >
                          {row.execution || "未执行"}
                        </span>
                      </td>
                      <td className="max-w-sm px-4 py-3 text-xs leading-5 text-slate-500">
                        {row.errors.join("；") || "—"}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </PanelFrame>
  );
}
