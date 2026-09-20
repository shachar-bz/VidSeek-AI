import type { ReactNode } from "react";

export function EmptyState({
  title,
  description,
  action
}: {
  title: string;
  description: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="ui-empty-state" aria-labelledby="empty-state-title">
      <div className="ui-empty-state__mark" aria-hidden="true" />
      <h2 id="empty-state-title">{title}</h2>
      <div className="ui-empty-state__description">{description}</div>
      {action ? <div className="ui-empty-state__action">{action}</div> : null}
    </section>
  );
}
