export type ExecutionLimitMode = "default" | "all" | "custom";

export interface JobRowSelection { row: number; product_id: string; pack_fingerprint?: string }

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
  /** 调度器附加的执行槽标识；旧日志没有此字段。 */
  worker_id?: string;
  product_id?: string;
  row?: number;
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
  /** 主视频文件名；无视频为空串。 */
  video_name?: string;
  /** 主视频容器校验是否通过（false 时明细表标红“格式错误”）。 */
  video_ok?: boolean;
  video_warning?: string;
  video_status?: "uploading" | "bound" | "uploaded" | "failed" | "uncertain" | "paused" | "invalid";
  pack: string;
  pack_fingerprint?: string;
  /** 图片包主图的本地预览地址；不可用时为空。 */
  preview_url?: string;
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
  /** 本批开始时固定的并发数；运行中修改设置不会改变它。 */
  concurrency?: number;
  sku_image_strategy?: string;
  /** 当前各执行槽的状态；空闲槽也可以由调度器返回。 */
  active_workers?: ActiveWorker[];
  /** 需要人工关注的商品数量。 */
  attention_count?: number;
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

export interface ActiveWorker {
  worker_id: string;
  row: number | null;
  product_id: string;
  status: string;
  phase: string;
  started_at?: number | null;
  activity_at?: number | null;
  stalled?: boolean;
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
  /** 同时处理的商品数量，范围 1-8。 */
  concurrency: number;
  /** 入库后进编辑页每批补传的规格图行数；0 表示全部一次上传。 */
  spec_upload_batch_size: number;
  /** 条目失败后的自动重试次数；0 表示失败不重试直接跳下一条。 */
  item_retry_limit: number;
  results_dir: string;
  update_feed_url?: string;
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
  /** 磁盘任务代码比进程内存新：开任务会被拦截，需重启应用。 */
  stale_code?: { files: string[] };
  update?: UpdateState;
}

export interface UpdateState {
  status: string;
  current_version: string;
  version: string;
  notes: string;
  message: string;
  error: string;
  progress: number;
  feed_url: string;
  can_restart: boolean;
}

export interface LicenseState {
  activated: boolean;
  machine_code: string;
  /** 授权签名里的真实到期时间（Unix 秒）；0 表示永久授权。 */
  expires_at: number;
  memo: string;
  days_left: number | null;
  /** 本次离线可用的截止时间（服务端签发的租约，Unix 秒）；0 表示未启用联网确认。 */
  offline_until?: number;
  /** 未激活且本机存在失效授权时的原因说明（如机器码变化、文件损坏）；正常为空串。 */
  issue?: string;
}
