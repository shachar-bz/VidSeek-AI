import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import {
  changePassword,
  deleteAccount,
  getSessions,
  revokeAllSessions,
  revokeSession,
  updateAccount
} from "../../api/account";
import type { SessionSummary } from "../../api/types";
import { useAccount } from "../../auth";
import { Button, Dialog, ErrorState, Field, LoadingState, Panel, StatusBadge } from "../../components/ui";
import { ROUTES } from "../../routes";
import { featureFailureMessage } from "../shared";

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(date);
}

function surfaceLabel(surface: SessionSummary["surface"]): string {
  return surface === "website" ? "Website" : "Chrome extension";
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

  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [revokingAll, setRevokingAll] = useState(false);

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deletePending, setDeletePending] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    setDisplayName(user?.display_name ?? "");
  }, [user?.display_name]);

  useEffect(() => {
    const controller = new AbortController();
    setSessionsLoading(true);
    setSessionsError(null);
    getSessions(controller.signal)
      .then((response) => setSessions(response.sessions))
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setSessionsError(featureFailureMessage(caught, "We couldn’t load your sessions."));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setSessionsLoading(false);
      });
    return () => controller.abort();
  }, []);

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
      // Password changes revoke every session on both surfaces, including this one.
      await account.signOut();
    } catch (caught) {
      setPasswordError(featureFailureMessage(caught, "We couldn’t change your password."));
      setPasswordPending(false);
    }
  }

  async function removeSession(session: SessionSummary) {
    setRevokingId(session.session_id);
    setSessionsError(null);
    try {
      await revokeSession(session.session_id);
      if (session.current) await account.signOut();
      else setSessions((current) => current.filter((item) => item.session_id !== session.session_id));
    } catch (caught) {
      setSessionsError(featureFailureMessage(caught, "We couldn’t revoke that session."));
    } finally {
      setRevokingId(null);
    }
  }

  async function signOutEverywhere() {
    setRevokingAll(true);
    setSessionsError(null);
    try {
      await revokeAllSessions();
      await account.signOut();
    } catch (caught) {
      setSessionsError(featureFailureMessage(caught, "We couldn’t sign out every session."));
      setRevokingAll(false);
    }
  }

  async function confirmDelete(event: FormEvent) {
    event.preventDefault();
    if (!deletePassword) {
      setDeleteError("Enter your password to confirm deletion.");
      return;
    }
    if (deletePassword.length > 72) {
      setDeleteError("Password must be 72 characters or fewer.");
      return;
    }
    setDeletePending(true);
    setDeleteError(null);
    try {
      await deleteAccount({ password: deletePassword });
      await account.signOut();
    } catch (caught) {
      setDeleteError(featureFailureMessage(caught, "We couldn’t delete your account."));
      setDeletePending(false);
    }
  }

  if (!user) return <LoadingState label="Loading your account…" />;

  return (
    <div className="feature-page account-page">
      <header className="feature-page__heading">
        <div>
          <p className="eyebrow">Preferences & access</p>
          <h1>Account</h1>
          <p>Manage your identity, password, and every place signed into VidSeek.</p>
        </div>
        <Link className="button-link button-link--ghost" to={ROUTES.setup}>Open setup guide</Link>
      </header>

      <div className="account-grid">
        <Panel className="account-card">
          <div className="section-heading"><div><h2>Profile</h2><p>Your email is the login shared by the website and extension.</p></div></div>
          <form className="stack-form" onSubmit={saveProfile}>
            <Field label="Email" value={user.email} disabled />
            <Field label="Display name" required maxLength={128} value={displayName} onChange={(event) => setDisplayName(event.target.value)} error={profileError ?? undefined} />
            {profileSuccess ? <p className="form-success" role="status">{profileSuccess}</p> : null}
            <Button variant="primary" pending={profilePending} type="submit">{profilePending ? "Saving…" : "Save profile"}</Button>
          </form>
        </Panel>

        <Panel className="account-card">
          <div className="section-heading"><div><h2>Change password</h2><p>Changing it signs out every website and extension session.</p></div></div>
          <form className="stack-form" onSubmit={savePassword}>
            <Field label="Current password" type="password" autoComplete="current-password" required maxLength={72} value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} />
            <Field label="New password" type="password" autoComplete="new-password" required minLength={8} maxLength={72} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} hint="8–72 characters" />
            <Field label="Confirm new password" type="password" autoComplete="new-password" required minLength={8} maxLength={72} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} />
            {passwordError ? <p className="form-error" role="alert">{passwordError}</p> : null}
            <Button pending={passwordPending} type="submit">{passwordPending ? "Changing…" : "Change password"}</Button>
          </form>
        </Panel>
      </div>

      <Panel className="sessions-panel">
        <div className="section-heading section-heading--split">
          <div><h2>Sessions</h2><p>Website and Chrome extension sessions signed into this account.</p></div>
          <Button className="danger-button" variant="ghost" pending={revokingAll} onClick={signOutEverywhere}>{revokingAll ? "Signing out…" : "Sign out everywhere"}</Button>
        </div>
        {sessionsError ? <ErrorState title="Session action failed" message={sessionsError} /> : null}
        {sessionsLoading ? <LoadingState label="Loading sessions…" /> : sessions.length === 0 ? <p className="muted-text">No active sessions.</p> : (
          <ul className="session-list">
            {sessions.map((session) => (
              <li key={session.session_id}>
                <div className="session-list__identity"><span className={`surface-icon surface-icon--${session.surface}`} aria-hidden="true" /><div><div className="session-list__title">{surfaceLabel(session.surface)} {session.current ? <StatusBadge tone="active">Current session</StatusBadge> : null}</div><p>Last used {formatDateTime(session.last_used_at)}</p><p className="session-list__secondary">Started {formatDateTime(session.created_at)} · Expires {formatDateTime(session.expires_at)}</p></div></div>
                <Button variant="ghost" pending={revokingId === session.session_id} onClick={() => removeSession(session)}>{revokingId === session.session_id ? "Revoking…" : session.current ? "Revoke and sign out" : "Revoke"}</Button>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel className="danger-zone">
        <div><p className="eyebrow">Danger zone</p><h2>Delete account</h2><p>This is permanent and cannot be undone.</p></div>
        <Button className="danger-button" variant="ghost" onClick={() => { setDeletePassword(""); setDeleteError(null); setDeleteOpen(true); }}>Delete account</Button>
      </Panel>

      <Dialog open={deleteOpen} title="Permanently delete your account?" onClose={() => setDeleteOpen(false)} actions={<><Button variant="ghost" onClick={() => setDeleteOpen(false)}>Cancel</Button><Button className="danger-button" pending={deletePending} type="submit" form="delete-account-form">{deletePending ? "Deleting…" : "Delete my account"}</Button></>}>
        <form className="stack-form" id="delete-account-form" onSubmit={confirmDelete}>
          <p>Deleting your account removes your user, private library links, conversations, and pins. Shared video data and artifacts remain available to other users.</p>
          <Field label="Password" type="password" autoComplete="current-password" required maxLength={72} value={deletePassword} onChange={(event) => setDeletePassword(event.target.value)} error={deleteError ?? undefined} hint="Enter your password to confirm this irreversible action." />
        </form>
      </Dialog>
    </div>
  );
}
