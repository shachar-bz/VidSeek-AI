// The route table. Every page the website has is declared here and nowhere else.
//
// Auth routes use their real pages. The remaining elements are placeholders: each names the
// page that belongs at that path and the section of frontend/WEBSITE_FUNCTIONALITY.md that
// specifies it. Adding a *path* is not expected because the set of pages is closed by the
// specification's "Out of scope" list.
//
// Nothing here is styled. The visual system is specified in frontend/DESIGN.md and is the
// job of whoever builds these pages.
//
// Only /sign-in and /sign-up are reachable without a session (`PUBLIC_ROUTES` in routes.ts).

import { Navigate, Route, Routes } from "react-router-dom";

import { ProtectedRoute, PublicOnlyRoute } from "./auth";
import { SignInPage, SignUpPage } from "./pages/auth";
import { ROUTES } from "./routes";

function Placeholder({ title, specification }: { title: string; specification: string }) {
  return (
    <main>
      <h1>{title}</h1>
      <p>Not built yet — see {specification} of WEBSITE_FUNCTIONALITY.md.</p>
    </main>
  );
}

export function App() {
  return (
    <Routes>
      <Route element={<PublicOnlyRoute />}>
        <Route path={ROUTES.signIn} element={<SignInPage />} />
        <Route path={ROUTES.signUp} element={<SignUpPage />} />
      </Route>
      <Route element={<ProtectedRoute />}>
        <Route path={ROUTES.library} element={<Placeholder title="Library" specification="§3" />} />
        <Route path={ROUTES.video} element={<Placeholder title="Video" specification="§4" />} />
        <Route path={ROUTES.account} element={<Placeholder title="Account" specification="§5" />} />
        <Route path={ROUTES.setup} element={<Placeholder title="Setup" specification="§6" />} />
      </Route>
      {/* Anything else is a mistyped URL rather than a page; the library is the home. */}
      <Route path="*" element={<Navigate to={ROUTES.library} replace />} />
    </Routes>
  );
}
