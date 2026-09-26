// Inspect every permitted frame independently, including nested lazy-loaded embeds.
import { discoverPage } from "./page-discovery";
import { discoverDomTranscript } from "./dom-transcript";
import type { FrameDiscoveryResult } from "./discovery";

export async function inspectFrames(
  tabId: number,
  requestAccess = false,
): Promise<FrameDiscoveryResult[]> {
  const frames = (await chrome.webNavigation.getAllFrames({ tabId })) || [];
  if (requestAccess) {
    const origins = [
      ...new Set(
        // The side panel can outlive activeTab access after a tab switch or navigation.
        // Include the main page, not only embedded player origins.
        frames.flatMap((f) => {
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
  const failures: string[] = [];
  for (const frame of frames) {
    try {
      const found = await chrome.scripting.executeScript({
        target: { tabId, frameIds: [frame.frameId] },
        func: discoverPage,
      });
      for (const entry of found) {
        const discovery = entry.result;
        const owners = discovery?.videos;
        // DOM panels have no reliable media identity in a multi-video page.
        if (discovery && owners?.length === 1 && !owners[0]!.caption_candidates.length) {
          try {
            const transcripts = await chrome.scripting.executeScript({
              target: { tabId, frameIds: [frame.frameId] },
              func: discoverDomTranscript,
              args: [discovery.frame_url || discovery.page_url],
            });
            const captions = transcripts[0]?.result || [];
            owners[0]!.caption_candidates.push(...captions);
            discovery.caption_candidates = [...owners[0]!.caption_candidates];
          } catch {
            /* A changing/unpermitted page must not discard discovered media. */
          }
        }
      }
      results.push(...found);
    } catch (error) {
      /* A sandboxed, unloaded or unpermitted sibling must not abort the page. */
      failures.push(
        `Frame ${frame.frameId}: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }
  if (!results.some((entry) => entry.result)) {
    throw new Error(
      failures.length
        ? `Could not inspect this tab. ${failures.join("; ")}`
        : "Could not inspect this tab: no page frame returned a result. Reload the page and try again.",
    );
  }
  return results;
}
