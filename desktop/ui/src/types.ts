export interface ChromeStatus {
  chrome_path: string;
  chrome_found: boolean;
  profile: string;
  cdp_port: number;
  cdp: boolean;
  browser: string;
  logged_in: boolean;
  blocker: string;
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
  count: number;
  rows: WorkbookRow[];
  logs: LogEntry[];
}

export interface AppSettings {
  chrome_path: string;
  chrome_profile: string;
  cdp_port: number;
  debug_browser: boolean;
  confirm_submit: boolean;
  limit: number;
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
  main_count: number;
  portrait_count: number;
  detail_count: number;
  sku_count: number;
}

export interface WorkspaceScan {
  root?: string;
  folders?: WorkspaceScanFolder[];
  skipped?: { folder: string; reason: string }[];
  errors?: { folder: string; error: string }[];
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

export interface AppStatus {
  chrome: ChromeStatus;
  job: JobState;
  workspace?: WorkspaceInfo;
  settings: AppSettings;
}
