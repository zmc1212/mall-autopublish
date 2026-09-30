/** 把秒数格式化为可读时长；无有效耗时时返回 —。 */
export default function formatDuration(seconds?: number | null): string {
  if (!seconds || seconds <= 0 || !Number.isFinite(seconds)) return "—";
  const total = Math.round(seconds);
  if (total < 60) return `${total}秒`;
  if (total < 3600) return `${Math.floor(total / 60)}分${String(total % 60).padStart(2, "0")}秒`;
  return `${Math.floor(total / 3600)}小时${String(Math.floor((total % 3600) / 60)).padStart(2, "0")}分`;
}
