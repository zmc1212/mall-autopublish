import type { AppSettings, AppStatus, JobState, WorkspaceDefaults, WorkspaceInfo } from "./types";

const base = () => window.__QIANNIU_API_BASE__ || "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${base()}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      detail = await response.text();
    }
    throw new Error(detail || `请求失败 ${response.status}`);
  }
  return (await response.json()) as T;
}

export const api = {
  status: () => request<AppStatus>("/api/status"),
  job: () => request<JobState>("/api/job"),
  openChrome: () => request<ChromeLike>("/api/chrome/open", { method: "POST" }),
  importWorkbook: (path: string) =>
    request<JobState>("/api/workbook/import", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  validateWorkbook: () => request<JobState>("/api/workbook/validate", { method: "POST" }),
  openWorkspace: (path: string) =>
    request<JobState & { workspace?: WorkspaceInfo }>("/api/workspace/open", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  rescanWorkspace: () => request<JobState & { workspace?: WorkspaceInfo }>("/api/workspace/rescan", { method: "POST" }),
  getWorkspaceDefaults: () => request<{ defaults: WorkspaceDefaults; registry: WorkspaceInfo["registry"]; path: string }>("/api/workspace/defaults"),
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
  startJob: (confirmSubmit: boolean, limit: number, forceNew = false, retryFailed = false) =>
    request<JobState>("/api/job/start", {
      method: "POST",
      body: JSON.stringify({
        confirm_submit: confirmSubmit,
        limit,
        force_new: forceNew,
        retry_failed: retryFailed,
      }),
    }),
  stopJob: () => request<JobState>("/api/job/stop", { method: "POST" }),
  openItem: (row: number, productId: string, action: "view" | "edit") =>
    request<{ ok: boolean; url: string }>("/api/item/open", {
      method: "POST",
      body: JSON.stringify({ row, product_id: productId, action }),
    }),
  saveSettings: (body: Partial<AppSettings>) =>
    request<AppSettings>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
};

type ChromeLike = AppStatus["chrome"];

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
