import type { KeyboardEvent } from "react";

/** 页签使用方向键/Home/End切换；保留Tab进入和离开页签组的原生行为。 */
export function handleTabKeys(event: KeyboardEvent<HTMLElement>) {
  const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
  if (!keys.includes(event.key)) return;
  const tabs = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]:not(:disabled)'));
  const index = tabs.findIndex(tab => tab === document.activeElement);
  if (index < 0 || !tabs.length) return;
  event.preventDefault();
  const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
    : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
  const target = tabs[next];
  if (target) { target.focus(); target.click(); }
}
