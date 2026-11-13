import {
  Bug,
  Check,
  Download,
  FileImage,
  FolderOpen,
  KeyRound,
  Loader2,
  Save,
  ScrollText,
  SlidersHorizontal,
} from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api";
import { Button, InputText } from "../theme";
import type { AppSettings, ChromeStatus, JobState, LicenseState, UpdateState } from "../types";
import cn from "../utils/classnames";
import { handleTabKeys } from "../utils/tabKeyboard";
import { useSessionState } from "../utils/useSessionState";

import { PanelFrame } from "./Sidebar";
import UpdatePanel from "./UpdatePanel";

type SettingsSection = "common" | "images" | "debug" | "update";

const EDITABLE_SETTING_KEYS = [
  "chrome_path",
  "chrome_profile",
  "cdp_port",
  "debug_browser",
  "sku_template_import",
  "sku_image_strategy",
  "limit",
  "concurrency",
  "spec_upload_batch_size",
  "item_retry_limit",
  "results_dir",
] as const;

interface SettingsPanelProps {
  settings: AppSettings | null;
  update: UpdateState | null;
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
  initialSection?: SettingsSection;
  initialLogQuery?: string;
  onSectionChange?: (section: SettingsSection) => void;
  className?: string;
}

const SETTINGS_SECTIONS = [
  { id: "common", label: "常用设置", description: "批次参数与结果目录", icon: SlidersHorizontal },
  { id: "images", label: "图片处理", description: "SKU 模板与图片策略", icon: FileImage },
  { id: "debug", label: "排障日志", description: "调试窗口与运行记录", icon: Bug },
  { id: "update", label: "更新与授权", description: "更新来源与本机许可", icon: KeyRound },
] as const;

