/**
 * Stable Wave 1 surface for route composition and later feature work.
 *
 * Prompt 4 should import `styles/index.css` once at the browser entry, then compose
 * AccountProvider, PublicOnlyRoute, ProtectedRoute, and AppShell around the closed route
 * table. API calls made through api/client automatically publish protected-request 401s to
 * AccountProvider. A nonstandard API transport can pass its error to `reportApiError` from
 * `useAccount` to use the same local sign-out path.
 */
export * from "./auth";
export * from "./components/ui";
export * from "./layout";
export * from "./pages/auth";
