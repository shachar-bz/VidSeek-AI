import { Navigate, Route, Routes } from "react-router-dom";

import { ProtectedRoute, PublicOnlyRoute } from "./auth";
import { AppShell } from "./layout";
import { AccountPage, LibraryPage, SetupPage, VideoPage } from "./pages";
import { SignInPage, SignUpPage } from "./pages/auth";
import { ROUTES } from "./routes";

export function App() {
  return (
    <Routes>
      <Route element={<PublicOnlyRoute />}>
        <Route path={ROUTES.signIn} element={<SignInPage />} />
        <Route path={ROUTES.signUp} element={<SignUpPage />} />
      </Route>

      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route path={ROUTES.library} element={<LibraryPage />} />
          <Route path={ROUTES.video} element={<VideoPage />} />
          <Route path={ROUTES.account} element={<AccountPage />} />
          <Route path={ROUTES.setup} element={<SetupPage />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to={ROUTES.library} replace />} />
    </Routes>
  );
}
