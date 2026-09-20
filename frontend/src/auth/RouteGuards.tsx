import type { ReactNode } from "react";
import { Navigate, Outlet } from "react-router-dom";

import { ROUTES } from "../routes";
import { ErrorState, LoadingState } from "../components/ui";
import { useAccount } from "./AccountContext";

function PendingAccount() {
  const account = useAccount();
  if (account.status !== "loading") return null;

  if (account.initializationError) {
    return (
      <main className="app-centered-state">
        <ErrorState
          title="Unable to check your session"
          message={account.initializationError}
          actionLabel="Try again"
          onAction={account.retryInitialization}
        />
      </main>
    );
  }

  return (
    <main className="app-centered-state">
      <LoadingState label="Checking your session…" />
    </main>
  );
}

/** Protect a route subtree. It renders an Outlet when no child element is supplied. */
export function ProtectedRoute({ children }: { children?: ReactNode }) {
  const account = useAccount();
  if (account.status === "loading") return <PendingAccount />;
  if (account.status === "unauthenticated") {
    return <Navigate to={ROUTES.signIn} replace />;
  }
  return children ?? <Outlet />;
}

/** Keep signed-in accounts out of the sign-in and sign-up pages. */
export function PublicOnlyRoute({ children }: { children?: ReactNode }) {
  const account = useAccount();
  if (account.status === "loading") return <PendingAccount />;
  if (account.status === "authenticated") {
    return <Navigate to={ROUTES.library} replace />;
  }
  return children ?? <Outlet />;
}
