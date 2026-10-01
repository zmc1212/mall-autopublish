import { Download, FolderOpen, Loader2, Save, ScrollText } from "lucide-react";
import { useEffect, useState } from "react";

import { Button, InputText } from "../theme";
import type { AppSettings, ChromeStatus, JobState } from "../types";
import cn from "../utils/classnames";

import { PanelFrame } from "./Sidebar";

interface SettingsPanelProps {
  settings: AppSettings | null;
  chrome: ChromeStatus | null;
  job: JobState | null;
  draft: AppSettings;
  busy: boolean;
  pending: ReadonlySet<string>;
  onChange: (next: AppSettings) => void;
  onToggleDebugBrowser: (checked: boolean) => void;
  onPickChrome: () => void;
  onPickResults: () => void;
  onPickProfile: () => void;
  onExportLogs: () => void;
  onSave: () => void;
  className?: string;
}

export default function SettingsPanel({
  settings,
  chrome,
  job,
  draft,
  busy,
  pending,
  onChange,
  onToggleDebugBrowser,
  onPickChrome,
  onPickResults,
  onPickProfile,
  onExportLogs,
  onSave,
  className = "",
}: SettingsPanelProps) {
  const [logLevel, setLogLevel] = useState<"all" | "warn" | "error">("all");
  const [logQuery, setLogQuery] = useState("");
  const allLogs = job?.logs || [];
  const query = logQuery.trim().toLowerCase();
  const filteredLogs = allLogs
    .filter((entry) => (logLevel === "all" ? true : entry.level === logLevel))
    .filter((entry) => !query || (entry.message || "").toLowerCase().includes(query))
    .slice(-100);
  // 数字输入允许暂存非法文本并显式报错，不再静默回退默认值
  const [portText, setPortText] = useState(String(draft.cdp_port));
  const [limitText, setLimitText] = useState(String(draft.limit));
  const [specBatchText, setSpecBatchText] = useState(String(draft.spec_upload_batch_size));
  const [retryLimitText, setRetryLimitText] = useState(String(draft.item_retry_limit));
  useEffect(() => setPortText(String(draft.cdp_port)), [draft.cdp_port]);
  useEffect(() => setLimitText(String(draft.limit)), [draft.limit]);
  useEffect(() => setSpecBatchText(String(draft.spec_upload_batch_size)), [draft.spec_upload_batch_size]);
  useEffect(() => setRetryLimitText(String(draft.item_retry_limit)), [draft.item_retry_limit]);
  const portValid = /^\d+$/.test(portText) && Number(portText) >= 1 && Number(portText) <= 65535;
  const limitValid = limitText === "" || /^\d+$/.test(limitText);
  const specBatchValid = specBatchText === "" || (/^\d+$/.test(specBatchText) && Number(specBatchText) <= 99);
  const retryLimitValid = retryLimitText === "" || (/^\d+$/.test(retryLimitText) && Number(retryLimitText) <= 5);

  const toggleSkuImageTarget = (target: "slim_material" | "publish_page") => {
    const selected = new Set(
      draft.sku_image_strategy === "both"
        ? ["slim_material", "publish_page"]
        : [draft.sku_image_strategy],
    );
    if (selected.has(target)) {
      if (selected.size === 1) return;
      selected.delete(target);
    } else {
      selected.add(target);
    }
    onChange({
      ...draft,
      sku_image_strategy: selected.size === 2 ? "both" : ([...selected][0] || target),
    });
  };
  return (
    <PanelFrame title="设置与排障" hint="需要观察自动填写过程或排查异常时，可显示浏览器并查看最近日志。">
      <div className={`max-w-4xl min-h-0 flex-1 space-y-4 overflow-auto ${className}`}>
        <article className="rounded-2xl border border-border bg-white p-5">
          <div>
            <div>
              <h3 className="text-sm font-semibold">排障工具</h3>
              <p className="mt-1 text-xs leading-5 text-slate-500">
                默认隐藏自动化浏览器窗口和任务栏图标。需要查看页面或手动处理异常时，勾选后立即生效并保持显示。
              </p>
            </div>
            <label className="mt-4 flex items-start gap-3 rounded-lg border border-border bg-slate-50 p-3 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-primary"
                checked={draft.debug_browser}
                disabled={busy || !chrome?.chrome_found}
                onChange={(event) => onToggleDebugBrowser(event.target.checked)}
              />
              <span>
                <span className="block font-medium text-slate-800">显示自动化浏览器</span>
                <span className="mt-1 block text-xs text-slate-500">
                  勾选后浏览器窗口立即显示，执行任务时保持显示；取消勾选后窗口立即隐藏，任务栏也不会显示浏览器图标。
                </span>
              </span>
            </label>
          </div>
        </article>

        <article className="overflow-hidden rounded-2xl border border-border bg-slate-950 text-slate-100">
          <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              <ScrollText className="h-4 w-4" aria-hidden="true" />
              最近运行日志
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400">
                {logLevel === "all" && !query ? `${allLogs.length} 条` : `匹配 ${filteredLogs.length} / ${allLogs.length} 条`}
              </span>
              <button
                type="button"
                onClick={onExportLogs}
                disabled={pending.has("settings.exportLogs")}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs transition-colors",
                  "text-slate-300 hover:bg-white/10 hover:text-white",
                  pending.has("settings.exportLogs") && "opacity-60",
                )}
              >
                {pending.has("settings.exportLogs") ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                ) : (
                  <Download className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                导出日志
              </button>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 border-b border-white/10 px-4 py-2">
            <div className="flex gap-1" role="group" aria-label="日志级别过滤">
              {([["all", "全部"], ["warn", "注意"], ["error", "异常"]] as const).map(([level, label]) => (
                <button
                  key={level}
                  type="button"
                  onClick={() => setLogLevel(level)}
                  aria-pressed={logLevel === level}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-xs transition-colors",
                    logLevel === level ? "bg-white/15 text-white" : "text-slate-400 hover:bg-white/5 hover:text-white",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
            <input
              type="search"
              className="min-h-8 w-48 rounded-md border border-white/15 bg-white/5 px-2 py-1 text-xs text-slate-100 outline-none transition-colors placeholder:text-slate-500 focus:border-primary"
              placeholder="搜索日志关键词"
              aria-label="搜索日志关键词"
              value={logQuery}
              onChange={(event) => setLogQuery(event.target.value)}
            />
          </div>
          <div className="max-h-72 min-h-36 overflow-auto p-4 font-mono text-xs leading-6">
            {allLogs.length === 0 ? (
              <p className="font-sans text-slate-500">暂无运行日志。扫描清单或开始执行后，关键步骤会显示在这里。</p>
            ) : filteredLogs.length === 0 ? (
              <p className="font-sans text-slate-500">没有匹配的日志，可调整级别或关键词。</p>
            ) : (
              filteredLogs.map((entry, index) => (
                <p
                  key={`${entry.time}-${index}`}
                  className={cn("break-words", {
                    "text-red-300": entry.level === "error",
                    "text-amber-200": entry.level === "warn",
                    "text-slate-200": entry.level === "info",
                  })}
                >
                  <span className="text-slate-500">{entry.time}</span> {entry.message}
                </p>
              ))
            )}
          </div>
        </article>

        <article className="rounded-2xl border border-border bg-white p-5">
          <h3 className="mb-4 text-sm font-semibold">高级设置</h3>
          <label className="text-sm font-medium" htmlFor="chrome-path">
            自定义浏览器路径（可选）
          </label>
          <div className="mt-2 flex gap-2">
            <InputText
              id="chrome-path"
              value={draft.chrome_path}
              placeholder="留空使用内置 Chromium"
              onChange={(event) => onChange({ ...draft, chrome_path: event.target.value })}
            />
            <Button variant="secondary" onClick={onPickChrome} disabled={busy}>
              {pending.has("settings.pickChrome") ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <FolderOpen className="h-4 w-4" aria-hidden="true" />}
              浏览
            </Button>
          </div>
          <p className="mt-2 text-xs text-slate-500">
            当前留空时自动使用内置浏览器；旧路径失效时也会自动回退，不影响启动。
          </p>
          <label className="mt-4 block text-sm font-medium" htmlFor="profile-path">
            登录目录（user-data-dir）
          </label>
          <div className="mt-2 flex gap-2">
            <InputText
              id="profile-path"
              value={draft.chrome_profile}
              onChange={(event) => onChange({ ...draft, chrome_profile: event.target.value })}
            />
            <Button variant="secondary" onClick={onPickProfile} disabled={busy}>
              {pending.has("settings.pickProfile") ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
              浏览
            </Button>
          </div>
          <label className="mt-4 block text-sm font-medium" htmlFor="results-dir">
            结果保存目录
          </label>
          <div className="mt-2 flex gap-2">
            <InputText
              id="results-dir"
              value={draft.results_dir}
              onChange={(event) => onChange({ ...draft, results_dir: event.target.value })}
            />
            <Button variant="secondary" onClick={onPickResults} disabled={busy}>
              {pending.has("settings.pickResults") ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
              浏览
            </Button>
          </div>
          <label className="mt-4 block text-sm font-medium" htmlFor="cdp-port">
            调试端口
          </label>
          <InputText
            id="cdp-port"
            className="mt-2 w-32"
            inputMode="numeric"
            aria-invalid={!portValid}
            value={portText}
            onChange={(event) => {
              const text = event.target.value;
              setPortText(text);
              if (/^\d+$/.test(text) && Number(text) >= 1 && Number(text) <= 65535) {
                onChange({ ...draft, cdp_port: Number(text) });
              }
            }}
          />
          {!portValid && (
            <p className="mt-1 text-xs text-red-600" role="alert">
              请输入 1-65535 之间的端口号。
            </p>
          )}
          <label className="mt-5 flex items-start gap-3 rounded-lg border border-border bg-slate-50 p-3 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 accent-primary"
              checked={draft.sku_template_import}
              onChange={(event) => onChange({ ...draft, sku_template_import: event.target.checked })}
            />
            <span>
              <span className="block font-medium text-slate-800">使用千牛模板批量导入 SKU</span>
              <span className="mt-1 block text-xs text-slate-500">
                默认关闭。开启后为支持的中性笔类目自动生成并导入 SKU 模板；导入入口不可用时会暂停任务。
              </span>
            </span>
          </label>
          <fieldset className="mt-5 rounded-lg border border-border bg-slate-50 p-3 text-sm">
            <legend className="px-1 font-medium text-slate-800">SKU 图片处理方式（可多选）</legend>
            <label className="mt-3 flex items-start gap-3">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-primary"
                checked={["slim_material", "both"].includes(draft.sku_image_strategy)}
                onChange={() => toggleSkuImageTarget("slim_material")}
              />
              <span>
                <span className="block font-medium text-slate-800">官方素材批量导入搜索主图（默认）</span>
                <span className="mt-1 block text-xs text-slate-500">
                  入库后通过官方素材批量导入上传并核验 SKU 搜索主图；遇到验证或结果不明确时保留断点。
                </span>
              </span>
            </label>
            <label className="mt-3 flex items-start gap-3">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-primary"
                checked={["publish_page", "both"].includes(draft.sku_image_strategy)}
                onChange={() => toggleSkuImageTarget("publish_page")}
              />
              <span>
                <span className="block font-medium text-slate-800">商品规格图（原方式）</span>
                <span className="mt-1 block text-xs text-slate-500">
                  图片绑定到「商品规格」名称旁的图片位；已有商品只补规格图，不重复建品。
                </span>
              </span>
            </label>
            {["publish_page", "both"].includes(draft.sku_image_strategy) && (
              <div className="mt-3 rounded-lg border border-border bg-white p-3">
                <label className="block text-sm font-medium" htmlFor="spec-upload-batch-size">
                  每批上传规格图数量（0 表示全部一次上传）
                </label>
                <p className="mt-1 text-xs text-slate-500">
                  入库成功后进入商品编辑页，每批最多上传 N 行规格图并保存一次商品，然后退出编辑页再重开传下一批，降低一次性上传触发滑块验证的概率。
                </p>
                <InputText
                  id="spec-upload-batch-size"
                  className="mt-2 w-32"
                  inputMode="numeric"
                  aria-invalid={!specBatchValid}
                  value={specBatchText}
                  onChange={(event) => {
                    const text = event.target.value;
                    setSpecBatchText(text);
                    if (/^\d*$/.test(text)) {
                      onChange({ ...draft, spec_upload_batch_size: text === "" ? 0 : Number(text) });
                    }
                  }}
                />
                {!specBatchValid && (
                  <p className="mt-1 text-xs text-red-600" role="alert">
                    请输入 0-99 的整数，0 表示全部一次上传。
                  </p>
                )}
              </div>
            )}
            <p className="mt-3 text-xs text-slate-500">同时选择时，先核验商品规格图，再处理搜索主图；至少保留一项。</p>
          </fieldset>
          <label className="mt-4 block text-sm font-medium" htmlFor="default-limit">
            每次默认条数（0 表示全部）
          </label>
          <InputText
            id="default-limit"
            className="mt-2 w-32"
            inputMode="numeric"
            aria-invalid={!limitValid}
            value={limitText}
            onChange={(event) => {
              const text = event.target.value;
              setLimitText(text);
              if (text === "" || /^\d+$/.test(text)) {
                onChange({ ...draft, limit: text === "" ? 0 : Number(text) });
              }
            }}
          />
          {!limitValid && (
            <p className="mt-1 text-xs text-red-600" role="alert">
              请输入非负整数，留空或 0 表示全部。
            </p>
          )}
          <label className="mt-6 block text-sm font-medium" htmlFor="item-retry-limit">
            失败自动重试次数（0-5，0 表示不重试）
          </label>
          <p className="mt-1 text-xs text-slate-500">
            某条数据入库失败时自动重试 N 次，仍失败则跳过该条继续下一条，全程不暂停；跑完后统一列出需人工处理的条目。登录失效、滑块验证等需人工处理的情况以及提交结果不明确的条目不重试，直接跳过。
          </p>
          <InputText
            id="item-retry-limit"
            className="mt-2 w-32"
            inputMode="numeric"
            aria-invalid={!retryLimitValid}
            value={retryLimitText}
            onChange={(event) => {
              const text = event.target.value;
              setRetryLimitText(text);
              if (text === "" || /^\d+$/.test(text)) {
                onChange({ ...draft, item_retry_limit: text === "" ? 0 : Number(text) });
              }
            }}
          />
          {!retryLimitValid && (
            <p className="mt-1 text-xs text-red-600" role="alert">
              请输入 0-5 的整数，0 表示失败后直接跳下一条。
            </p>
          )}
          <div className="mt-6">
            <Button onClick={onSave} disabled={busy || !portValid || !limitValid || !specBatchValid || !retryLimitValid}>
              {pending.has("settings.save") ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Save className="h-4 w-4" aria-hidden="true" />}
              保存设置
            </Button>
            {settings ? (
              <p className="mt-3 text-xs text-slate-400">保存后立即用于下一次打开千牛窗口和入库任务。</p>
            ) : null}
          </div>
        </article>
      </div>
    </PanelFrame>
  );
}
