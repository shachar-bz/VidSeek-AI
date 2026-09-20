import { useState, type ChangeEventHandler, type ReactNode } from "react";

import { Field } from "../../components/ui";

export function PasswordField({
  value,
  onChange,
  error,
  hint,
  autoComplete,
  disabled
}: {
  value: string;
  onChange: ChangeEventHandler<HTMLInputElement>;
  error?: string;
  hint?: ReactNode;
  autoComplete: "current-password" | "new-password";
  disabled?: boolean;
}) {
  const [isVisible, setIsVisible] = useState(false);

  return (
    <div className="auth-password-field">
      <Field
        label="Password"
        name="password"
        type={isVisible ? "text" : "password"}
        value={value}
        onChange={onChange}
        error={error}
        hint={hint}
        autoComplete={autoComplete}
        minLength={8}
        maxLength={72}
        required
        disabled={disabled}
      />
      <button
        className="auth-password-field__toggle"
        type="button"
        aria-label={isVisible ? "Hide password" : "Show password"}
        aria-pressed={isVisible}
        disabled={disabled}
        onClick={() => setIsVisible((visible) => !visible)}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M2.5 12s3.5-5 9.5-5 9.5 5 9.5 5-3.5 5-9.5 5-9.5-5-9.5-5Z" />
          <circle cx="12" cy="12" r="2.5" />
        </svg>
      </button>
    </div>
  );
}
