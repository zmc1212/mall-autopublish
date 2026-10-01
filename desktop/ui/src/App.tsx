import { useCallback, useEffect, useRef, useState } from "react";

import { api, nativeOpen, nativePick } from "./api";
import ConnectPanel from "./components/ConnectPanel";
import RunPanel from "./components/RunPanel";
import RunNotifications from "./components/RunNotifications";
import SettingsPanel from "./components/SettingsPanel";
import Sidebar from "./components/Sidebar";
import type { NavId } from "./components/Sidebar";
import StatusBar from "./components/StatusBar";
import ToastHost from "./components/ToastHost";
import WorkbookPanel from "./components/WorkbookPanel";
import type { AppSettings, AppStatus, SyncSummary, WorkbookRow, WorkspaceDefaults } from "./types";
import { pushToast } from "./utils/toasts";

const LAST_WORKBOOK_KEY = "qianniu.lastWorkbook";
const LAST_WORKSPACE_KEY = "qianniu.lastWorkspace";

const EMPTY_SETTINGS: AppSettings = {
  chrome_path: "",
  chrome_profile: "",
  cdp_port: 9222,
  debug_browser: false,
  sku_template_import: false,
  skip_spec_images: false,
  sku_image_strategy: "slim_material",
  settings_version: 3,
  limit: 0,
  spec_upload_batch_size: 2,
  item_retry_limit: 1,
  results_dir: "",
};

