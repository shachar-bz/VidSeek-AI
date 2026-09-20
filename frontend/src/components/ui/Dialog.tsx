import { useEffect, useId, useRef, type ReactNode } from "react";

import { Button } from "./Button";
import { VisuallyHidden } from "./VisuallyHidden";

export interface DialogProps {
  open: boolean;
  title: string;
  children: ReactNode;
  actions?: ReactNode;
  onClose(): void;
}

/** Native modal semantics, focus trapping, Escape support, and focus restoration. */
export function Dialog({ open, title, children, actions, onClose }: DialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    } else if (!open && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    const firstTarget = dialog?.querySelector<HTMLElement>(
      "[data-autofocus], button, input, select, textarea, [href], [tabindex]:not([tabindex='-1'])"
    );
    firstTarget?.focus();
    return () => previouslyFocused?.focus();
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      className="ui-dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="ui-dialog__surface">
        <header className="ui-dialog__header">
          <h2 id={titleId}>{title}</h2>
          <Button className="ui-dialog__close" variant="ghost" onClick={onClose}>
            <span aria-hidden="true">×</span>
            <VisuallyHidden>Close dialog</VisuallyHidden>
          </Button>
        </header>
        <div className="ui-dialog__body">{children}</div>
        {actions ? <footer className="ui-dialog__actions">{actions}</footer> : null}
      </div>
    </dialog>
  );
}
