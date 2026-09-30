import { useEffect, useRef } from "react";
import type { RefObject } from "react";

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

// 打开中的弹窗栈：Escape 和 Tab 陷阱只作用于最上层弹窗，
// 避免"确认弹窗叠在明细弹窗上时一次 Escape 关掉两层"。
const openDialogs: symbol[] = [];

/**
 * 弹窗通用行为：打开时把焦点移入弹窗、关闭时归还焦点、
 * Escape 关闭（栈顶优先）、Tab 焦点圈定在弹窗内。
 */
export function useDialogBehavior(
  open: boolean,
  onClose: () => void,
  cardRef: RefObject<HTMLElement | null>,
) {
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return undefined;
    const id = Symbol("dialog");
    openDialogs.push(id);
    const restoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = cardRef.current;
    if (node) {
      // 尊重组件内的 autoFocus（如确认弹窗聚焦"清除"按钮），焦点不在弹窗内时才移入第一个控件
      const activeInside = document.activeElement instanceof HTMLElement && node.contains(document.activeElement);
      if (!activeInside) {
        const first = node.querySelectorAll<HTMLElement>(FOCUSABLE)[0];
        if (first) first.focus();
        else node.focus();
      }
    }
    const isTop = () => openDialogs[openDialogs.length - 1] === id;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (!isTop()) return;
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !isTop()) return;
      const focusables = node?.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (!focusables || focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", handleKeyDown, true);
    return () => {
      window.removeEventListener("keydown", handleKeyDown, true);
      const index = openDialogs.indexOf(id);
      if (index >= 0) openDialogs.splice(index, 1);
      restoreFocus?.focus();
    };
  }, [cardRef, open]);
}
