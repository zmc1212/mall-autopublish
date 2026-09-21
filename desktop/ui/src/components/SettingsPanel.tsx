import { FolderOpen, Save } from "lucide-react";

import { Button, InputText } from "../theme";
import type { AppSettings } from "../types";

import { PanelFrame } from "./Sidebar";

interface SettingsPanelProps {
  settings: AppSettings | null;
  draft: AppSettings;
  busy: boolean;
  onChange: (next: AppSettings) => void;
  onPickChrome: () => void;
  onPickResults: () => void;
  onPickProfile: () => void;
  onSave: () => void;
  className?: string;
}

export default function SettingsPanel({
  settings,
  draft,
  busy,
  onChange,
  onPickChrome,
  onPickResults,
  onPickProfile,
  onSave,
  className = "",
}: SettingsPanelProps) {
  return (
    <PanelFrame title="设置" hint="Chrome 路径会自动探测，也可手改。结果 Excel 默认保存在本机用户目录。">
      <div className={`max-w-3xl min-h-0 flex-1 space-y-4 overflow-auto ${className}`}>
        <article className="rounded-2xl border border-border bg-white p-5">
          <label className="text-sm font-medium" htmlFor="chrome-path">
            Chrome 路径
          </label>
          <div className="mt-2 flex gap-2">
            <InputText
              id="chrome-path"
              value={draft.chrome_path}
              onChange={(event) => onChange({ ...draft, chrome_path: event.target.value })}
            />
            <Button variant="secondary" onClick={onPickChrome} disabled={busy}>
              <FolderOpen className="h-4 w-4" aria-hidden="true" />
              浏览
            </Button>
          </div>
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
              浏览
            </Button>
          </div>
          <label className="mt-4 block text-sm font-medium" htmlFor="cdp-port">
            调试端口
          </label>
          <InputText
            id="cdp-port"
            className="mt-2 w-32"
            value={String(draft.cdp_port)}
            onChange={(event) =>
              onChange({ ...draft, cdp_port: Number(event.target.value.replace(/\D/g, "") || 9222) })
            }
          />
          <label className="mt-5 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 accent-primary"
              checked={draft.debug_browser}
              onChange={(event) => onChange({ ...draft, debug_browser: event.target.checked })}
            />
            <span>
              <span className="block font-medium text-slate-800">调试模式：显示自动化浏览器</span>
              <span className="mt-1 block text-xs text-slate-500">
                开启后，执行入库时 Chrome 窗口保持可见，便于观察规格图上传和弹窗状态。
              </span>
            </span>
          </label>
          <label className="mt-4 block text-sm font-medium" htmlFor="default-limit">
            每次默认条数（0 表示全部）
          </label>
          <InputText
            id="default-limit"
            className="mt-2 w-32"
            value={String(draft.limit)}
            onChange={(event) =>
              onChange({ ...draft, limit: Number(event.target.value.replace(/\D/g, "") || 0) })
            }
          />
          <div className="mt-6">
            <Button onClick={onSave} disabled={busy}>
              <Save className="h-4 w-4" aria-hidden="true" />
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
