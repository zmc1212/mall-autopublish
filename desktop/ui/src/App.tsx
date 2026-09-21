import { useCallback, useEffect, useRef, useState } from "react";

import { api, nativeOpen, nativePick } from "./api";
import ConnectPanel from "./components/ConnectPanel";
import RunPanel from "./components/RunPanel";
import SettingsPanel from "./components/SettingsPanel";
import Sidebar from "./components/Sidebar";
import type { NavId } from "./components/Sidebar";
import StatusBar from "./components/StatusBar";
import WorkbookPanel from "./components/WorkbookPanel";
import type { AppSettings, AppStatus, WorkspaceDefaults } from "./types";

const LAST_WORKBOOK_KEY = "qianniu.lastWorkbook";
const LAST_WORKSPACE_KEY = "qianniu.lastWorkspace";

const EMPTY_SETTINGS: AppSettings = {
  chrome_path: "",
  chrome_profile: "",
  cdp_port: 9222,
  debug_browser: false,
  confirm_submit: false,
  limit: 0,
  results_dir: "",
};

const EMPTY_DEFAULTS: WorkspaceDefaults = {
  brand: "",
  attributes_template: "中性笔",
  logistics_template: "48小时",
  sales_template: "仓库多规格",
  price: 9.9,
  stock: 20,
};

