import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import cn from "../utils/classnames";

interface ProductItemIdProps {
  value?: string;
  className?: string;
}

async function copyText(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }

  const input = document.createElement("textarea");
  input.value = value;
  input.style.position = "fixed";
  input.style.opacity = "0";
  document.body.appendChild(input);
  input.select();
  const copied = document.execCommand("copy");
  input.remove();
  if (!copied) throw new Error("复制失败");
}

export default function ProductItemId({ value = "", className = "" }: ProductItemIdProps) {
  const [copied, setCopied] = useState(false);
  const resetTimer = useRef<number | null>(null);

  useEffect(() => () => {
    if (resetTimer.current !== null) window.clearTimeout(resetTimer.current);
  }, []);

  if (!value) return <span className={cn("text-slate-400", className)}>—</span>;

  const handleCopy = async () => {
    try {
      await copyText(value);
      setCopied(true);
      if (resetTimer.current !== null) window.clearTimeout(resetTimer.current);
      resetTimer.current = window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className={cn("flex min-w-0 items-center gap-1.5", className)}>
      <span className="truncate font-mono text-xs" title={value}>{value}</span>
      <button
        type="button"
        className={cn(
          "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900",
          { "text-emerald-600": copied },
        )}
        onClick={handleCopy}
        title={copied ? "已复制" : "复制商品ID"}
        aria-label={copied ? "商品ID已复制" : "复制商品ID"}
      >
        {copied ? <Check className="h-4 w-4" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}
      </button>
    </div>
  );
}
