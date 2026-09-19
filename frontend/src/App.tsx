// The route table. Every page the website has is declared here and nowhere else.
//
// The elements below are placeholders: each names the page that belongs at that path and
// the section of frontend/WEBSITE_FUNCTIONALITY.md that specifies it. Replacing one with a
// real page is the expected next step; adding a *path* is not, because the set of pages is
// closed by the specification's "Out of scope" list.
//
// Nothing here is styled. The visual system is specified in frontend/DESIGN.md and is the
// job of whoever builds these pages.
//
// Signed-out access is not enforced here yet. Only /sign-in and /sign-up are reachable
// without a session (`PUBLIC_ROUTES` in routes.ts); the guard that redirects everything
// else belongs with whatever holds the signed-in account.

import { Navigate, Route, Routes } from "react-router-dom";

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
      <Route path={ROUTES.signIn} element={<Placeholder title="Sign in" specification="§2" />} />
      <Route path={ROUTES.signUp} element={<Placeholder title="Sign up" specification="§2" />} />
      <Route path={ROUTES.library} element={<Placeholder title="Library" specification="§3" />} />
      <Route path={ROUTES.video} element={<Placeholder title="Video" specification="§4" />} />
      <Route path={ROUTES.account} element={<Placeholder title="Account" specification="§5" />} />
      <Route path={ROUTES.setup} element={<Placeholder title="Setup" specification="§6" />} />
      {/* Anything else is a mistyped URL rather than a page; the library is the home. */}
      <Route path="*" element={<Navigate to={ROUTES.library} replace />} />
    </Routes>
  );
}
