import { CircleAlert, FolderOpen } from "lucide-react";
import type { ChromeStatus, LicenseState } from "../types";
export default function StatusBar({ chrome, license = null, loading = false, workspacePath = "", onConnect, className = "" }: {
  chrome: ChromeStatus | null; license?: LicenseState | null; loading?: boolean; workspacePath?: string; onConnect?: () => void; className?: string;
}) {
  const name = workspacePath.replace(/[\\/]+$/, "").split(/[\\/]/).pop();
  const loggedIn = Boolean(chrome?.logged_in);
  return <header className={`app-topbar ${className}`}>
    <div className="app-context" title={workspacePath || undefined}>
      <FolderOpen className="h-4 w-4 shrink-0" aria-hidden="true" /><span>工作空间 /</span><strong>{name || "尚未选择工作空间"}</strong>
    </div>
    <div className="connection-indicators" role="status">
      {license?.activated ? (
        <span className="text-slate-600" data-testid="license-expiry" title={license.memo ? "授权备注：" + license.memo : undefined}>
          {license.expires_at ? "授权至 " + new Date(license.expires_at * 1000).toLocaleDateString("zh-CN") : "永久授权"}
        </span>
      ) : null}
      {loading || !chrome ? <span className="text-slate-500">正在连接本地服务…</span> : <>
        <span className={`browser-ready-label ${chrome.chrome_found ? "text-primary" : "text-amber-700"}`}><i className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />{chrome.chrome_found ? "浏览器已准备" : "浏览器未准备好"}</span>
        {loggedIn ? <span className="text-primary"><i className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />卖家中心已登录</span>
          : <button className="inline-flex items-center gap-1 text-amber-700 hover:underline" onClick={onConnect}><CircleAlert className="h-3.5 w-3.5" aria-hidden="true" />{chrome.checking ? "正在检测登录…" : "前往连接店铺"}</button>}
      </>}
    </div>
  </header>;
}
