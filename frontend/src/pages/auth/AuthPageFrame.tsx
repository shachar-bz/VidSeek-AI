import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Panel } from "../../components/ui";

export function AuthPageFrame({
  title,
  introduction,
  alternatePrompt,
  alternateLabel,
  alternatePath,
  children
}: {
  title: string;
  introduction: string;
  alternatePrompt: string;
  alternateLabel: string;
  alternatePath: string;
  children: ReactNode;
}) {
  return (
    <main className="auth-page">
      <section className="auth-page__intro" aria-labelledby="auth-title">
        <Link className="auth-page__brand" to="/" aria-label="VidSeek home">
          <span className="brand-mark" aria-hidden="true" />
          VidSeek
        </Link>
        <div>
          <p className="auth-page__eyebrow">Your video knowledge, ready when you are.</p>
          <h1 id="auth-title">{title}</h1>
          <p className="auth-page__lede">{introduction}</p>
        </div>
      </section>

      <section className="auth-page__form-column" aria-label={title}>
        <Panel className="auth-card">
          {children}
          <p className="auth-card__alternate">
            {alternatePrompt} <Link to={alternatePath}>{alternateLabel}</Link>
          </p>
        </Panel>
      </section>
    </main>
  );
}
