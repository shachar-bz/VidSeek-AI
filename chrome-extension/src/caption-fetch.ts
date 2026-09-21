// Read bounded caption bodies in the authenticated frame, with extension fetch as fallback.
import type { DiscoveryResult } from "./types";

/** Serialized by Chrome: all helpers and limits must stay inside this function. */
export async function readCaptionBody(url: string): Promise<string | null> {
  try {
    const limit = 2_000_000;
    const response = await fetch(url, {
      credentials: "include",
      signal: AbortSignal.timeout(15_000),
    });
    if (
      !response.ok ||
      !response.body ||
      Number(response.headers.get("content-length")) > limit
    )
      return null;
    const reader = response.body.getReader(),
      decoder = new TextDecoder();
    let body = "",
      bytes = 0;
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      bytes += part.value.byteLength;
      if (bytes > limit) {
        await reader.cancel();
        return null;
      }
      body += decoder.decode(part.value, { stream: true });
    }
    return body + decoder.decode();
  } catch {
    return null;
  }
}

export async function hydrateCaptionBodies(
  discovery: DiscoveryResult,
  tabId?: number,
): Promise<void> {
  const frames =
    tabId === undefined
      ? []
      : (await chrome.webNavigation.getAllFrames({ tabId }).catch(() => [])) ||
        [];
  const preferred = discovery.preferred_language?.split("-")[0];
  const candidates = discovery.caption_candidates
    .filter((c) => c.url && !c.text)
    .sort((a, b) => {
      const rank = (c: typeof a) =>
        (c.is_active ? 0 : 4) +
        (c.language?.split("-")[0] === preferred ? 0 : 2) +
        (c.is_manual ? 0 : 1);
      return rank(a) - rank(b);
    })
    .slice(0, 5);
  await Promise.all(
    candidates.map(async (candidate) => {
      const owner = frames.find(
        (f) =>
          f.url === discovery.frame_url &&
          new URL(f.url).origin === new URL(candidate.url!).origin,
      );
      let text: string | null = null;
      if (owner && tabId !== undefined) {
        try {
          const result = await chrome.scripting.executeScript({
            target: { tabId, frameIds: [owner.frameId] },
            func: readCaptionBody,
            args: [candidate.url!],
          });
          text = result[0]?.result || null;
        } catch {
          /* Host access may have been revoked since inspection. */
        }
      }
      text ||= await readCaptionBody(candidate.url!);
      if (text) {
        candidate.text = text;
        if (/^\s*[\[{]/.test(text)) candidate.format = "json";
        else if (/^\s*<(?:\?xml|tt\b)/i.test(text)) candidate.format = "ttml";
      }
    }),
  );
}
