// Collect playable resources and provider data without executing page scripts.
import type {
  CaptionCandidate,
  DiscoveryResult,
  MediaCandidate,
  MediaKind,
} from "./types";

/** Self-contained: Chrome serializes this function without its module closure. */
export function discoverPage(): DiscoveryResult {
  const roots: (Document | ShadowRoot)[] = [document];
  for (let i = 0; i < roots.length && i < 200; i++) {
    for (const node of roots[i]!.querySelectorAll("*"))
      if (node.shadowRoot) roots.push(node.shadowRoot);
  }
  const query = <T extends Element>(selector: string): T[] =>
    roots.flatMap((root) => [...root.querySelectorAll<T>(selector)]);
  const absolute = (s: string): string => {
    try {
      return new URL(s, document.baseURI).href;
    } catch {
      return "";
    }
  };
  const http = (s: string): boolean => /^https?:\/\//i.test(s);
  const youtube = (value: string): string | undefined => {
    try {
      const u = new URL(value, document.baseURI);
      if (
        !/(^|\.)(youtube\.com|youtube-nocookie\.com|youtu\.be)$/.test(
          u.hostname,
        )
      )
        return;
      const id =
        u.hostname === "youtu.be"
          ? u.pathname.split("/")[1]
          : u.searchParams.get("v") ||
            u.pathname.match(/\/(?:embed|shorts)\/([\w-]+)/)?.[1];
      return id && /^[\w-]{11}$/.test(id)
        ? `https://www.youtube.com/watch?v=${id}`
        : undefined;
    } catch {
      return;
    }
  };
  const adUrl = (u: string): boolean =>
    /(?:doubleclick\.net|2mdn\.net|googlesyndication\.com|\/web_video_ads\/|\/vast(?:[/.?]|$))/i.test(
      u,
    );
  const classify = (url: string, mime = ""): MediaKind | null => {
    if (!http(url) || adUrl(url) || /\.(?:m4s|ts|aac)(?:[?#]|$)/i.test(url))
      return null;
    if (/\.m3u8(?:[?#]|$)/i.test(url) || /mpegurl/i.test(mime)) return "hls";
    if (/\.mpd(?:[?#]|$)/i.test(url) || /dash\+xml/i.test(mime)) return "dash";
    if (
      /\.(mp4|m4v|webm|mov|mkv)(?:[?#]|$)/i.test(url) ||
      /^video\/(?!mp2t)/i.test(mime)
    )
      return "direct";
    return null;
  };
  const format = (url: string): string => {
    try {
      return (
        new URL(url).searchParams.get("fileExtension") ||
        /\.(vtt|srt|ttml|dfxp|json)(?:[?#]|$)/i.exec(url)?.[1]?.toLowerCase() ||
        "vtt"
      );
    } catch {
      return "vtt";
    }
  };
  const make = (id?: string, title?: string): DiscoveryResult => ({
    page_url: location.href,
    frame_url: location.href,
    page_title: (title || document.title || "Video").slice(0, 512),
    selected_media_id: id?.slice(0, 512),
    preferred_language: document.documentElement.lang || undefined,
    drm_detected: false,
    media_candidates: [],
    caption_candidates: [],
    structured_candidates: [],
  });
  const groups: DiscoveryResult[] = [];
  const fallback = make();
  const addMedia = (
    g: DiscoveryResult,
    value: string,
    mime = "",
    source = "structured",
  ): void => {
    const url = absolute(value),
      kind = classify(url, mime);
    if (
      !kind ||
      g.media_candidates.some((c) => c.url === url) ||
      g.media_candidates.length >= 100
    )
      return;
    g.media_candidates.push({
      url,
      kind,
      mime_type: mime,
      source,
      headers: { Referer: location.href, Origin: location.origin },
    });
  };
  const addCaption = (
    g: DiscoveryResult,
    candidate: Partial<CaptionCandidate>,
  ): void => {
    if (g.caption_candidates.length >= 50) return;
    if (candidate.url) {
      candidate.url = absolute(candidate.url);
      if (
        !http(candidate.url) ||
        g.caption_candidates.some((c) => c.url === candidate.url)
      )
        return;
    }
    g.caption_candidates.push({
      format: "vtt",
      is_active: false,
      is_manual: true,
      is_visible_transcript: false,
      ...candidate,
    });
  };
  const keepEvidence = (g: DiscoveryResult, value: unknown): void => {
    const text = JSON.stringify(value);
    if (
      text.length <= 200_000 &&
      g.structured_candidates!.length < 8 &&
      !g.structured_candidates!.includes(text)
    )
      g.structured_candidates!.push(text);
  };
  let visited = 0;
  // Walk data, not a list of provider-specific field names. Context supplies a MIME hint
  // for extensionless CDN URLs; unsupported fields remain available to the resolver.
  const walk = (
    value: unknown,
    g: DiscoveryResult,
    path = "",
    mime = "",
    depth = 0,
  ): void => {
    if (++visited > 40_000 || depth > 16 || value == null) return;
    if (typeof value === "string") {
      if (/^(?:https?:\/\/|\/\/|\/)/.test(value)) {
        const url = absolute(value);
        if (
          /\.(?:vtt|srt|ttml|dfxp)(?:[?#]|$)/i.test(url) ||
          /(?:caption|subtitle|transcript).*(?:url|src)|(?:caption|subtitle).*url/i.test(
            path,
          )
        ) {
          if (!url.includes("__lang__"))
            addCaption(g, { url, format: format(url) });
        } else if (
          !/(?:image|poster|cover|thumb|avatar|audio|music|adurl)/i.test(path)
        )
          addMedia(g, url, mime);
      }
      return;
    }
    if (Array.isArray(value)) {
      if (
        value.length &&
        value
          .slice(0, 5)
          .every(
            (row) =>
              row &&
              typeof row === "object" &&
              Object.values(row).some((v) => typeof v === "string") &&
              Object.values(row).some((v) => typeof v === "number"),
          )
      ) {
        const text = JSON.stringify({ [path || "cues"]: value });
        if (text.length <= 200_000) addCaption(g, { format: "json", text });
      }
      for (const item of value.slice(0, 5000))
        walk(item, g, path, mime, depth + 1);
      return;
    }
    if (typeof value !== "object") return;
    const obj = value as Record<string, unknown>;
    if (
      obj.isAd === true ||
      obj.is_ad === true ||
      obj.mediaType === "ADVERTISEMENT"
    )
      return;
    const video =
      obj.video && typeof obj.video === "object"
        ? (obj.video as Record<string, unknown>)
        : undefined;
    // A nested `video` object is not enough on its own. TED, for example, puts
    // `{ translation, video: { id, talkExtras } }` inside its transcript data. Treating
    // that relationship as a second playable item creates a phantom picker choice and
    // separates the real <video> element from the page's VideoObject. The containing
    // object must also identify the media item; feed entries such as TikTok's carry their
    // id/title beside the nested playback data, while transcript metadata does not.
    const identifiesNestedVideo = Boolean(
      video &&
        (obj.mediaId != null ||
          obj.id != null ||
          obj.title != null ||
          obj.name != null ||
          obj.desc != null),
    );
    const isVideo = Boolean(
      identifiesNestedVideo ||
      obj.mediaType === "MEDIA_VIDEO" ||
      obj["@type"] === "VideoObject",
    );
    if (isVideo && g === fallback) {
      const id = String(obj.mediaId || obj.id || video?.id || "");
      g = make(
        id || undefined,
        String(obj.title || obj.name || obj.desc || document.title),
      );
      groups.push(g);
      keepEvidence(g, video || obj);
    }
    if (obj.is_drm === true || obj.has_drm === true) g.drm_detected = true;
    const f = String(
      obj.format || obj.Format || obj.mimeType || obj.type || "",
    );
    const nextMime = /^(mp4|webm)$/i.test(f)
      ? `video/${f.toLowerCase()}`
      : /^video\//.test(f)
        ? f
        : mime;
    if (
      (isVideo || /(?:^|\.)video(?:Data)?$/.test(path)) &&
      typeof obj.duration === "number" &&
      obj.duration > 0 &&
      obj.duration < 86400
    )
      g.media_duration_seconds = obj.duration;
    for (const [key, item] of Object.entries(obj)) {
      if (
        /cookie|authorization|token|password|signature|session|userState|publishCompletion/i.test(
          key,
        )
      )
        continue;
      walk(item, g, `${path}.${key}`, nextMime, depth + 1);
    }
  };
  const parse = (text: string, g: DiscoveryResult): void => {
    try {
      const value = JSON.parse(text);
      walk(value, g);
      if (
        text.length <= 200_000 &&
        /video|player|caption|transcript|subtitle/i.test(text)
      )
        keepEvidence(g, value);
    } catch {
      /* Not JSON; never eval. */
    }
  };

  for (const script of query<HTMLScriptElement>(
    'script[type="application/json"],script[type="application/ld+json"],script:not([src])',
  )) {
    const text = script.textContent || "";
    if (text.length > 2_000_000) continue;
    if (/^\s*[\[{]/.test(text)) parse(text, fallback);
    // JSON objects embedded in assignments/calls (e.g. YITSiteWidgets). Balanced extraction
    // respects quoted braces, handles nested objects, and never runs JavaScript.
    else if (/\.mp4|\.mpd|\.m3u8/.test(text)) {
      let start = -1,
        level = 0,
        quoted = false,
        escaped = false;
      for (let i = 0; i < text.length; i++) {
        const c = text[i];
        if (quoted) {
          if (escaped) escaped = false;
          else if (c === "\\") escaped = true;
          else if (c === '"') quoted = false;
          continue;
        }
        if (c === '"' && level > 0) quoted = true;
        else if (c === "{") {
          if (level++ === 0) start = i;
        } else if (c === "}" && level > 0 && --level === 0)
          parse(text.slice(start, i + 1), fallback);
      }
    }
  }
  for (const block of query<HTMLElement>("[data-metadata]")) {
    const g = make(
      block.id || undefined,
      block.getAttribute("aria-label") || undefined,
    );
    const raw = block.getAttribute("data-metadata") || "{}";
    let data: Record<string, unknown> = {};
    try {
      data = JSON.parse(raw);
    } catch {
      continue;
    }
    const embed = block.querySelector<HTMLIFrameElement>("iframe");
    const yt = youtube(embed?.src || "");
    if (yt) g.page_url = yt;
    if (embed?.title) g.page_title = embed.title;
    g.preferred_language =
      String(data.transcriptLanguage || g.preferred_language || "") ||
      undefined;
    walk(data, g);
    if (
      typeof data.transcriptTranslationUrl === "string" &&
      g.preferred_language
    )
      addCaption(g, {
        url: data.transcriptTranslationUrl.replace(
          "__lang__",
          encodeURIComponent(g.preferred_language),
        ),
        format: "json",
        language: g.preferred_language,
      });
    const cues = [...block.querySelectorAll<HTMLElement>("[data-start]")]
      .map((e) => ({
        text: e.textContent?.trim(),
        start: Number(e.dataset.start) / 1000,
      }))
      .filter((c) => c.text && Number.isFinite(c.start));
    if (cues.length)
      addCaption(g, {
        text: JSON.stringify({ unit: "seconds", cues }),
        format: "json",
        language: g.preferred_language,
      });
    if (yt || g.media_candidates.length || g.caption_candidates.length)
      groups.push(g);
  }
  const ownYoutube = youtube(location.href);
  if (ownYoutube) return { ...make(), page_url: ownYoutube };
  for (const frame of query<HTMLIFrameElement>("iframe")) {
    const yt = youtube(frame.src || frame.dataset.src || "");
    if (yt && !groups.some((g) => g.page_url === yt))
      groups.push({ ...make(undefined, frame.title), page_url: yt });
  }
  for (const video of query<HTMLVideoElement>("video")) {
    if (
      /advertisement|פרסומת/i.test(
        `${video.title} ${video.getAttribute("aria-label") || ""}`,
      ) ||
      adUrl(video.currentSrc)
    )
      continue;
    const sources = [
      video.currentSrc,
      video.src,
      ...[...video.querySelectorAll("source")].map((s) => s.src),
    ].filter(Boolean);
    let g = groups.find((group) =>
      group.media_candidates.some((c) => sources.includes(c.url)),
    );
    // A blob player and a single structured source are normally two views of one video.
    if (!g && groups.length === 1 && query("video").length === 1) g = groups[0];
    if (!g) {
      g = make(undefined, video.getAttribute("aria-label") || undefined);
      groups.push(g);
    }
    // `type` is a `<source>` attribute, never a `<video>` one: a URL takes its MIME type
    // from the `<source>` that names it, or else from the response the element got for it.
    // The browser reports that only for a same-origin or CORS response, so an extensionless
    // cross-origin URL stays unclassified and is left to the playback check. Having loaded
    // is no evidence of a file: Chrome plays an HLS playlist natively, too.
    const sourceElements = [...video.querySelectorAll("source")];
    // `contentType` is newer than this TypeScript version's DOM types.
    const servedType = (url: string): string =>
      (
        performance.getEntriesByName(url) as (PerformanceEntry & {
          contentType?: string;
        })[]
      ).find((entry) => entry.contentType)?.contentType || "";
    for (const src of sources)
      addMedia(
        g,
        src,
        sourceElements.find((s) => s.src === src)?.type || servedType(src),
        "video",
      );
    g.drm_detected ||= Boolean(video.mediaKeys);
    if (Number.isFinite(video.duration) && video.duration > 0)
      g.media_duration_seconds = video.duration;
    // Lets the picker point at the video the user is watching right now.
    if (!video.paused && !video.ended && video.currentTime > 0)
      g.media_playing = true;
    for (const track of video.querySelectorAll("track")) {
      if (!["captions", "subtitles"].includes(track.kind)) continue;
      if (track.getAttribute("src"))
        addCaption(g, {
          url: track.src,
          format: format(track.src),
          language: track.srclang || undefined,
          is_active: track.track?.mode === "showing",
          is_manual: !/auto/i.test(track.label),
        });
    }
    for (const track of [...(video.textTracks || [])]) {
      if (
        !["captions", "subtitles"].includes(track.kind) ||
        !track.cues?.length
      )
        continue;
      const cues = [...track.cues].map((c) => ({
        text: (c as VTTCue).text,
        start: c.startTime,
        end: c.endTime,
      }));
      addCaption(g, {
        text: JSON.stringify({ unit: "seconds", cues }),
        format: "json",
        language: track.language,
        is_active: track.mode === "showing",
      });
    }
  }
  for (const meta of query<HTMLMetaElement>('meta[property^="og:video"]'))
    addMedia(fallback, meta.content, "", "metadata");
  for (const entry of performance.getEntriesByType("resource")) {
    if (/\.(vtt|srt|ttml)(?:[?#]|$)/i.test(entry.name))
      addCaption(fallback, { url: entry.name, format: format(entry.name) });
    else addMedia(fallback, entry.name, "", "performance");
  }
  // Only merge unassociated resources when there is one possible owner. A page-wide
  // transcript/capture is not evidence that captions belong to every video in a feed.
  const usable = groups.filter(
    (g) =>
      youtube(g.page_url) ||
      g.media_candidates.length ||
      g.caption_candidates.length ||
      g.structured_candidates?.length,
  );
  const unique: DiscoveryResult[] = [];
  for (const g of usable) {
    const duplicate = unique.find(
      (u) =>
        (youtube(g.page_url) && u.page_url === g.page_url) ||
        g.media_candidates.some((c) =>
          u.media_candidates.some((d) => d.url === c.url),
        ),
    );
    if (duplicate) {
      for (const c of g.caption_candidates) addCaption(duplicate, c);
      for (const m of g.media_candidates)
        addMedia(duplicate, m.url, m.mime_type, m.source);
    } else unique.push(g);
  }
  if (unique.length === 1 && !youtube(unique[0]!.page_url)) {
    const g = unique[0]!;
    // Prefer structured masters over arbitrary adaptive media playlists/segments.
    if (!g.media_candidates.length)
      g.media_candidates = fallback.media_candidates;
    for (const c of fallback.caption_candidates) addCaption(g, c);
    if (!g.structured_candidates?.length)
      g.structured_candidates = fallback.structured_candidates;
  }
  if (!unique.length) unique.push(fallback);
  for (const g of unique) {
    if (!g.selected_media_id && g.media_candidates.length) {
      const u = new URL(g.media_candidates[0]!.url);
      for (const name of [...u.searchParams.keys()]) {
        if (
          /token|signature|expires|policy|key-pair|credential|hmac|^sig$|^x-amz-/i.test(
            name,
          )
        )
          u.searchParams.delete(name);
      }
      u.searchParams.sort();
      const key = u.origin + u.pathname + u.search;
      let hash = 2166136261;
      for (const c of key) hash = Math.imul(hash ^ c.charCodeAt(0), 16777619);
      g.selected_media_id = "media-" + (hash >>> 0).toString(16);
    }
  }
  return {
    ...make(),
    media_candidates: unique.length === 1 ? unique[0]!.media_candidates : [],
    caption_candidates:
      unique.length === 1 ? unique[0]!.caption_candidates : [],
    videos: unique,
  };
}
