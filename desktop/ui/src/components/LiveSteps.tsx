import { ArrowDown } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";
import type { JobState } from "../types";
import cn from "../utils/classnames";

export default function LiveSteps({ job }: { job: JobState | null }) {
  const scroll = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const [following, setFollowing] = useState(true);
  const logs = job?.logs || [];
  // 日志只追加：用条数 + 末条指纹代替整段 JSON 序列化来判断变化
  const lastEntry = logs[logs.length - 1];
  const signature = `${logs.length}|${lastEntry?.time ?? ""}|${lastEntry?.message ?? ""}`;
  const source = `${job?.workspace_path}|${job?.workbook_path}`;
  useLayoutEffect(() => { follow.current = true; setFollowing(true); }, [source]);
  useLayoutEffect(() => {
    if (follow.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [signature, source]);
  useLayoutEffect(() => {
    const node = scroll.current;
    if (!node) return;
    const observer = new ResizeObserver(() => { if (follow.current) node.scrollTop = node.scrollHeight; });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const running = job?.status === "running";
  return (
    <aside className="relative flex min-h-0 min-w-0 flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-slate-100">
      <header className="flex shrink-0 items-center justify-between border-b border-white/10 px-4 py-3">
        <h3 className="text-sm font-medium">实时步骤</h3>
        <span className="flex items-center gap-2 text-xs text-slate-400"><span className={cn("h-1.5 w-1.5 rounded-full", running ? "bg-emerald-400 motion-safe:animate-pulse" : "bg-slate-500")} />{running ? "进行中" : job?.status === "stopping" ? "正在暂停" : "待命"}</span>
      </header>
      <div ref={scroll} className="live-steps-scroll min-h-0 flex-1 overflow-y-auto px-4 py-3 text-sm leading-6" role="log" aria-label="实时执行日志" aria-live="off" tabIndex={0}
        onScroll={() => {
          const node = scroll.current!;
          const atBottom = node.scrollHeight - node.clientHeight - node.scrollTop < 36;
          follow.current = atBottom;
          setFollowing(atBottom);
        }}>
        {!logs.length ? <div className="py-5 text-slate-400"><p className="text-slate-200">等待开始入库</p><p className="mt-2 text-xs leading-6">执行后，这里会实时展示填写、入库和图片核验进度。</p></div> : logs.map((entry, index) => (
          <div key={`${entry.time}-${index}`} className={cn("live-step border-l py-2 pl-3", index === logs.length - 1 ? "border-emerald-400 bg-white/[0.03]" : "border-slate-800")}>
            <div className="flex gap-2 text-[11px] leading-4 text-slate-500"><time>{entry.time}</time>{entry.level === "error" ? <span className="text-red-300">异常</span> : entry.level === "warn" ? <span className="text-amber-200">注意</span> : index === logs.length - 1 ? <span className="text-emerald-400">最新</span> : null}</div>
            <p className={cn("mt-1 break-words", entry.level === "error" ? "text-red-300" : entry.level === "warn" ? "text-amber-200" : "text-slate-200")}>{entry.message}</p>
          </div>
        ))}
      </div>
      {!following && <button className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1 whitespace-nowrap rounded-full border border-slate-600 bg-slate-800 px-3 py-2 text-xs shadow-lg" onClick={() => {
        follow.current = true;
        setFollowing(true);
        if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
      }}><ArrowDown className="h-3 w-3" />回到最新步骤</button>}
    </aside>
  );
}
