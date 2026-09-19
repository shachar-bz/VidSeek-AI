// Every URL the website has, in one place, so a link and a route cannot drift apart.
//
// The set is closed: §Out of scope rules out adding a video from the website, searching
// across the library, and any cross-video conversations or notes view, so there is no page
// for any of them. Conversations live only on their video's page and are addressed by a
// query parameter rather than by a path of their own, because opening one is a change of
// panel on that page rather than a change of page.

export const ROUTES = {
  /** The home page for a signed-in user. */
  library: "/",
  signIn: "/sign-in",
  signUp: "/sign-up",
  video: "/videos/:videoId",
  account: "/account",
  /** How a video gets into the library at all: install the extension, run the companion. */
  setup: "/setup"
} as const;

/** The query parameter that selects which conversation a video page has open. */
export const CONVERSATION_PARAMETER = "conversation";

/** The two pages a signed-out visitor may reach. Everything else redirects to sign-in. */
export const PUBLIC_ROUTES: readonly string[] = [ROUTES.signIn, ROUTES.signUp];

export function videoPath(videoId: string, conversationId?: string): string {
  const base = ROUTES.video.replace(":videoId", encodeURIComponent(videoId));
  if (!conversationId) return base;
  return `${base}?${CONVERSATION_PARAMETER}=${encodeURIComponent(conversationId)}`;
}
