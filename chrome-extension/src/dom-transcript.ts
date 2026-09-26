// Read timed transcript panels, including bounded virtualized lists, without provider rules.
import type { CaptionCandidate } from "./types";

/** Serialized by Chrome: keep every helper inside this function. */
export async function discoverDomTranscript(expectedPageUrl?: string): Promise<CaptionCandidate[]> {
  if (expectedPageUrl && location.href !== expectedPageUrl) return [];
  const roots: (Document | ShadowRoot)[] = [document];
  for (let i = 0; i < roots.length && i < 200; i++) {
    for (const node of roots[i]!.querySelectorAll("*"))
      if (node.shadowRoot) roots.push(node.shadowRoot);
  }
  const query = <T extends Element>(selector: string): T[] =>
    roots.flatMap((root) => [...root.querySelectorAll<T>(selector)]);
  const videos = query<HTMLVideoElement>("video");
  // Without an owner and a duration we cannot check completeness or time the last cue.
  if (videos.length !== 1) return [];
  const video = videos[0]!;
  if (/advertisement|פרסומת/i.test(`${video.title} ${video.getAttribute("aria-label") || ""}`)) return [];
  const duration = video.duration;
  if (!Number.isFinite(duration) || duration <= 0) return [];
  const page = location.href, source = video.currentSrc || video.src;
  const unchanged = (): boolean => video.isConnected && location.href === page &&
    (video.currentSrc || video.src) === source && video.duration === duration;
  const seconds = (text: string): number | undefined => {
    const match = /^(?:(\d{1,2}):)?(\d{1,3}):([0-5]\d)(?:[.,](\d{1,3}))?$/.exec(text.trim());
    if (!match || (match[1] && Number(match[2]) > 59)) return;
    return Number(match[1] || 0) * 3600 + Number(match[2]) * 60 +
      Number(match[3]) + Number(`0.${match[4] || 0}`);
  };
  const hidden = (element: Element): boolean => {
    for (let node: Element | null = element; node;) {
      const style = getComputedStyle(node);
      if (node.hasAttribute("hidden") || node.getAttribute("aria-hidden") === "true" ||
          style.display === "none" || style.visibility === "hidden") return true;
      const root = node.getRootNode();
      node = node.parentElement || (root instanceof ShadowRoot ? root.host : null);
    }
    return false;
  };
  const candidates = query<HTMLElement>(
    '[id*="transcript" i],[class*="transcript" i],[id*="caption" i],'+
    '[class*="caption" i],[id*="subtitle" i],[class*="subtitle" i],[aria-label],[aria-labelledby]',
  ).filter((element) => {
    const root = element.getRootNode() as Document | ShadowRoot;
    const labels = (element.getAttribute("aria-labelledby") || "").split(/\s+/)
      .map((id) => root.getElementById(id)?.textContent || "");
    return /transcript|caption|subtitle|תמלול|כתוביות/i.test(
      `${element.id} ${element.className} ${element.getAttribute("aria-label") || ""} ${labels.join(" ")}`,
    ) && !element.matches('button,[role="tab"],input') && !hidden(element);
  });
  const candidateSet = new Set<Element>(candidates);
  const regions = candidates.filter((element) => {
    for (let parent = element.parentElement; parent; parent = parent.parentElement)
      if (candidateSet.has(parent)) return false;
    return true;
  }).slice(0, 20);
  type Cue = { text: string; start: number };
  const read = (region: HTMLElement): Cue[] => {
    const nodes = [...region.querySelectorAll<HTMLElement>("*")];
    if (nodes.length > 12_000) return [];
    const timestamps = nodes.filter((node) => !node.children.length &&
      seconds(node.textContent || "") !== undefined && !hidden(node));
    const counts = new Map<Element, number>();
    for (const timestamp of timestamps) {
      for (let parent = timestamp.parentElement; parent && parent !== region; parent = parent.parentElement)
        counts.set(parent, (counts.get(parent) || 0) + 1);
    }
    const cues: Cue[] = [];
    for (const timestamp of timestamps) {
      let row: Element | null = timestamp.parentElement;
      for (let depth = 0; row && row !== region && depth < 4; depth++, row = row.parentElement) {
        if (counts.get(row) !== 1) break;
        const parts: string[] = [];
        const walker = document.createTreeWalker(row, NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) {
          const node = walker.currentNode, parent = node.parentElement;
          if (!parent || timestamp.contains(node) || hidden(parent)) continue;
          const control = parent.closest('button,input,select,textarea,script,style,[role="button"],svg');
          // A whole cue may be a seek button; nested copy/menu controls are not speech.
          if (control && control !== row) continue;
          parts.push(node.textContent || "");
        }
        const text = parts.join(" ").replace(/\s+/g, " ").trim();
        if (!/\p{L}/u.test(text)) continue;
        cues.push({ text, start: seconds(timestamp.textContent || "")! });
        break;
      }
    }
    return cues;
  };
  const complete = (cues: Cue[]): boolean => cues.length >= 3 &&
    cues[0]!.start <= Math.min(60, duration * 0.1) &&
    cues[cues.length - 1]!.start >= duration * 0.9 &&
    cues.every((cue, i) => cue.start < duration && (i === 0 ||
      (cue.start > cues[i - 1]!.start && cue.start - cues[i - 1]!.start <= Math.max(60, duration * 0.1))));
  const deadline = Date.now() + 8_000;
  for (const region of regions) {
    if (!unchanged() || Date.now() > deadline) return [];
    let cues = read(region);
    if (!complete(cues) && cues.length >= 3) {
      // Scroll only the transcript panel, never the whole page. Overlapping
      // snapshots prove continuity across a virtualized/lazily loaded list.
      let scroll: HTMLElement | null = region;
      const scrollable = (node: HTMLElement): boolean => node.clientHeight > 0 &&
        node.scrollHeight > node.clientHeight && /auto|scroll/.test(getComputedStyle(node).overflowY);
      while (scroll && scroll !== document.body && !scrollable(scroll)) scroll = scroll.parentElement;
      if (!scroll || scroll === document.body) {
        scroll = [...region.querySelectorAll<HTMLElement>("*")].find(scrollable) || null;
      }
      if (scroll) {
        const original = scroll.scrollTop;
        const collected = new Map<number, string>();
        let valid = true, reachedEnd = false;
        try {
          for (let step = 0, position = 0; step < 60 && Date.now() < deadline; step++) {
            scroll.scrollTop = position;
            await new Promise((resolve) => setTimeout(resolve, 100));
            if (!unchanged() || !region.isConnected) { valid = false; break; }
            const snapshot = read(region);
            if (snapshot.length < 3 || (step > 0 && !snapshot.some((cue) => collected.has(cue.start)))) {
              valid = false; break;
            }
            for (const cue of snapshot) {
              if (collected.has(cue.start) && collected.get(cue.start) !== cue.text) valid = false;
              collected.set(cue.start, cue.text);
            }
            if (!valid || collected.size > 5_000) { valid = false; break; }
            if (scroll.scrollTop + scroll.clientHeight >= scroll.scrollHeight - 2) { reachedEnd = true; break; }
            position = scroll.scrollTop + scroll.clientHeight * 0.7;
          }
        } finally {
          scroll.scrollTop = original;
        }
        cues = valid && reachedEnd ? [...collected].map(([start, text]) => ({ start, text })).sort((a, b) => a.start - b.start) : [];
      }
    }
    if (!complete(cues) || !unchanged()) continue;
    const text = JSON.stringify({ unit: "seconds", cues: cues.map((cue, i) => ({
      ...cue, end: cues[i + 1]?.start ?? duration,
    })) });
    if (text.length > 200_000) continue;
    return [{ format: "json", text, is_active: false, is_manual: false,
      is_visible_transcript: false,
      language: region.closest("[lang]")?.getAttribute("lang") || undefined }];
  }
  return [];
}
