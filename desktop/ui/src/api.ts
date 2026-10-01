import type { AppSettings, AppStatus, JobHistoryEntry, JobState, SyncSummary, WorkspaceDefaults, WorkspaceInfo } from "./types";

const base = () => window.__QIANNIU_API_BASE__ || "";

const DEFAULT_TIMEOUT_MS = 15000;

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${base()}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
      signal: init?.signal ?? controller.signal,
    });
    if (!response.ok) {
      // 响应体只能读一次：先整体取文本，再尝试按 JSON 解析出 detail
      const raw = await response.text().catch(() => "");
      let detail = response.statusText;
      try {
        const payload = JSON.parse(raw) as { detail?: string };
        if (payload.detail) detail = payload.detail;
      } catch {
        detail = raw || detail;
      }
      throw new ApiError(detail || `请求失败 ${response.status}`, response.status);
    }
    return (await response.json()) as T;
  } catch (exc) {
    if (exc instanceof DOMException && exc.name === "AbortError") {
      throw new ApiError(`请求超时（${Math.round(timeoutMs / 1000)} 秒）：${path}`, 0);
    }
    throw exc;
  } finally {
    window.clearTimeout(timer);
  }
}

export const api = {
  status: () => request<AppStatus>("/api/status", undefined, 5000),
  openChrome: () => request<ChromeLike>("/api/chrome/open", { method: "POST" }),
  checkLogin: () => request<{ started: boolean }>("/api/chrome/check-login", { method: "POST" }, 5000),
  importWorkbook: (path: string) =>
    request<JobState>("/api/workbook/import", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  validateWorkbook: () =>
    request<JobState & { sync?: SyncSummary }>("/api/workbook/validate", { method: "POST" }),
  openWorkspace: (path: string, selectedCategories?: string[]) =>
    request<JobState & { workspace?: WorkspaceInfo; sync?: SyncSummary }>("/api/workspace/open", {
      method: "POST",
      body: JSON.stringify({ path, selected_categories: selectedCategories }),
    }),
  rescanWorkspace: (selectedCategories?: string[]) =>
    request<JobState & { workspace?: WorkspaceInfo; sync?: SyncSummary }>("/api/workspace/rescan", {
      method: "POST",
      body: JSON.stringify({ selected_categories: selectedCategories }),
    }),
  saveWorkspaceDefaults: (body: Partial<WorkspaceDefaults>) =>
    request<{ defaults: WorkspaceDefaults; registry: WorkspaceInfo["registry"]; path: string }>("/api/workspace/defaults", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  createTemplate: (path: string) =>
    request<{ path: string }>("/api/template", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  startJob: (limit: number, forceNew = false, retryFailed = false) =>
    request<JobState>("/api/job/start", {
      method: "POST",
      body: JSON.stringify({
        limit,
        force_new: forceNew,
        retry_failed: retryFailed,
      }),
    }),
  stopJob: () => request<JobState>("/api/job/stop", { method: "POST" }),
  jobHistory: () => request<{ items: JobHistoryEntry[] }>("/api/job/history"),
  exportLogs: () =>
    request<LogExportResult>("/api/logs/export", { method: "POST" }, 60000),
  openItem: (row: number, productId: string, action: "view" | "edit") =>
    request<{ ok: boolean; url: string }>("/api/item/open", {
      method: "POST",
      body: JSON.stringify({ row, product_id: productId, action }),
    }),
  clearItem: (row: number, productId: string) =>
    request<{ ok: boolean; row: number; product_id: string }>("/api/item/clear", {
      method: "POST",
      body: JSON.stringify({ row, product_id: productId }),
    }),
  saveSettings: (body: Partial<AppSettings>) =>
    request<SavedSettings>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
};

type ChromeLike = AppStatus["chrome"];

export interface LogExportResult {
  path: string;
  folder: string;
  files: number;
  size: number;
}

// debug_browser_applied 为 False 时表示浏览器尚未连接，偏好已保存、下次启动浏览器时生效
export type SavedSettings = AppSettings & { debug_browser_applied?: boolean | null };

export async function nativePick(
  method: "pick_excel" | "pick_chrome" | "pick_folder" | "save_template",
): Promise<string> {
  const bridge = window.pywebview?.api;
  if (!bridge) return "";
  return (await bridge[method]()) || "";
}

export async function nativeOpen(path: string): Promise<boolean> {
  const bridge = window.pywebview?.api;
  if (!bridge) {
    window.open(path, "_blank");
    return true;
  }
  return bridge.open_path(path);
}
