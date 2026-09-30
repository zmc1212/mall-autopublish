export interface ChromeStatus {
  chrome_path: string;
  chrome_found: boolean;
  browser_source: "bundled" | "custom" | "system" | "missing";
  profile: string;
  cdp_port: number;
  debug_browser: boolean;
  cdp: boolean;
  browser: string;
  logged_in: boolean;
  blocker: string;
  checking?: boolean;
  url: string;
  cli_js: string;
  cli_js_found: boolean;
  node: string;
  node_found: boolean;
  error?: string;
  opened?: string;
  notice?: string;
}

export interface LogEntry {
  time: string;
  level: string;
  message: string;
}

export interface WorkbookRow {
  row: number;
  product_id: string;
  title: string;
  category: string;
  brand: string;
  validation: string;
  execution: string;
  notice: string;
  errors: string[];
  main_count: number;
  portrait_count: number;
  detail_count: number;
  sku_count: number;
  pack: string;
  pack_found?: boolean;
  taobao_item_id?: string;
  view_url?: string;
  edit_url?: string;
  flow_version?: string;
  sku_image_strategy?: string;
  spec_image_stage?: string;
  flow_stage?: string;
  run_status?: string;
  sku_material_manifest?: unknown;
  material_result?: unknown;
  last_error?: string;
  updated_at?: string;
  /** 本次入库该商品的实际耗时（秒）；跳过或旧记录为 null。 */
  duration_seconds?: number | null;
}

export interface JobState {
  status: string;
  phase: string;
  blocker: string;
  message: string;
  current_row: number | null;
  current_id: string;
  done: number;
  total: number;
  started_at?: number | null;
  finished_at?: number | null;
  /** 运行中为已用时、结束后为总耗时（秒）；未开始为 null。 */
  elapsed_seconds?: number | null;
  /** 本段任务实际处理条目的平均耗时（秒）；无记录为 null。 */
  avg_item_seconds?: number | null;
  workbook_path: string;
  workspace_path?: string;
  result_xlsx: string;
  result_json: string;
  valid: number;
  failed: number;
  pending?: number;
  retryable?: number;
  can_resume?: boolean;
  restored?: boolean;
  stalled?: boolean;
  count: number;
  rows: WorkbookRow[];
  logs: LogEntry[];
}

export interface JobHistoryEntry {
  file: string;
  source: string;
  started_at: number | null;
  finished_at: number | null;
  duration_seconds: number | null;
  total: number;
  succeeded: number;
  failed: number;
  avg_seconds: number | null;
}

export interface AppSettings {
  chrome_path: string;
  chrome_profile: string;
  cdp_port: number;
  debug_browser: boolean;
  sku_template_import: boolean;
  skip_spec_images: boolean;
  sku_image_strategy: string;
  settings_version?: number;
  limit: number;
  /** 入库后进编辑页每批补传的规格图行数；0 表示全部一次上传。 */
  spec_upload_batch_size: number;
  results_dir: string;
}

export interface WorkspaceDefaults {
  brand: string;
  attributes_template: string;
  logistics_template: string;
  sales_template: string;
  price: number | string;
  stock: number | string;
}

export interface WorkspaceScanFolder {
  product_id: string;
  name: string;
  path: string;
  relative: string;
  category: string;
  category_path: string;
  selected: boolean;
  main_count: number;
  portrait_count: number;
  detail_count: number;
  sku_count: number;
}

export interface WorkspaceCategory {
  name: string;
  path: string;
  relative: string;
  selected: boolean;
  product_count: number;
  error_count: number;
  template_found: boolean;
  notice: string;
}

export interface WorkspaceScan {
  root?: string;
  folders?: WorkspaceScanFolder[];
  categories?: WorkspaceCategory[];
  skipped?: { folder: string; category?: string; reason: string }[];
  errors?: { folder: string; category?: string; error: string }[];
}

export interface WorkspaceInfo {
  path: string;
  workbook_path?: string;
  defaults: WorkspaceDefaults;
  registry: {
    attributes: string[];
    logistics: string[];
    sales: string[];
  };
  scan?: WorkspaceScan | null;
}

export interface SyncSummary {
  added: string[];
  removed: string[];
  created?: boolean;
}

export interface AppStatus {
  _rev?: string;
  chrome: ChromeStatus;
  job: JobState;
  workspace?: WorkspaceInfo;
  settings: AppSettings;
}
