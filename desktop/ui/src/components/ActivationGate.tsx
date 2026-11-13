import { Copy, FileUp, KeyRound, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api";
import { Button, InputText } from "../theme";
import type { LicenseState } from "../types";

interface ActivationGateProps {
  /** 激活成功（或发现本机已有有效授权）后回调，App 据此切换到主界面。 */
  onActivated: (state: LicenseState) => void;
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // WebView2 剪贴板权限受限时回退到 execCommand
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try {
      return document.execCommand("copy");
    } catch {
      return false;
    } finally {
      document.body.removeChild(area);
    }
  }
}

export default function ActivationGate({ onActivated }: ActivationGateProps) {
  const [machineCode, setMachineCode] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [issue, setIssue] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  const loadStatus = useCallback(async () => {
    try {
      const state = await api.licenseStatus();
      if (state.activated) {
        onActivated(state);
        return;
      }
      setMachineCode(state.machine_code);
      setIssue(state.issue || "");
      setError("");
      // 尚未激活时，能正常加载激活页和授权接口也算启动成功。
      void api.confirmUpdateBoot().catch(() => {});
    } catch (exc) {
      setError("无法连接本地服务：" + (exc instanceof Error ? exc.message : String(exc)));
    }
  }, [onActivated]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const activate = async (raw: string) => {
    const value = raw.trim();
    if (!value) {
      setError("请先粘贴开发者提供的激活码。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const state = await api.activateLicense(value);
      onActivated(state);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const onCopyMachineCode = async () => {
    if (!machineCode) return;
    const ok = await copyText(machineCode);
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    }
  };

  const onPickKeyFile = async (file: File | null) => {
    if (!file) return;
    try {
      const text = await file.text();
      setCode(text);
      await activate(text);
    } catch (exc) {
      setError("激活码文件读取失败：" + (exc instanceof Error ? exc.message : String(exc)));
    } finally {
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  return (
    <div className="flex h-full items-start justify-center overflow-y-auto overscroll-contain bg-background p-4 sm:p-6 lg:p-8">
      <div className="my-auto grid w-full max-w-5xl overflow-hidden rounded-xl border border-border bg-white shadow-[0_18px_60px_rgba(22,62,53,0.12)] md:grid-cols-[minmax(15rem,0.72fr)_minmax(0,1.28fr)]">
        <aside className="flex flex-col justify-between bg-foreground p-5 text-white sm:p-6 lg:p-8">
          <div>
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-white">
              <KeyRound className="h-5 w-5" aria-hidden="true" />
            </div>
            <h1 className="mt-5 text-2xl font-semibold tracking-tight">激活软件</h1>
            <p className="mt-2 text-sm leading-6 text-white/70">
              这是一次性的本机授权。完成激活后即可离线使用，升级不会清除已有授权。
            </p>
          </div>
          <div className="mt-8 space-y-3 text-xs leading-5 text-white/60">
            <p className="flex items-center gap-2 text-white/90">
              <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" />
              绑定当前电脑
            </p>
            <p className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-white/30" aria-hidden="true" />
              不影响登录态和工作目录
            </p>
            <p className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-white/30" aria-hidden="true" />
              换电脑时可重新领取
            </p>
          </div>
        </aside>

        <main className="min-w-0 p-5 sm:p-6 lg:p-8">
          <div className="max-w-2xl">
            <h2 className="text-lg font-semibold text-foreground">完成授权后开始工作</h2>
            <p className="mt-1 text-sm leading-6 text-slate-500">
              把本机机器码发给开发者领取激活码，再粘贴回来完成授权。
            </p>

            <section className="mt-5 rounded-xl border border-border bg-muted/60 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-foreground">第一步：复制本机机器码</p>
                  <p className="mt-1 text-xs leading-5 text-slate-500">机器码只用于识别这台电脑，可直接发给开发者。</p>
                </div>
                <span className="rounded-full bg-white px-2 py-1 text-[11px] font-medium text-slate-600">1 / 2</span>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <code
                  data-testid="machine-code"
                  className="min-h-11 min-w-0 flex-1 break-all rounded-lg border border-border bg-white px-3 py-2 font-mono text-sm font-semibold tracking-wider text-foreground select-all"
                >
                  {machineCode || "读取中…"}
                </code>
                {machineCode ? (
                  <Button variant="secondary" onClick={onCopyMachineCode}>
                    <Copy className="h-4 w-4" aria-hidden="true" />
                    {copied ? "已复制" : "复制"}
                  </Button>
                ) : (
                  <Button variant="secondary" onClick={() => void loadStatus()}>
                    <RefreshCw className="h-4 w-4" aria-hidden="true" />
                    重试
                  </Button>
                )}
              </div>
            </section>

            {issue ? (
              <div
                data-testid="license-issue"
                className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs leading-5 text-amber-800"
              >
                <p className="font-medium">检测到本机已有授权，但当前无法使用：{issue}</p>
                <p className="mt-1 text-amber-700">
                  软件升级不会清除授权。若因重装系统、更换电脑或清理过系统盘导致失效，把上方机器码发给开发者即可重新领取激活码。
                </p>
              </div>
            ) : null}

            <section className="mt-4 rounded-xl border border-border bg-white p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-foreground">第二步：粘贴收到的激活码</p>
                  <p className="mt-1 text-xs leading-5 text-slate-500">支持整段粘贴，系统会自动忽略横线和空格。</p>
                </div>
                <span className="rounded-full bg-muted px-2 py-1 text-[11px] font-medium text-slate-600">2 / 2</span>
              </div>
              <InputText
                className="mt-3 font-mono"
                placeholder="例如：A1B2C-D3E4F-…"
                value={code}
                spellCheck={false}
                onChange={(event) => setCode(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !busy) void activate(code);
                }}
              />
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button onClick={() => void activate(code)} disabled={busy || !code.trim()}>
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <ShieldCheck className="h-4 w-4" aria-hidden="true" />}
                  激活
                </Button>
                <Button variant="secondary" onClick={() => fileInput.current?.click()} disabled={busy}>
                  <FileUp className="h-4 w-4" aria-hidden="true" />
                  导入激活码文件
                </Button>
                <input
                  ref={fileInput}
                  type="file"
                  accept=".key,.txt"
                  className="hidden"
                  onChange={(event) => void onPickKeyFile(event.target.files?.[0] ?? null)}
                />
              </div>
              {error ? (
                <p className="mt-3 rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm leading-5 text-red-700" role="alert" data-testid="activation-error">
                  {error}
                </p>
              ) : null}
            </section>

            <p className="mt-4 text-xs leading-5 text-slate-400">
              激活后可离线使用；换电脑或重装系统后重新领取激活码。
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}
