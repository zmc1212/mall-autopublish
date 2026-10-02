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
    } catch (exc) {
      setError(`无法连接本地服务：${exc instanceof Error ? exc.message : String(exc)}`);
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
      setError(`激活码文件读取失败：${exc instanceof Error ? exc.message : String(exc)}`);
    } finally {
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  return (
    <div className="flex h-full items-center justify-center overflow-auto bg-background p-6">
      <div className="w-full max-w-xl space-y-5 rounded-2xl border border-border bg-white p-8 shadow-sm">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-orange-50 text-primary">
            <KeyRound className="h-5 w-5" aria-hidden="true" />
          </span>
          <div>
            <h1 className="text-lg font-semibold">激活软件</h1>
            <p className="text-xs leading-5 text-slate-500">
              本软件按电脑授权。首次使用需要免费领取激活码：把下方机器码发给开发者即可。
            </p>
          </div>
        </div>

        <section className="rounded-xl border border-border bg-slate-50 p-4">
          <p className="text-sm font-medium text-slate-800">第一步：复制本机机器码发给开发者</p>
          <div className="mt-3 flex items-center gap-2">
            <code
              data-testid="machine-code"
              className="min-h-11 flex-1 rounded-lg border border-border bg-white px-3 py-2 font-mono text-base font-semibold tracking-wider text-foreground select-all"
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
            className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs leading-5 text-amber-800"
          >
            <p className="font-medium">检测到本机已有授权，但当前无法使用：{issue}</p>
            <p className="mt-1 text-amber-700">
              软件升级不会清除授权。若因重装系统、更换电脑或清理过系统盘导致失效，把上方机器码发给开发者即可重新领取激活码。
            </p>
          </div>
        ) : null}

        <section className="rounded-xl border border-border bg-slate-50 p-4">
          <p className="text-sm font-medium text-slate-800">第二步：粘贴收到的激活码</p>
          <InputText
            className="mt-3 font-mono"
            placeholder="例如：A1B2C-D3E4F-…（支持整段粘贴，自动忽略横线和空格）"
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
            <p className="mt-3 text-sm text-red-600" role="alert" data-testid="activation-error">
              {error}
            </p>
          ) : null}
        </section>

        <p className="text-center text-xs leading-5 text-slate-400">
          激活后即可离线使用，无需网络；换电脑或重装系统后用同样方式重新领取激活码。
        </p>
      </div>
    </div>
  );
}
