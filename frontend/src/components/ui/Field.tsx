import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from "react";

export interface FieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "id"> {
  id?: string;
  label: string;
  error?: string;
  hint?: ReactNode;
}

export const Field = forwardRef<HTMLInputElement, FieldProps>(function Field(
  { id: providedId, label, error, hint, className = "", required, ...props },
  ref
) {
  const generatedId = useId();
  const id = providedId ?? generatedId;
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;
  const describedBy = [hint ? hintId : "", error ? errorId : ""].filter(Boolean).join(" ");

  return (
    <div className="ui-field">
      <label className="ui-field__label" htmlFor={id}>
        {label}
        {required ? <span aria-hidden="true"> *</span> : null}
      </label>
      <input
        {...props}
        ref={ref}
        id={id}
        required={required}
        className={["ui-field__input", className].filter(Boolean).join(" ")}
        aria-invalid={Boolean(error) || undefined}
        aria-describedby={describedBy || undefined}
      />
      {hint ? (
        <div className="ui-field__hint" id={hintId}>
          {hint}
        </div>
      ) : null}
      {error ? (
        <div className="ui-field__error" id={errorId}>
          {error}
        </div>
      ) : null}
    </div>
  );
});
