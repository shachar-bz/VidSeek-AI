import { useState, type ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { useAccount } from "../auth";
import { Button, ErrorState, LoadingState } from "../components/ui";
import { ROUTES } from "../routes";

const NAVIGATION = [
  { label: "Library", to: ROUTES.library, end: true },
  { label: "Setup", to: ROUTES.setup, end: false },
  { label: "Account", to: ROUTES.account, end: false }
] as const;

function accountInitial(name: string): string {
  return name.trim().charAt(0).toLocaleUpperCase() || "V";
}

/** Responsive frame shared by every signed-in route. */
export function AppShell({ children }: { children?: ReactNode }) {
  const account = useAccount();
  const [signingOut, setSigningOut] = useState(false);

  if (account.status === "loading") {
    return (
      <main className="app-centered-state">
        {account.initializationError ? (
          <ErrorState
            title="Unable to check your session"
            message={account.initializationError}
            actionLabel="Try again"
            onAction={account.retryInitialization}
          />
        ) : (
          <LoadingState label="Loading your workspace…" />
        )}
      </main>
    );
  }

  if (account.status === "unauthenticated") {
    return (
      <main className="app-centered-state">
        <LoadingState label="Returning to sign in…" />
      </main>
    );
  }

  const accountLabel = account.user.display_name?.trim() || account.user.email;

  async function handleSignOut() {
    setSigningOut(true);
    await account.signOut();
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="app-shell__header">
        <div className="app-shell__header-inner">
          <NavLink className="app-shell__brand" to={ROUTES.library} aria-label="VidSeek library">
            <span className="brand-mark" aria-hidden="true" />
            <span>VidSeek</span>
          </NavLink>

          <nav className="app-shell__nav" aria-label="Primary navigation">
            {NAVIGATION.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  ["app-shell__nav-link", isActive ? "app-shell__nav-link--active" : ""]
                    .filter(Boolean)
                    .join(" ")
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="app-shell__account">
            <span className="app-shell__avatar" aria-hidden="true">
              {accountInitial(accountLabel)}
            </span>
            <span className="app-shell__account-name" title={accountLabel}>
              {accountLabel}
            </span>
            <Button variant="ghost" pending={signingOut} onClick={handleSignOut}>
              {signingOut ? "Signing out…" : "Sign out"}
            </Button>
          </div>
        </div>
      </header>

      <main className="app-shell__main" id="main-content" tabIndex={-1}>
        {children ?? <Outlet />}
      </main>
    </div>
  );
}
