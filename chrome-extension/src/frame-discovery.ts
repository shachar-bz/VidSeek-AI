// Inspect every permitted frame independently, including nested lazy-loaded embeds.
import { discoverPage } from "./page-discovery";
import type { FrameDiscoveryResult } from "./discovery";

export async function inspectFrames(
  tabId: number,
  requestAccess = false,
): Promise<FrameDiscoveryResult[]> {
  const frames = (await chrome.webNavigation.getAllFrames({ tabId })) || [];
  if (requestAccess) {
    const origins = [
      ...new Set(
        frames
          .filter((f) => f.frameId !== 0)
          .flatMap((f) => {
            try {
              const u = new URL(f.url);
              return /^https?:$/.test(u.protocol)
                ? [`${u.protocol}//${u.hostname}/*`]
                : [];
            } catch {
              return [];
            }
          }),
      ),
    ];
    if (origins.length) await chrome.permissions.request({ origins });
  }
  const results: FrameDiscoveryResult[] = [];
  for (const frame of frames) {
    try {
      const found = await chrome.scripting.executeScript({
        target: { tabId, frameIds: [frame.frameId] },
        func: discoverPage,
      });
      results.push(...found);
    } catch {
      /* A sandboxed, unloaded or unpermitted sibling must not abort the page. */
    }
  }
  return results;
}
