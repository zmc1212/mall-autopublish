/// <reference types="vite/client" />

interface PyWebviewApi {
  pick_excel: () => Promise<string>;
  pick_chrome: () => Promise<string>;
  pick_folder: () => Promise<string>;
  save_template: () => Promise<string>;
  open_path: (path: string) => Promise<boolean>;
}

interface Window {
  pywebview?: { api: PyWebviewApi };
  __QIANNIU_API_BASE__?: string;
}
