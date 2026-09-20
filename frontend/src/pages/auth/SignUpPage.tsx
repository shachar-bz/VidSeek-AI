import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { useAccount } from "../../auth";
import { Button, Field } from "../../components/ui";
import { ROUTES } from "../../routes";
import { AuthPageFrame } from "./AuthPageFrame";
import { authFailureMessage, validateCredentials, type CredentialsErrors } from "./validation";

interface SignUpErrors extends CredentialsErrors {
  displayName?: string;
}

export function SignUpPage() {
  const account = useAccount();
  const navigate = useNavigate();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<SignUpErrors>({});
  const [requestError, setRequestError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors: SignUpErrors = validateCredentials(email, password);
    if (!displayName.trim()) nextErrors.displayName = "Enter your display name.";
    else if (displayName.trim().length > 128) {
      nextErrors.displayName = "Display name must be 128 characters or fewer.";
    }
    setErrors(nextErrors);
    setRequestError(null);
    if (Object.keys(nextErrors).length > 0) return;

    setPending(true);
    try {
      await account.signUp({
        display_name: displayName.trim(),
        email: email.trim(),
        password
      });
      navigate(ROUTES.library, { replace: true });
    } catch (error) {
      setRequestError(authFailureMessage(error, "sign-up"));
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthPageFrame
      title="Make every video findable"
      introduction="Create your account, then connect the extension to build a private, searchable video library."
      alternatePrompt="Already have an account?"
      alternateLabel="Sign in"
      alternatePath={ROUTES.signIn}
    >
      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        <div className="auth-form__heading">
          <h2>Create your account</h2>
          <p>One account keeps your website and extension in sync.</p>
        </div>

        {requestError ? (
          <div className="auth-form__error" role="alert">
            {requestError}
          </div>
        ) : null}

        <Field
          label="Display name"
          name="display_name"
          value={displayName}
          onChange={(event) => setDisplayName(event.currentTarget.value)}
          error={errors.displayName}
          autoComplete="name"
          maxLength={128}
          required
          disabled={pending}
        />
        <Field
          label="Email"
          name="email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.currentTarget.value)}
          error={errors.email}
          autoComplete="email"
          inputMode="email"
          required
          disabled={pending}
        />
        <Field
          label="Password"
          name="password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.currentTarget.value)}
          error={errors.password}
          hint="Use 8–72 characters."
          autoComplete="new-password"
          minLength={8}
          maxLength={72}
          required
          disabled={pending}
        />
        <Button type="submit" variant="primary" fullWidth pending={pending}>
          {pending ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </AuthPageFrame>
  );
}
