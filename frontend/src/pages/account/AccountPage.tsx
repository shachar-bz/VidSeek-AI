import { useEffect, useState, type ChangeEventHandler, type FormEvent } from "react";

import { changePassword, updateAccount } from "../../api/account";
import { useAccount } from "../../auth";
import { Button, Field, LoadingState, Panel } from "../../components/ui";
import { featureFailureMessage } from "../shared";

interface AccountPasswordFieldProps {
  label: string;
  value: string;
  placeholder?: string;
  autoComplete: "current-password" | "new-password";
  onChange: ChangeEventHandler<HTMLInputElement>;
}

function AccountPasswordField({ label, value, placeholder, autoComplete, onChange }: AccountPasswordFieldProps) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="account-password-field">
      <Field
        label={label}
        type={visible ? "text" : "password"}
        autoComplete={autoComplete}
        required
        minLength={autoComplete === "new-password" ? 8 : undefined}
        maxLength={72}
        value={value}
        placeholder={placeholder}
        onChange={onChange}
      />
      <button
        className="account-password-field__toggle"
        type="button"
        aria-label={`${visible ? "Hide" : "Show"} ${label.toLocaleLowerCase()}`}
        aria-pressed={visible}
        onClick={() => setVisible((current) => !current)}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M2.5 12s3.5-5 9.5-5 9.5 5 9.5 5-3.5 5-9.5 5-9.5-5-9.5-5Z" />
          <circle cx="12" cy="12" r="2.5" />
        </svg>
      </button>
    </div>
  );
}

export function AccountPage() {
  const account = useAccount();
  const user = account.status === "authenticated" ? account.user : null;
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [profilePending, setProfilePending] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileSuccess, setProfileSuccess] = useState<string | null>(null);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordPending, setPasswordPending] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  useEffect(() => {
    setDisplayName(user?.display_name ?? "");
  }, [user?.display_name]);

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    const normalized = displayName.trim();
    if (!normalized) {
      setProfileError("Enter a display name.");
      return;
    }
    if (normalized.length > 128) {
      setProfileError("Display name must be 128 characters or fewer.");
      return;
    }
    setProfilePending(true);
    setProfileError(null);
    setProfileSuccess(null);
    try {
      const updated = await updateAccount({ display_name: normalized });
      account.synchronizeUser(updated);
      setDisplayName(updated.display_name ?? "");
      setProfileSuccess("Display name updated.");
    } catch (caught) {
      setProfileError(featureFailureMessage(caught, "We couldn’t update your display name."));
    } finally {
      setProfilePending(false);
    }
  }

  async function savePassword(event: FormEvent) {
    event.preventDefault();
    if (!currentPassword) {
      setPasswordError("Enter your current password.");
      return;
    }
    if (currentPassword.length > 72) {
      setPasswordError("Current password must be 72 characters or fewer.");
      return;
    }
    if (newPassword.length < 8 || newPassword.length > 72) {
      setPasswordError("New password must be between 8 and 72 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError("New passwords do not match.");
      return;
    }
    setPasswordPending(true);
    setPasswordError(null);
    try {
      await changePassword({ current_password: currentPassword, new_password: newPassword });
      await account.signOut();
    } catch (caught) {
      setPasswordError(featureFailureMessage(caught, "We couldn’t change your password."));
      setPasswordPending(false);
    }
  }

  if (!user) return <LoadingState label="Loading your account…" />;

  return (
    <div className="account-page">
      <header className="account-page__heading">
        <h1>Account</h1>
        <p>Manage your name and password.</p>
      </header>

      <Panel className="account-card">
        <div className="account-card__heading">
          <h2>Display name</h2>
          <p>This is how your name appears in VidSeek AI.</p>
        </div>
        <form className="account-form" onSubmit={saveProfile}>
          <Field
            label="Display name"
            required
            maxLength={128}
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            error={profileError ?? undefined}
          />
          {profileSuccess ? <p className="form-success" role="status">{profileSuccess}</p> : null}
          <Button className="account-form__submit" pending={profilePending} type="submit">
            {profilePending ? "Saving…" : "Save name"}
          </Button>
        </form>
      </Panel>

      <Panel className="account-card">
        <div className="account-card__heading">
          <h2>Change password</h2>
          <p>Enter your current password before choosing a new one.</p>
        </div>
        <form className="account-form account-form--password" onSubmit={savePassword}>
          <AccountPasswordField
            label="Current password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
          />
          <AccountPasswordField
            label="New password"
            autoComplete="new-password"
            value={newPassword}
            placeholder="At least 8 characters"
            onChange={(event) => setNewPassword(event.target.value)}
          />
          <AccountPasswordField
            label="Confirm new password"
            autoComplete="new-password"
            value={confirmPassword}
            placeholder="Repeat new password"
            onChange={(event) => setConfirmPassword(event.target.value)}
          />
          {passwordError ? <p className="form-error" role="alert">{passwordError}</p> : null}
          <Button className="account-form__submit" pending={passwordPending} type="submit">
            {passwordPending ? "Changing…" : "Change password"}
          </Button>
        </form>
      </Panel>
    </div>
  );
}
