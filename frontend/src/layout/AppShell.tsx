import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import brandIcon from "../assets/vidseek-icon.png";
import { getLibrary, subscribeToLibraryEvents } from "../api/library";
import type { LibraryProgressEvent, LibraryVideo, ReadinessStage } from "../api/types";
import { useAccount } from "../auth";
import { Button, ErrorState, LoadingState } from "../components/ui";
import { ROUTES } from "../routes";

interface LiveNotification {
  id: string;
  title: string;
  message: string;
  createdAt: Date;
  unread: boolean;
}

const PROCESSING_STAGES = new Set<ReadinessStage>([
  "downloading",
  "transcribing",
  "understanding"
]);

function accountInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "VS";
  const first = parts.at(0) ?? "";
  if (parts.length === 1) return first.slice(0, 2).toLocaleUpperCase();
  return `${first[0] ?? ""}${parts.at(-1)?.[0] ?? ""}`.toLocaleUpperCase();
}

function completionMessage(event: LibraryProgressEvent): string {
  if (event.stage === "failed") return "Processing failed";
  if (event.stage === "partial") return "Processing finished with limited timing";
  return "Finished processing and is ready to search";
}

function titleForJob(videos: LibraryVideo[], jobId: string): string {
  return videos.find((video) => video.job_id === jobId)?.title ?? "Your video";
}

function NotificationBell() {
  const [notifications, setNotifications] = useState<LiveNotification[]>([]);
  const [open, setOpen] = useState(false);
  const activeJobs = useRef(new Map<string, string>());
  const unreadCount = notifications.filter((notification) => notification.unread).length;

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const baseline = await getLibrary({ limit: 200 }, controller.signal);
        for (const video of baseline.videos) {
          if (video.job_id && PROCESSING_STAGES.has(video.stage)) {
            activeJobs.current.set(video.job_id, video.title);
          }
        }

        for await (const event of subscribeToLibraryEvents(controller.signal)) {
          if (controller.signal.aborted) return;
          if (PROCESSING_STAGES.has(event.stage)) {
            activeJobs.current.set(
              event.job_id,
              titleForJob(baseline.videos, event.job_id)
            );
            continue;
          }

          const title = activeJobs.current.get(event.job_id);
          if (!title) continue;
          activeJobs.current.delete(event.job_id);
          setNotifications((current) => [
            {
              id: `${event.job_id}-${Date.now()}`,
              title,
              message: completionMessage(event),
              createdAt: new Date(),
              unread: true
            },
            ...current
          ]);
        }
      } catch {
        // The bell is intentionally best-effort and current-session only.
      }
    })();
    return () => controller.abort();
  }, []);

  function toggleNotifications() {
    setOpen((current) => !current);
    setNotifications((current) =>
      current.map((notification) => ({ ...notification, unread: false }))
    );
  }

  return (
    <div className="notification-center">
      <button
        className="notification-center__button"
        type="button"
        aria-label={unreadCount > 0 ? `Notifications, ${unreadCount} unread` : "Notifications"}
        aria-expanded={open}
        onClick={toggleNotifications}
      >
        <BellIcon />
        {unreadCount > 0 ? <span className="notification-center__badge">{unreadCount}</span> : null}
      </button>
      {open ? (
        <section className="notification-center__popover" aria-label="Processing notifications">
          <header>
            <strong>Notifications</strong>
            {notifications.length > 0 ? (
              <button type="button" onClick={() => setNotifications([])}>Clear</button>
            ) : null}
          </header>
          {notifications.length === 0 ? (
            <p>No new processing updates.</p>
          ) : (
            <ol>
              {notifications.map((notification) => (
                <li key={notification.id}>
                  <span className="notification-center__success" aria-hidden="true">✓</span>
                  <div>
                    <strong>{notification.title}</strong>
                    <p>{notification.message}</p>
                    <time>{notification.createdAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </section>
      ) : null}
      <span className="visually-hidden" aria-live="polite">
        {unreadCount > 0 ? `${notifications[0]?.title} finished processing` : ""}
      </span>
    </div>
  );
}

/** Responsive frame shared by every signed-in route. */
export function AppShell({ children }: { children?: ReactNode }) {
  const account = useAccount();
  const location = useLocation();
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
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="app-shell__header">
        <div className="app-shell__header-inner">
          <NavLink className="app-shell__brand" to={ROUTES.library} aria-label="VidSeek AI library">
            <img src={brandIcon} alt="" />
            <span>VidSeek AI</span>
          </NavLink>

          <nav className="app-shell__nav" aria-label="Primary navigation">
            <NavLink
              to={ROUTES.library}
              end
              className={({ isActive }) =>
                ["app-shell__nav-link", isActive ? "app-shell__nav-link--active" : ""]
                  .filter(Boolean)
                  .join(" ")
              }
            >
              Library
            </NavLink>
          </nav>

          <div className="app-shell__account">
            {location.pathname === ROUTES.account ? null : <NotificationBell />}
            <details className="account-menu">
              <summary aria-label={`Open account menu for ${accountLabel}`}>
                {accountInitials(accountLabel)}
              </summary>
              <div className="account-menu__popover">
                <strong>{accountLabel}</strong>
                <NavLink to={ROUTES.account}>Account settings</NavLink>
                <NavLink to={ROUTES.setup}>Extension setup</NavLink>
                <Button variant="ghost" pending={signingOut} onClick={handleSignOut}>
                  {signingOut ? "Signing out…" : "Sign out"}
                </Button>
              </div>
            </details>
          </div>
        </div>
      </header>

      <main className="app-shell__main" id="main-content" tabIndex={-1}>
        {children ?? <Outlet />}
      </main>
    </div>
  );
}

function BellIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none">
      <path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9Z" />
      <path d="M10 21h4" />
    </svg>
  );
}
