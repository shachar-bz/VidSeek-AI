import { Link } from "react-router-dom";

import { Panel, StatusBadge } from "../../components/ui";
import { ROUTES } from "../../routes";

const EXTENSION_URL = "https://github.com/shachar-bz/VidSeek-AI/tree/main/chrome-extension";
const COMPANION_URL =
  "https://github.com/shachar-bz/VidSeek-AI/tree/main/backend/services/video_download/web";

const STEPS = [
  {
    number: "01",
    title: "Install the Chrome extension",
    body: (
      <>
        <p>Download the extension source, build it, then open <code>chrome://extensions</code>, enable Developer mode, and choose <strong>Load unpacked</strong> for <code>chrome-extension/dist</code>.</p>
        <pre><code>cd chrome-extension{"\n"}npm install{"\n"}npm run build</code></pre>
        <a href={EXTENSION_URL} target="_blank" rel="noreferrer">Get the Chrome extension files</a>
      </>
    )
  },
  {
    number: "02",
    title: "Run the local companion",
    body: (
      <>
        <p>Install Python 3.11+, FFmpeg, and the backend requirements. Copy the extension ID from Chrome into <code>VIDSEEK_EXTENSION_IDS</code> in <code>backend/.env</code>, add the required service credentials, then apply the database schema and start the loopback service.</p>
        <pre><code>python -m backend.storage.postgres.migrate{"\n"}uvicorn backend.app:app --host 127.0.0.1 --port 8765</code></pre>
        <p>The extension expects the companion at <code>http://127.0.0.1:8765</code>. Keep this process running while sending a video.</p>
        <a href={COMPANION_URL} target="_blank" rel="noreferrer">Read the companion configuration reference</a>
      </>
    )
  },
  {
    number: "03",
    title: "Sign in with the same account",
    body: <p>Open the VidSeek extension and sign in with the same email and password you use here. The shared account connects extension submissions to your private library.</p>
  },
  {
    number: "04",
    title: "Send a video to your library",
    body: <p>Open a supported video in Chrome and use the extension to inspect and send it. If prompted, play or reload the video so VidSeek can verify the media. Processing progress then appears live in your website library.</p>
  }
] as const;

export function SetupPage() {
  return (
    <div className="feature-page setup-page">
      <header className="feature-page__heading setup-page__hero">
        <div>
          <p className="eyebrow">Four steps to your first video</p>
          <h1>Connect Chrome to your library</h1>
          <p>VidSeek uses a Chrome extension and a local companion to securely send videos into your account. The website displays what they send; it does not ingest URLs or files itself.</p>
        </div>
        <StatusBadge tone="active">About 10 minutes</StatusBadge>
      </header>

      <ol className="setup-steps">
        {STEPS.map((step) => (
          <li key={step.number}>
            <span className="setup-step__number" aria-hidden="true">{step.number}</span>
            <Panel className="setup-step"><h2>{step.title}</h2><div>{step.body}</div></Panel>
          </li>
        ))}
      </ol>

      <Panel className="setup-finish">
        <div><p className="eyebrow">You’re connected</p><h2>Watch the handoff in your library</h2><p>Downloading, transcription, and understanding appear as live stages. You can leave the tab and return later to see the latest state.</p></div>
        <Link className="button-link button-link--primary" to={ROUTES.library}>Go to library</Link>
      </Panel>
    </div>
  );
}