export default function SettingsPanel({
  settings,
  update,
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
  initialSection,
  initialLogQuery,
  onSectionChange,
  className = "",
}: SettingsPanelProps) {
  const [activeSection, setActiveSection] = useState<SettingsSection>(initialSection ?? "common");
  const [logLevel, setLogLevel] = useState<"all" | "warn" | "error">("all");
  const [logQuery, setLogQuery] = useSessionState("qianniu.settings.logQuery", "");
  const [license, setLicense] = useState<LicenseState | null>(null);
  const [deactivating, setDeactivating] = useState(false);

  useEffect(() => {
    if (initialSection) setActiveSection(initialSection);
  }, [initialSection]);
  useEffect(() => {
    if (initialLogQuery !== undefined) setLogQuery(initialLogQuery);
  }, [initialLogQuery]);

  useEffect(() => {
    void api.licenseStatus().then(setLicense).catch(() => {});
  }, []);

  const onDeactivate = async () => {
    if (!window.confirm("取消本机激活后，需要重新输入激活码才能使用。确定继续吗？")) return;
    setDeactivating(true);
    try {
      setLicense(await api.deactivateLicense());
    } catch {
      // 失败时保留当前显示，用户可重试
    } finally {
      setDeactivating(false);
    }
  };

  const allLogs = job?.logs || [];
  const query = logQuery.trim().toLowerCase();
  const filteredLogs = allLogs
    .filter((entry) => (logLevel === "all" ? true : entry.level === logLevel))
    .filter((entry) => !query || [entry.message, entry.product_id, entry.worker_id, entry.row].join(" ").toLowerCase().includes(query))
    .slice(-100);

  // 数字输入允许暂存非法文本并显式报错，不再静默回退默认值
  const [portText, setPortText] = useState(String(draft.cdp_port));
  const [limitText, setLimitText] = useState(String(draft.limit));
  const [concurrencyText, setConcurrencyText] = useState(String(draft.concurrency));
  const [specBatchText, setSpecBatchText] = useState(String(draft.spec_upload_batch_size));
  const [retryLimitText, setRetryLimitText] = useState(String(draft.item_retry_limit));
  useEffect(() => setPortText(String(draft.cdp_port)), [draft.cdp_port]);
  useEffect(() => setLimitText(String(draft.limit)), [draft.limit]);
  useEffect(() => setConcurrencyText(String(draft.concurrency)), [draft.concurrency]);
  useEffect(() => setSpecBatchText(String(draft.spec_upload_batch_size)), [draft.spec_upload_batch_size]);
  useEffect(() => setRetryLimitText(String(draft.item_retry_limit)), [draft.item_retry_limit]);

  const portValid = /^\d+$/.test(portText) && Number(portText) >= 1 && Number(portText) <= 65535;
  const limitValid = limitText === "" || /^\d+$/.test(limitText);
  const concurrencyValid = /^\d+$/.test(concurrencyText) && Number(concurrencyText) >= 1 && Number(concurrencyText) <= 8;
  const specBatchValid = specBatchText === "" || (/^\d+$/.test(specBatchText) && Number(specBatchText) <= 99);
  const retryLimitValid = retryLimitText === "" || (/^\d+$/.test(retryLimitText) && Number(retryLimitText) <= 5);
  const validationErrors = [portValid, limitValid, concurrencyValid, specBatchValid, retryLimitValid].filter((valid) => !valid).length;
  const draftValuesMatch = settings
    ? EDITABLE_SETTING_KEYS.every((key) => settings[key] === draft[key])
    : false;
  const hasDraftChanges = !draftValuesMatch || validationErrors > 0;

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

  const numberError = (message: string) => (
    <p className="mt-1 text-xs text-red-600" role="alert">
      {message}
    </p>
  );

  const renderCommonSettings = () => (
    <div className="grid gap-4 xl:grid-cols-2">
      <section className="rounded-xl border border-border bg-white p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-foreground">文件保存与环境</h3>
            <p className="mt-1 text-xs leading-5 text-slate-500">日常使用内置浏览器；需要排障时再展开高级环境。</p>
          </div>
          <span className="rounded-full bg-muted px-2 py-1 text-[11px] font-medium text-slate-600">
            {chrome?.chrome_found ? "浏览器已就绪" : "等待检查"}
          </span>
        </div>

        <details className="mt-4 rounded-lg border border-border p-3">
        <summary className="cursor-pointer text-sm font-medium">高级环境：浏览器与登录目录</summary>
        <label className="mt-4 block text-sm font-medium" htmlFor="chrome-path">
          自定义浏览器路径（可选）
        </label>
        <div className="mt-2 flex gap-2">
          <InputText
            id="chrome-path"
            className="min-w-0 flex-1"
            value={draft.chrome_path}
            placeholder="留空使用内置 Chromium"
            onChange={(event) => onChange({ ...draft, chrome_path: event.target.value })}
          />
          <Button variant="secondary" onClick={onPickChrome} disabled={busy}>
            {pending.has("settings.pickChrome") ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <FolderOpen className="h-4 w-4" aria-hidden="true" />}
            浏览
          </Button>
        </div>
        <p className="mt-2 text-xs leading-5 text-slate-500">当前留空时自动使用内置浏览器；旧路径失效时也会自动回退，不影响启动。</p>

        <label className="mt-4 block text-sm font-medium" htmlFor="profile-path">
          登录目录（user-data-dir）
        </label>
        <div className="mt-2 flex gap-2">
          <InputText
            id="profile-path"
            className="min-w-0 flex-1"
            value={draft.chrome_profile}
            onChange={(event) => onChange({ ...draft, chrome_profile: event.target.value })}
          />
          <Button variant="secondary" onClick={onPickProfile} disabled={busy}>
            {pending.has("settings.pickProfile") ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <FolderOpen className="h-4 w-4" aria-hidden="true" />}
            浏览
          </Button>
        </div>

        </details>
        <label className="mt-4 block text-sm font-medium" htmlFor="results-dir">
          结果保存目录
        </label>
        <div className="mt-2 flex gap-2">
          <InputText
            id="results-dir"
            className="min-w-0 flex-1"
            value={draft.results_dir}
            onChange={(event) => onChange({ ...draft, results_dir: event.target.value })}
          />
          <Button variant="secondary" onClick={onPickResults} disabled={busy}>
            {pending.has("settings.pickResults") ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <FolderOpen className="h-4 w-4" aria-hidden="true" />}
            浏览
          </Button>
        </div>
      </section>

      <section className="rounded-xl border border-border bg-white p-4">
        <div>
          <h3 className="text-sm font-semibold text-foreground">批次参数</h3>
          <p className="mt-1 text-xs leading-5 text-slate-500">这些值会在下一次开始或继续入库时生效，运行中的批次保持开始时的参数。</p>
        </div>

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-sm font-medium" htmlFor="concurrency">
              同时入库数量
            </label>
            <p className="mt-1 text-xs text-slate-500">范围 1-8</p>
            <InputText
              id="concurrency"
              className="mt-2 w-full"
              inputMode="numeric"
              aria-invalid={!concurrencyValid}
              value={concurrencyText}
              onChange={(event) => {
                const text = event.target.value;
                setConcurrencyText(text);
                if (/^\d*$/.test(text)) {
                  onChange({ ...draft, concurrency: text === "" ? 0 : Number(text) });
                }
              }}
            />
            {!concurrencyValid ? numberError("请输入 1-8 之间的整数。") : null}
          </div>

          <div>
            <label className="block text-sm font-medium" htmlFor="default-limit">
              每次默认条数
            </label>
            <p className="mt-1 text-xs text-slate-500">0 表示全部</p>
            <InputText
              id="default-limit"
              className="mt-2 w-full"
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
            {!limitValid ? numberError("请输入非负整数，留空或 0 表示全部。") : null}
          </div>

          <div className="sm:col-span-2">
            <label className="block text-sm font-medium" htmlFor="item-retry-limit">
              失败自动重试次数
            </label>
            <p className="mt-1 text-xs leading-5 text-slate-500">范围 0-5。0 表示失败后直接跳下一条，需人工处理的情况不会自动重试。</p>
            <InputText
              id="item-retry-limit"
              className="mt-2 w-full sm:max-w-48"
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
            {!retryLimitValid ? numberError("请输入 0-5 的整数，0 表示失败后直接跳下一条。") : null}
          </div>

          <details className="rounded-lg border border-border p-3 sm:col-span-2">
            <summary className="cursor-pointer text-sm font-medium">高级调试端口</summary>
            <label className="mt-3 block text-sm font-medium" htmlFor="cdp-port">
              调试端口
            </label>
            <p className="mt-1 text-xs text-slate-500">范围 1-65535，用于连接浏览器调试协议。</p>
            <InputText
              id="cdp-port"
              className="mt-2 w-full sm:max-w-48"
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
            {!portValid ? numberError("请输入 1-65535 之间的端口号。") : null}
          </details>
        </div>
      </section>
    </div>
  );

  const renderImageSettings = () => (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(18rem,0.72fr)]">
      <section className="rounded-xl border border-border bg-white p-4">
        <div>
          <h3 className="text-sm font-semibold text-foreground">SKU 与图片策略</h3>
          <p className="mt-1 text-xs leading-5 text-slate-500">保留现有素材导入顺序，至少选择一种图片处理方式。</p>
        </div>

        <label className="mt-4 flex items-start gap-3 rounded-lg border border-border bg-muted p-3 text-sm">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 accent-primary"
            checked={draft.sku_template_import}
            onChange={(event) => onChange({ ...draft, sku_template_import: event.target.checked })}
          />
          <span>
            <span className="block font-medium text-foreground">使用千牛模板批量导入 SKU</span>
            <span className="mt-1 block text-xs leading-5 text-slate-500">
              默认关闭。开启后为支持的中性笔类目自动生成并导入 SKU 模板；导入入口不可用时会暂停任务。
            </span>
          </span>
        </label>

        <fieldset className="mt-4 rounded-lg border border-border p-3 text-sm">
          <legend className="px-1 font-medium text-foreground">SKU 图片处理方式（可多选）</legend>
          <label className="mt-3 flex items-start gap-3">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 accent-primary"
              checked={["slim_material", "both"].includes(draft.sku_image_strategy)}
              onChange={() => toggleSkuImageTarget("slim_material")}
            />
            <span>
              <span className="block font-medium text-foreground">官方素材批量导入搜索主图（默认）</span>
              <span className="mt-1 block text-xs leading-5 text-slate-500">
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
              <span className="block font-medium text-foreground">商品规格图（原方式）</span>
              <span className="mt-1 block text-xs leading-5 text-slate-500">
                图片绑定到「商品规格」名称旁的图片位；已有商品只补规格图，不重复建品。
              </span>
            </span>
          </label>

          {["publish_page", "both"].includes(draft.sku_image_strategy) ? (
            <div className="mt-3 rounded-lg border border-border bg-white p-3">
              <label className="block text-sm font-medium" htmlFor="spec-upload-batch-size">
                每批上传规格图数量
              </label>
              <p className="mt-1 text-xs leading-5 text-slate-500">范围 0-99，0 表示全部一次上传。分批保存可以降低一次性上传触发滑块验证的概率。</p>
              <InputText
                id="spec-upload-batch-size"
                className="mt-2 w-full sm:max-w-48"
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
              {!specBatchValid ? numberError("请输入 0-99 的整数，0 表示全部一次上传。") : null}
            </div>
          ) : null}
          <p className="mt-3 text-xs leading-5 text-slate-500">同时选择时，先核验商品规格图，再处理搜索主图；至少保留一项。</p>
        </fieldset>
      </section>

      <aside className="rounded-xl border border-border bg-muted p-3">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white text-primary">
            <FileImage className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <h3 className="text-sm font-semibold text-foreground">当前素材流程</h3>
            <p className="mt-1 text-xs leading-5 text-slate-600">配置只影响下一次开始或继续入库，当前运行批次不会被切页或保存动作打断。</p>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-3 gap-2 text-xs leading-5 text-slate-600">
          <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-white px-3 py-2">
            <span>搜索主图</span>
            <span className="font-medium text-primary">{["slim_material", "both"].includes(draft.sku_image_strategy) ? "已启用" : "未启用"}</span>
          </div>
          <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-white px-3 py-2">
            <span>商品规格图</span>
            <span className="font-medium text-primary">{["publish_page", "both"].includes(draft.sku_image_strategy) ? "已启用" : "未启用"}</span>
          </div>
          <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-white px-3 py-2">
            <span>规格图批次</span>
            <span className="font-medium text-foreground">{draft.spec_upload_batch_size || "全部"}</span>
          </div>
        </div>
      </aside>
    </div>
  );

  const renderDebugSettings = () => (
    <div className="space-y-4">
      <section className="rounded-xl border border-border bg-white p-4">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-primary">
            <Bug className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <h3 className="text-sm font-semibold text-foreground">排障工具</h3>
            <p className="mt-1 text-xs leading-5 text-slate-500">调试开关即时生效，不需要点击保存；其它设置继续保留在当前草稿中。</p>
          </div>
        </div>
        <label className="mt-4 flex items-start gap-3 rounded-lg border border-border bg-muted p-3 text-sm">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 accent-primary"
            checked={draft.debug_browser}
            disabled={busy || !chrome?.chrome_found}
            onChange={(event) => onToggleDebugBrowser(event.target.checked)}
          />
          <span>
            <span className="block font-medium text-foreground">显示自动化浏览器</span>
            <span className="mt-1 block text-xs leading-5 text-slate-500">
              勾选后浏览器窗口立即显示，执行任务时保持显示；取消勾选后窗口立即隐藏，任务栏也不会显示浏览器图标。
            </span>
          </span>
        </label>
      </section>

      <section className="overflow-hidden rounded-xl border border-border bg-slate-950 text-slate-100">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ScrollText className="h-4 w-4" aria-hidden="true" />
            最近运行日志
            <span className="text-xs font-normal text-slate-400">
              {logLevel === "all" && !query ? allLogs.length + " 条" : "匹配 " + filteredLogs.length + " / " + allLogs.length + " 条"}
            </span>
          </div>
          <button
            type="button"
            onClick={onExportLogs}
            disabled={pending.has("settings.exportLogs")}
            className={cn(
              "flex min-h-8 items-center gap-1.5 rounded-md px-2.5 py-1 text-xs transition-colors",
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
        <div className="flex flex-wrap items-center gap-2 border-b border-white/10 px-4 py-2">
          <div className="flex gap-1" role="group" aria-label="日志级别过滤">
            {([["all", "全部"], ["warn", "注意"], ["error", "异常"]] as const).map(([level, label]) => (
              <button
                key={level}
                type="button"
                onClick={() => setLogLevel(level)}
                aria-pressed={logLevel === level}
                className={cn(
                  "min-h-8 rounded-md px-2.5 py-1 text-xs transition-colors",
                  logLevel === level ? "bg-white/15 text-white" : "text-slate-400 hover:bg-white/5 hover:text-white",
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <input
            type="search"
            className="min-h-8 w-full rounded-md border border-white/15 bg-white/5 px-2 py-1 text-xs text-slate-100 outline-none transition-colors placeholder:text-slate-500 focus:border-primary sm:ml-auto sm:w-56"
            placeholder="搜索日志关键词"
            aria-label="搜索日志关键词"
            value={logQuery}
            onChange={(event) => setLogQuery(event.target.value)}
          />
        </div>
        <div className="min-h-24 overflow-visible p-4 font-mono text-xs leading-6">
          {allLogs.length === 0 ? (
            <p className="font-sans text-slate-500">暂无运行日志。扫描清单或开始执行后，关键步骤会显示在这里。</p>
          ) : filteredLogs.length === 0 ? (
            <p className="font-sans text-slate-500">没有匹配的日志，可调整级别或关键词。</p>
          ) : (
            filteredLogs.map((entry, index) => (
              <p
                key={entry.time + "-" + index}
                className={cn("break-words", {
                  "text-red-300": entry.level === "error",
                  "text-amber-200": entry.level === "warn",
                  "text-slate-200": entry.level === "info",
                })}
              >
                <span className="text-slate-500">{entry.time}</span>
                {entry.worker_id ? " [" + entry.worker_id + "]" : ""}{entry.product_id ? ` ${entry.product_id}` : ""} {entry.message}
              </p>
            ))
          )}
        </div>
      </section>
    </div>
  );

  const renderUpdateAndLicense = () => (
    <div className="space-y-4">
      <UpdatePanel update={update} />
      <article className="rounded-xl border border-border bg-white p-4" data-testid="license-info">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-primary">
            <KeyRound className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <h3 className="text-sm font-semibold text-foreground">授权信息</h3>
            <p className="mt-1 text-xs leading-5 text-slate-500">授权只绑定本机，不会被软件更新清除。</p>
          </div>
        </div>
        {license ? (
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-border bg-muted p-3 text-xs leading-5">
              <p className="text-slate-500">授权状态</p>
              <p className={cn("mt-1 font-medium", license.activated ? "text-emerald-600" : "text-red-600")}>
                {license.activated ? "已激活" : "未激活"}
                {license.activated && license.memo ? "（" + license.memo + "）" : ""}
              </p>
            </div>
            <div className="rounded-lg border border-border bg-muted p-3 text-xs leading-5">
              <p className="text-slate-500">本机机器码</p>
              <code className="mt-1 block break-all font-mono font-semibold text-foreground">{license.machine_code}</code>
            </div>
            <div className="rounded-lg border border-border bg-muted p-3 text-xs leading-5">
              <p className="text-slate-500">有效期</p>
              <p className="mt-1 font-medium text-foreground">
                {license.activated
                  ? license.expires_at
                    ? new Date(license.expires_at * 1000).toLocaleDateString("zh-CN") + " 到期（剩余 " + (license.days_left ?? 0) + " 天）"
                    : "永久有效"
                  : "未激活"}
              </p>
            </div>
          </div>
        ) : (
          <p className="mt-4 text-xs text-slate-400">授权信息读取中…</p>
        )}
        {license?.activated ? (
          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-border pt-4">
            <Button variant="danger" onClick={() => void onDeactivate()} disabled={deactivating}>
              {deactivating ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
              取消本机激活
            </Button>
            <p className="text-xs text-slate-500">换电脑或重装系统前可先取消激活；取消后需重新输入激活码。</p>
          </div>
        ) : null}
      </article>
    </div>
  );

  const activeContent = activeSection === "common"
    ? renderCommonSettings()
    : activeSection === "images"
      ? renderImageSettings()
      : activeSection === "debug"
        ? renderDebugSettings()
        : renderUpdateAndLicense();

  return (
    <PanelFrame
      title="设置与排障"
      hint="管理工作参数、图片处理、日志和软件更新。"
      actions={
        <div className="flex flex-wrap items-center justify-end gap-3">
          <div className="flex flex-col items-end gap-1 text-xs">
            <span className="inline-flex items-center gap-1.5 text-slate-500">
              <Check className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
              {settings ? "当前生效值已加载" : "正在读取当前生效值"}
            </span>
            {hasDraftChanges ? (
              <span className="rounded-full bg-amber-50 px-2 py-0.5 font-medium text-amber-700">有未保存草稿</span>
            ) : (
              <span className="rounded-full bg-muted px-2 py-0.5 font-medium text-primary">草稿已同步</span>
            )}
          </div>
          <Button
            onClick={onSave}
            disabled={busy || !portValid || !limitValid || !concurrencyValid || !specBatchValid || !retryLimitValid}
          >
            {pending.has("settings.save") ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Save className="h-4 w-4" aria-hidden="true" />}
            保存设置
          </Button>
        </div>
      }
    >

      <div className={cn("flex min-h-0 flex-1 flex-col gap-3", className)}>
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-white">
          <nav className="flex shrink-0 flex-wrap gap-1 border-b border-border bg-muted/60 p-2" role="tablist" aria-label="设置分组" onKeyDown={handleTabKeys}>
            {SETTINGS_SECTIONS.map((section) => {
              const Icon = section.icon;
              const active = activeSection === section.id;
              return (
                <button
                  key={section.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  tabIndex={active ? 0 : -1}
                  aria-controls="settings-panel"
                  onClick={() => { setActiveSection(section.id); onSectionChange?.(section.id); }}
                  className={cn(
                    "flex min-h-10 flex-1 items-center gap-2 rounded-lg px-3 text-left transition-colors sm:min-w-40",
                    active ? "bg-white text-primary shadow-sm" : "text-slate-600 hover:bg-white/70 hover:text-foreground",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{section.label}</span>
                    <span className="hidden text-[11px] leading-4 text-slate-500 lg:block">{section.description}</span>
                  </span>
                  {section.id === "common" && validationErrors > 0 ? (
                    <span className="ml-auto rounded-full bg-red-50 px-1.5 py-0.5 text-[10px] font-semibold text-red-600">{validationErrors}</span>
                  ) : null}
                </button>
              );
            })}
          </nav>
          <div
            id="settings-panel"
            role="tabpanel"
            aria-label={SETTINGS_SECTIONS.find((section) => section.id === activeSection)?.label}
            className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto bg-background/45 p-3 sm:p-4"
          >
            {activeContent}
          </div>
        </div>
      </div>
    </PanelFrame>
  );
}
