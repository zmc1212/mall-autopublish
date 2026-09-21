import type { InputHTMLAttributes } from "react";

import cn from "../../utils/classnames";

interface InputTextProps extends InputHTMLAttributes<HTMLInputElement> {
  className?: string;
}

export default function InputText({ className = "", ...props }: InputTextProps) {
  return (
    <input
      className={cn(
        "min-h-11 w-full rounded-lg border border-border bg-white px-3 text-sm text-foreground outline-none transition-colors duration-150 placeholder:text-slate-400 focus:border-primary",
        className,
      )}
      {...props}
    />
  );
}
