import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import brandIcon from "../../assets/auth/vidseek-icon.png";
import { ROUTES } from "../../routes";
import { AuthShowcaseCarousel } from "./AuthShowcaseCarousel";

export function AuthPageFrame({
  mode,
  alternatePrompt,
  alternateLabel,
  alternatePath,
  children
}: {
  mode: "sign-in" | "sign-up";
  alternatePrompt: string;
  alternateLabel: string;
  alternatePath: string;
  children: ReactNode;
}) {
  return (
    <main className="auth-page">
      <section className="auth-page__showcase" aria-labelledby="auth-showcase-title">
        <Link className="auth-page__brand" to={ROUTES.signIn} aria-label="VidSeek AI sign in">
          <img src={brandIcon} alt="" />
          <span>VidSeek AI</span>
        </Link>

        <div className="auth-page__showcase-content">
          <div className="auth-page__showcase-heading">
            <h1 id="auth-showcase-title">Understand the video better</h1>
            <p>Search a phrase. Skip the scrubbing.</p>
          </div>
          <AuthShowcaseCarousel />
        </div>
      </section>

      <section className="auth-page__form-column" aria-labelledby="auth-form-title">
        <div className="auth-card">
          <div className="auth-card__heading">
            <h2 id="auth-form-title">Find any moment.</h2>
            <p>Search inside your videos with AI.</p>
          </div>

          <nav className="auth-card__tabs" aria-label="Account access">
            <Link
              className={mode === "sign-in" ? "auth-card__tab auth-card__tab--active" : "auth-card__tab"}
              to={ROUTES.signIn}
              aria-current={mode === "sign-in" ? "page" : undefined}
            >
              Sign in
            </Link>
            <Link
              className={mode === "sign-up" ? "auth-card__tab auth-card__tab--active" : "auth-card__tab"}
              to={ROUTES.signUp}
              aria-current={mode === "sign-up" ? "page" : undefined}
            >
              Sign up
            </Link>
          </nav>

          {children}
          <p className="auth-card__alternate">
            {alternatePrompt} <Link to={alternatePath}>{alternateLabel}</Link>
          </p>
        </div>
      </section>
    </main>
  );
}
