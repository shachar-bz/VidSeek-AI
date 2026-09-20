import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { useAccount } from "../../auth";
import { Button, Field } from "../../components/ui";
import { ROUTES } from "../../routes";
import { AuthPageFrame } from "./AuthPageFrame";
import { PasswordField } from "./PasswordField";
import { authFailureMessage, validateCredentials, type CredentialsErrors } from "./validation";

export function SignInPage() {
  const account = useAccount();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<CredentialsErrors>({});
  const [requestError, setRequestError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors = validateCredentials(email, password);
    setErrors(nextErrors);
    setRequestError(null);
    if (Object.keys(nextErrors).length > 0) return;

    setPending(true);
    try {
      await account.signIn({ email: email.trim(), password });
      navigate(ROUTES.library, { replace: true });
    } catch (error) {
      setRequestError(authFailureMessage(error, "sign-in"));
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthPageFrame
      mode="sign-in"
      alternatePrompt="New to VidSeek?"
      alternateLabel="Create an account"
      alternatePath={ROUTES.signUp}
    >
      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        {requestError ? (
          <div className="auth-form__error" role="alert">
            {requestError}
          </div>
        ) : null}

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
        <PasswordField
          value={password}
          onChange={(event) => setPassword(event.currentTarget.value)}
          error={errors.password}
          autoComplete="current-password"
          disabled={pending}
        />
        <Button type="submit" variant="primary" fullWidth pending={pending}>
          {pending ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthPageFrame>
  );
}