function readLocal(key: string) {
  try {
    return window.localStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

function writeLocal(key: string, path: string) {
  if (!path) return;
  try {
    window.localStorage.setItem(key, path);
  } catch {
    /* ignore */
  }
}

function clearLocal(key: string) {
  try {
    window.localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

export default function App() {
  const [nav, setNav] = useState<NavId>("connect");
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pathDraft, setPathDraft] = useState("");
  const [workspaceDraft, setWorkspaceDraft] = useState("");
  const [confirmSubmit, setConfirmSubmit] = useState(false);
  const [forceNew, setForceNew] = useState(false);
  const [retryFailed, setRetryFailed] = useState(false);
  const [limit, setLimit] = useState("");
  const [settingsDraft, setSettingsDraft] = useState<AppSettings>(EMPTY_SETTINGS);
  const [defaultsDraft, setDefaultsDraft] = useState<WorkspaceDefaults>(EMPTY_DEFAULTS);
  const [notice, setNotice] = useState("");
  const hydrated = useRef(false);
  const keepError = useRef(false);
  const autoImporting = useRef(false);

  const refresh = useCallback(async () => {
    let next = await api.status();
    if (!next.job.workbook_path && !next.job.workspace_path && !autoImporting.current) {
      const savedWorkspace = readLocal(LAST_WORKSPACE_KEY);
      const saved = readLocal(LAST_WORKBOOK_KEY);
      if (savedWorkspace) {
        autoImporting.current = true;
        try {
          await api.openWorkspace(savedWorkspace);
          next = await api.status();
          setNotice(`已恢复上次工作空间：${savedWorkspace}`);
        } catch (exc) {
          clearLocal(LAST_WORKSPACE_KEY);
          setNotice(exc instanceof Error ? `上次工作空间无法自动打开：${exc.message}` : "上次工作空间无法自动打开，请重新选择");
        }
      } else if (saved) {
        autoImporting.current = true;
        try {
          await api.importWorkbook(saved);
          next = await api.status();
          setNotice(`已恢复上次清单：${saved}`);
        } catch (exc) {
          clearLocal(LAST_WORKBOOK_KEY);
          setNotice(exc instanceof Error ? `上次清单无法自动打开：${exc.message}` : "上次清单无法自动打开，请重新选择 Excel");
        }
      }
    }
    if (next.job.workspace_path) {
      writeLocal(LAST_WORKSPACE_KEY, next.job.workspace_path);
      if (next.job.restored) {
        setNotice((current) => current || `已恢复上次工作空间：${next.job.workspace_path}`);
      }
    } else if (next.job.workbook_path) {
      writeLocal(LAST_WORKBOOK_KEY, next.job.workbook_path);
      if (next.job.restored) {
        setNotice((current) => current || `已恢复上次清单：${next.job.workbook_path}`);
      }
    }
    setStatus(next);
    setWorkspaceDraft((current) => current || next.job.workspace_path || next.workspace?.path || "");
    setPathDraft((current) => current || next.job.workbook_path || "");
    if (next.workspace?.defaults) {
      setDefaultsDraft((current) => (hydrated.current ? current : next.workspace?.defaults || current));
    }
    if (!hydrated.current) {
      hydrated.current = true;
      setSettingsDraft(next.settings);
      setConfirmSubmit(next.settings.confirm_submit);
      if (next.settings.limit) setLimit(String(next.settings.limit));
      if (next.workspace?.defaults) setDefaultsDraft(next.workspace.defaults);
    }
    return next;
  }, []);

  useEffect(() => {
    let timer = 0;
    const tick = async () => {
      try {
        await refresh();
        if (!keepError.current) setError("");
      } catch (exc) {
        if (!keepError.current) {
          setError(exc instanceof Error ? exc.message : String(exc));
        }
      }
    };
    void tick();
    timer = window.setInterval(() => {
      void tick();
    }, 1200);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    keepError.current = false;
    try {
      await action();
      await refresh();
    } catch (exc) {
      keepError.current = true;
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const chrome = status?.chrome ?? null;
  const job = status?.job ?? null;

  return (
    <div className="flex h-full overflow-hidden bg-background">
      <Sidebar current={nav} onChange={setNav} />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <StatusBar chrome={chrome} loading={!status} />
        <main className="flex min-h-0 flex-1 flex-col overflow-hidden p-4 [@media(min-height:840px)]:p-6">
          {error ? (
            <p className="mb-4 shrink-0 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-destructive" role="alert">
              {error}
            </p>
          ) : null}
          {notice && nav !== "connect" ? (
            <p className="mb-4 shrink-0 truncate rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800" title={notice}>
              {notice}
            </p>
          ) : null}
          {nav === "connect" ? (
            <ConnectPanel
              chrome={chrome}
              busy={busy}
              notice={notice}
              onOpen={() =>
                run(async () => {
                  const result = await api.openChrome();
                  setNotice(result.notice || "请在弹出窗口登录一次");
                })
              }
              onRevealProfile={() => nativeOpen(chrome?.profile || "")}
            />
          ) : null}
          {nav === "workbook" ? (
            <WorkbookPanel
              job={job}
              workspace={status?.workspace ?? null}
              workspaceDraft={workspaceDraft}
              onWorkspaceDraft={setWorkspaceDraft}
              excelDraft={pathDraft}
              onExcelDraft={setPathDraft}
              defaults={defaultsDraft}
              onDefaultsChange={setDefaultsDraft}
              busy={busy}
              onPickWorkspace={() =>
                run(async () => {
                  const picked = await nativePick("pick_folder");
                  if (picked) {
                    setWorkspaceDraft(picked);
                    const snap = await api.openWorkspace(picked);
                    writeLocal(LAST_WORKSPACE_KEY, picked);
                    if (snap.workspace?.defaults) setDefaultsDraft(snap.workspace.defaults);
                    setNotice(`已打开工作空间：${picked}`);
                  }
                })
              }
              onRescan={() =>
                run(async () => {
                  const target = workspaceDraft.trim() || job?.workspace_path || "";
                  const snap =
                    target && target !== job?.workspace_path
                      ? await api.openWorkspace(target)
                      : await api.rescanWorkspace();
                  if (snap.workspace?.defaults) setDefaultsDraft(snap.workspace.defaults);
                  setNotice("已扫描并更新商品清单");
                })
              }
              onOpenFolder={() => nativeOpen(workspaceDraft.trim() || job?.workspace_path || "")}
              onSaveDefaults={() =>
                run(async () => {
                  const saved = await api.saveWorkspaceDefaults(defaultsDraft);
                  setDefaultsDraft(saved.defaults);
                  setNotice("已保存批次默认");
                })
              }
              onPickExcel={() =>
                run(async () => {
                  const picked = await nativePick("pick_excel");
                  if (picked) {
                    setPathDraft(picked);
                    await api.importWorkbook(picked);
                    writeLocal(LAST_WORKBOOK_KEY, picked);
                  }
                })
              }
              onImportExcel={() => run(() => api.importWorkbook(pathDraft.trim()))}
              onValidate={() => run(() => api.validateWorkbook())}
              onTemplate={() =>
                run(async () => {
                  const picked = await nativePick("save_template");
                  const target =
                    picked ||
                    `${status?.settings.results_dir || ""}\\千牛商品清单模板.xlsx`;
                  if (!target.trim()) {
                    throw new Error("请选择模板保存位置");
                  }
                  const created = await api.createTemplate(target);
                  await nativeOpen(created.path);
                })
              }
            />
          ) : null}
          {nav === "run" ? (
            <RunPanel
              job={job}
              confirmSubmit={confirmSubmit}
              forceNew={forceNew}
              retryFailed={retryFailed}
              limit={limit}
              busy={busy}
              onConfirmSubmit={setConfirmSubmit}
              onForceNew={setForceNew}
              onRetryFailed={setRetryFailed}
              onLimit={setLimit}
              onStart={() =>
                run(() => api.startJob(confirmSubmit, Number(limit || 0), forceNew, retryFailed))
              }
              onStop={() => run(() => api.stopJob())}
              onOpenResult={() => nativeOpen(job?.result_xlsx || "")}
              onOpenItem={(row, action) =>
                run(() => api.openItem(row.row, row.product_id, action))
              }
            />
          ) : null}
          {nav === "settings" ? (
            <SettingsPanel
              settings={status?.settings ?? null}
              draft={settingsDraft}
              busy={busy}
              onChange={setSettingsDraft}
              onPickChrome={() =>
                run(async () => {
                  const picked = await nativePick("pick_chrome");
                  if (picked) setSettingsDraft((current) => ({ ...current, chrome_path: picked }));
                })
              }
              onPickProfile={() =>
                run(async () => {
                  const picked = await nativePick("pick_folder");
                  if (picked) setSettingsDraft((current) => ({ ...current, chrome_profile: picked }));
                })
              }
              onPickResults={() =>
                run(async () => {
                  const picked = await nativePick("pick_folder");
                  if (picked) setSettingsDraft((current) => ({ ...current, results_dir: picked }));
                })
              }
              onSave={() => run(() => api.saveSettings(settingsDraft))}
            />
          ) : null}
        </main>
      </div>
    </div>
  );
}
