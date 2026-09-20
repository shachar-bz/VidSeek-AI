import type { ReactNode } from "react";

export type StatusTone = "neutral" | "active" | "positive" | "caution" | "critical";

export function StatusBadge({ children, tone = "neutral" }: { children: ReactNode; tone?: StatusTone }) {
  return <span className={`ui-status ui-status--${tone}`}>{children}</span>;
}
