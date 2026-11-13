import type { JobState } from "../types";
import cn from "../utils/classnames";

function displayTime(value: string) {
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) {
    const date = new Date(value);
    if (!Number.isNaN(date.getTime())) return date.toLocaleTimeString("zh-CN", { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hour12: false });
  }
  return value.match(/\d{2}:\d{2}/)?.[0] || value;
}

export default function LiveSteps({ job, onAllLogs }: { job: JobState | null; onAllLogs?: () => void }) {
  const logs = job?.logs || [];
  // 侧栏只展示最近动态，完整记录通过“查看全部”进入排障日志。
  const recentLogs = onAllLogs ? logs.slice(-4) : logs;
  const running = job?.status === "running" || job?.status === "stopping";
  return (
    <section className="live-events inspector-section" aria-label="最近动态">
      <div className="inspector-title">
        <h3>最近动态</h3>
        {onAllLogs ? <button onClick={onAllLogs}>查看全部{logs.length > recentLogs.length ? `（${logs.length}）` : ""}</button> : <span>{running ? "实时更新" : logs.length ? `${logs.length} 条记录` : "暂无记录"}</span>}
      </div>
      <div role="log" aria-label="最近动态" aria-live="off">
        {!recentLogs.length ? (
          <div className="inspector-clear">执行后，这里会显示最新的入库和图片核验进度。</div>
        ) : recentLogs.map((entry, index) => (
          <div key={`${entry.time}-${index}`} className={cn("live-event", index === recentLogs.length - 1 && "font-medium")} data-level={entry.level}>
            <time title={entry.time}>{displayTime(entry.time)}</time>
            <p>
              {entry.level === "error" ? <span className="mr-1.5 text-[10px]">异常</span> : entry.level === "warn" ? <span className="mr-1.5 text-[10px]">注意</span> : null}
              {entry.message}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
