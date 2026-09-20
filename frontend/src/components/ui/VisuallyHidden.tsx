import type { HTMLAttributes, ReactNode } from "react";

export function VisuallyHidden({
  children,
  className = "",
  ...props
}: HTMLAttributes<HTMLSpanElement> & { children: ReactNode }) {
  return (
    <span {...props} className={["visually-hidden", className].filter(Boolean).join(" ")}>
      {children}
    </span>
  );
}