const EMPTY_DEFAULTS: WorkspaceDefaults = {
  brand: "卡游",
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

function displayName(path: string) {
  const normalized = path.replace(/[\\/]+$/, "");
  return normalized.split(/[\\/]/).pop() || normalized;
}

function syncNotice(snap: { sync?: SyncSummary } | undefined, message: string) {
  const sync = snap?.sync;
  if (!sync) return message;
  const parts: string[] = [];
  if (sync.added?.length) parts.push(`新增 ${sync.added.length} 款`);
  if (sync.removed?.length) parts.push(`移除 ${sync.removed.length} 款`);
  return parts.length ? `${message}（${parts.join("，")}）` : message;
}

export default function App() {
  const [nav, setNav] = useState<NavId>("connect");
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [pending, setPending] = useState<ReadonlySet<string>>(new Set());
  const [pathDraft, setPathDraft] = useState("");
  const [workspaceDraft, setWorkspaceDraft] = useState("");
  const [detailRow, setDetailRow] = useState<WorkbookRow | null>(null);
  const [retryFailed, setRetryFailed] = useState(false);
  const [limit, setLimit] = useState("");
  const [settingsDraft, setSettingsDraft] = useState<AppSettings>(EMPTY_SETTINGS);
  const [defaultsDraft, setDefaultsDraft] = useState<WorkspaceDefaults>(EMPTY_DEFAULTS);
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);
  const [scanDecisionOpen, setScanDecisionOpen] = useState(false);
  const hydrated = useRef(false);
  const offline = useRef(false);
  const restoreNotified = useRef(false);
  const autoImporting = useRef(false);
  const categorySelectionDirty = useRef(false);
  const pathDraftDirty = useRef(false);
  const workspaceDraftDirty = useRef(false);
  const lastRev = useRef("");

  const refresh = useCallback(async () => {
    let next = await api.status();
    if (next._rev && next._rev === lastRev.current) {
      return next; // 状态内容未变：跳过 setState，避免空闲时整树重渲染
    }
    if (!next.job.workbook_path && !next.job.workspace_path && !autoImporting.current) {
      const savedWorkspace = readLocal(LAST_WORKSPACE_KEY);
      const saved = readLocal(LAST_WORKBOOK_KEY);
      if (savedWorkspace) {
        autoImporting.current = true;
        try {
          await api.openWorkspace(savedWorkspace);
          next = await api.status();
          pushToast("success", `已恢复上次工作空间：${displayName(savedWorkspace)}`);
        } catch {
          clearLocal(LAST_WORKSPACE_KEY);
          pushToast("warning", "上次工作空间无法自动打开，请重新选择");
        }
      } else if (saved) {
        autoImporting.current = true;
        try {
          await api.importWorkbook(saved);
          next = await api.status();
          pushToast("success", `已恢复上次清单：${displayName(saved)}`);
        } catch {
          clearLocal(LAST_WORKBOOK_KEY);
          pushToast("warning", "上次清单无法自动打开，请重新选择 Excel");
        }
      }
    }
    if (next.job.workspace_path) {
      writeLocal(LAST_WORKSPACE_KEY, next.job.workspace_path);
      if (next.job.restored && !restoreNotified.current) {
        restoreNotified.current = true;
        pushToast("success", `已恢复上次工作空间：${displayName(next.job.workspace_path || "")}`);
      }
    } else if (next.job.workbook_path) {
      writeLocal(LAST_WORKBOOK_KEY, next.job.workbook_path);
      if (next.job.restored && !restoreNotified.current) {
        restoreNotified.current = true;
        pushToast("success", `已恢复上次清单：${displayName(next.job.workbook_path || "")}`);
      }
    }
    setStatus(next);
    lastRev.current = next._rev || "";
    // 用户编辑过输入框后（含清空），轮询不再回填服务端路径，避免"跳回旧值"
    if (!workspaceDraftDirty.current) {
      setWorkspaceDraft(next.job.workspace_path || next.workspace?.path || "");
    }
    if (!pathDraftDirty.current) {
      setPathDraft(next.job.workbook_path || "");
    }
    if (next.workspace?.defaults) {
      setDefaultsDraft((current) => (hydrated.current ? current : next.workspace?.defaults || current));
    }
    if (!categorySelectionDirty.current && next.workspace?.scan?.categories) {
      setSelectedCategories(
        next.workspace.scan.categories.filter((item) => item.selected).map((item) => item.name),
      );
    }
    if (!hydrated.current) {
      hydrated.current = true;
      setSettingsDraft(next.settings);
      if (next.settings.limit) setLimit(String(next.settings.limit));
      if (next.workspace?.defaults) setDefaultsDraft(next.workspace.defaults);
    }
    return next;
  }, []);

  // 首次进入自动检测一次登录态：浏览器 profile 里有登录记录时直接显示
  // 「已登录」，不再要求用户手动点击「登录卖家中心」。失败不影响状态轮询。
  useEffect(() => {
    void api.checkLogin().catch(() => {});
  }, []);

  useEffect(() => {
    let timer = 0;
    const tick = async () => {
      if (document.hidden) return; // 窗口隐藏时暂停轮询，回前台后立即补一次
      try {
        await refresh();
        if (offline.current) {
          offline.current = false;
          pushToast("success", "与本地服务的连接已恢复");
        }
      } catch (exc) {
        const message = exc instanceof Error ? exc.message : String(exc);
        if (!offline.current) {
          offline.current = true;
          pushToast("error", `与本地服务失去连接：${message}`);
        }
      }
    };
    void tick();
    timer = window.setInterval(() => {
      void tick();
    }, 1200);
    const onVisibility = () => {
      if (!document.hidden) void tick();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [refresh]);

  const runAction = useCallback(
    async (key: string, action: () => Promise<unknown>) => {
      setPending((current) => new Set(current).add(key));
      try {
        await action();
        await refresh();
      } catch (exc) {
        pushToast("error", exc instanceof Error ? exc.message : String(exc));
      } finally {
        setPending((current) => {
          if (!current.has(key)) return current;
          const next = new Set(current);
          next.delete(key);
          return next;
        });
      }
    },
    [refresh],
  );

  const familyBusy = (prefix: string) => {
    for (const key of pending) {
      if (key.startsWith(prefix)) return true;
    }
    return false;
  };

  const chrome = status?.chrome ?? null;
  const job = status?.job ?? null;

  return (
    <div className="flex h-full overflow-hidden bg-background">
      <Sidebar current={nav} onChange={setNav} />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <StatusBar chrome={chrome} loading={!status} />
        <main className="flex min-h-0 flex-1 flex-col overflow-hidden p-4">
          {nav === "connect" ? (
            <ConnectPanel
              chrome={chrome}
              busy={familyBusy("connect.")}
              onOpen={() =>
                runAction("connect.open", async () => {
                  const result = await api.openChrome();
                  pushToast("info", result.notice || "请在弹出窗口登录一次");
                })
              }
            />
          ) : null}
          {nav === "workbook" ? (
            <WorkbookPanel
              job={job}
              workspace={status?.workspace ?? null}
              workspaceDraft={workspaceDraft}
              onWorkspaceDraft={(value) => {
                workspaceDraftDirty.current = true;
                setWorkspaceDraft(value);
              }}
              excelDraft={pathDraft}
              onExcelDraft={(value) => {
                pathDraftDirty.current = true;
                setPathDraft(value);
              }}
              defaults={defaultsDraft}
              onDefaultsChange={setDefaultsDraft}
              selectedCategories={selectedCategories}
              onSelectedCategoriesChange={(value) => {
                categorySelectionDirty.current = true;
                setSelectedCategories(value);
              }}
              busy={familyBusy("workbook.")}
              pending={pending}
              onPickWorkspace={() =>
                runAction("workbook.pickWorkspace", async () => {
                  const picked = await nativePick("pick_folder");
                  if (picked) {
                    setWorkspaceDraft(picked);
                    const snap = await api.openWorkspace(picked);
                    categorySelectionDirty.current = false;
                    setSelectedCategories(
                      (snap.workspace?.scan?.categories || []).filter((item) => item.selected).map((item) => item.name),
                    );
                    writeLocal(LAST_WORKSPACE_KEY, picked);
                    if (snap.workspace?.defaults) setDefaultsDraft(snap.workspace.defaults);
                    setScanDecisionOpen((snap.count || 0) > 0);
                    pushToast("success", syncNotice(snap, `已打开工作空间：${displayName(picked)}`));
                  }
                })
              }
              onRescan={() =>
                runAction("workbook.rescan", async () => {
                  const target = workspaceDraft.trim() || job?.workspace_path || "";
                  const changedWorkspace = Boolean(target && target !== job?.workspace_path);
                  const snap = changedWorkspace
                    ? await api.openWorkspace(target)
                    : await api.rescanWorkspace(
                        categorySelectionDirty.current ? selectedCategories : undefined,
                      );
                  categorySelectionDirty.current = false;
                  setSelectedCategories(
                    (snap.workspace?.scan?.categories || []).filter((item) => item.selected).map((item) => item.name),
                  );
                  if (snap.workspace?.defaults) setDefaultsDraft(snap.workspace.defaults);
                  setScanDecisionOpen((snap.count || 0) > 0);
                  pushToast("success", syncNotice(snap, "已扫描并更新商品清单"));
                })
              }
              onOpenFolder={() => nativeOpen(workspaceDraft.trim() || job?.workspace_path || "")}
              onSaveDefaults={() =>
                runAction("workbook.saveDefaults", async () => {
                  const saved = await api.saveWorkspaceDefaults(defaultsDraft);
                  setDefaultsDraft(saved.defaults);
                  pushToast("success", "已保存批次默认");
                })
              }
              onPickExcel={() =>
                runAction("workbook.pickExcel", async () => {
                  const picked = await nativePick("pick_excel");
                  if (picked) {
                    setPathDraft(picked);
                    await api.importWorkbook(picked);
                    writeLocal(LAST_WORKBOOK_KEY, picked);
                  }
                })
              }
              onImportExcel={() => runAction("workbook.import", () => api.importWorkbook(pathDraft.trim()))}
              onValidate={() =>
                runAction("workbook.validate", async () => {
                  const snap = await api.validateWorkbook();
                  pushToast("success", syncNotice(snap, "已重新扫描并校验商品清单"));
                })
              }
              scanDecisionOpen={scanDecisionOpen}
              onCloseScanDecision={() => setScanDecisionOpen(false)}
              onOpenGeneratedWorkbook={() => {
                setScanDecisionOpen(false);
                pushToast("info", "已打开商品清单，补充后回到软件点击“校验”");
                return nativeOpen(job?.workbook_path || "");
              }}
              onUseDefaults={() => {
                setScanDecisionOpen(false);
                setNav("run");
                pushToast("success", "已采用扫描结果和默认值，可直接开始执行");
              }}
              onTemplate={() =>
                runAction("workbook.template", async () => {
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
              detailRow={detailRow}
              retryFailed={retryFailed}
              limit={limit}
              busy={familyBusy("run.")}
              pending={pending}
              onRetryFailed={setRetryFailed}
              onLimit={setLimit}
              onStart={() =>
                runAction("run.start", () => api.startJob(Number(limit || 0), false, retryFailed))
              }
              onStop={() => runAction("run.stop", () => api.stopJob())}
              onOpenResult={() => nativeOpen(job?.result_xlsx || "")}
              onOpenItem={(row, action) =>
                runAction(`run.openItem.${row.row}`, () => api.openItem(row.row, row.product_id, action))
              }
              onClearItem={(row) => runAction(`run.clearItem.${row.row}`, () => api.clearItem(row.row, row.product_id))}
            />
          ) : null}
          {nav === "settings" ? (
            <SettingsPanel
              settings={status?.settings ?? null}
              chrome={chrome}
              job={job}
              draft={settingsDraft}
              busy={familyBusy("settings.")}
              pending={pending}
              onChange={setSettingsDraft}
              onPickChrome={() =>
                runAction("settings.pickChrome", async () => {
                  const picked = await nativePick("pick_chrome");
                  if (picked) setSettingsDraft((current) => ({ ...current, chrome_path: picked }));
                })
              }
              onPickProfile={() =>
                runAction("settings.pickProfile", async () => {
                  const picked = await nativePick("pick_folder");
                  if (picked) setSettingsDraft((current) => ({ ...current, chrome_profile: picked }));
                })
              }
              onPickResults={() =>
                runAction("settings.pickResults", async () => {
                  const picked = await nativePick("pick_folder");
                  if (picked) setSettingsDraft((current) => ({ ...current, results_dir: picked }));
                })
              }
              onExportLogs={() =>
                runAction("settings.exportLogs", async () => {
                  const result = await api.exportLogs();
                  pushToast("success", `日志已导出（${result.files} 个文件），文件夹已打开`);
                  await nativeOpen(result.folder);
                })
              }
              onToggleDebugBrowser={(checked) => {
                // 勾选立即保存并显示/隐藏窗口，不等“保存设置”；失败时回滚勾选态
                setSettingsDraft((current) => ({ ...current, debug_browser: checked }));
                void runAction("settings.toggleDebugBrowser", async () => {
                  try {
                    const saved = await api.saveSettings({ debug_browser: checked });
                    // 只回写本次变更的字段，避免覆盖草稿中其他未保存的编辑
                    setSettingsDraft((current) => ({ ...current, debug_browser: saved.debug_browser }));
                    if (saved.debug_browser_applied === false) {
                      pushToast("warning", "设置已保存；当前浏览器未连接，将在下次打开浏览器时生效");
                    } else {
                      pushToast("success", checked ? "自动化浏览器窗口已显示" : "自动化浏览器窗口已隐藏");
                    }
                  } catch (exc) {
                    setSettingsDraft((current) => ({ ...current, debug_browser: !checked }));
                    throw exc;
                  }
                });
              }}
              onSave={() =>
                runAction("settings.save", async () => {
                  const saved = await api.saveSettings(settingsDraft);
                  // 用服务端返回的规范值刷新草稿，避免保存后草稿与后端脱钩
                  setSettingsDraft(saved);
                  pushToast("success", "设置已保存，将用于下一次打开千牛窗口和入库任务");
                })
              }
            />
          ) : null}
        </main>
        <RunNotifications
          job={job}
          busy={familyBusy("run.")}
          onDetails={(row) => { setDetailRow({ ...row }); setNav("run"); }}
          onEdit={(row) => { void runAction(`run.openItem.${row.row}`, () => api.openItem(row.row, row.product_id, "edit")); }}
        />
        <ToastHost />
      </div>
    </div>
  );
}
