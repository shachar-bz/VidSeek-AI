import type { HTMLAttributes, ReactNode } from "react";

export interface PanelProps extends HTMLAttributes<HTMLElement> {
  as?: "article" | "div" | "section";
  children: ReactNode;
}

export function Panel({ as: Element = "section", className = "", children, ...props }: PanelProps) {
  return (
    <Element {...props} className={["ui-panel", className].filter(Boolean).join(" ")}>
      {children}
    </Element>
  );
}
