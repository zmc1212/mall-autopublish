import type { ButtonHTMLAttributes, ReactNode } from "react";

import cn from "../../utils/classnames";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  className?: string;
  children: ReactNode;
}

export default function Button({
  variant = "primary",
  className = "",
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 text-sm font-medium transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50",
        {
          "bg-primary text-on-primary hover:bg-orange-700": variant === "primary",
          "border border-border bg-white text-foreground hover:bg-muted": variant === "secondary",
          "text-slate-600 hover:bg-muted": variant === "ghost",
          "border border-destructive/30 bg-red-50 text-destructive hover:bg-red-100":
            variant === "danger",
        },
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
