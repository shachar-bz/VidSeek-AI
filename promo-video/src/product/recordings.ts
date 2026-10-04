import type { CameraKeyframe, ClipSegment } from "./recordingTiming";

// Every product scene's source material, as data. Swapping a recording is an edit here:
// change `src`, `sourceSize`, `pageRect`, `segments`, `camera`, `clicks` and the overlay times.
//
// Units:
// * source px: pixels of the recording file (or still image) itself.
// * scene seconds: seconds from the scene's start in the edited demonstration, i.e. BEFORE
//   `visualPlaybackRates` (timeline.ts) speeds the whole scene up. Camera `at`, still `from`,
//   click `sceneTime` and overlay times all use scene seconds.
// * source seconds: a moment in the recording file. `segments` cut and speed it up; overlays tied
//   to real events use source seconds and are mapped through the segments.

export type SourceSize = { width: number; height: number };
export type SourceRect = { x: number; y: number; width: number; height: number };

// What the window's address pill shows: a third-party site's real domain, or the VidSeek website.
export type AddressLabel = { kind: "site"; domain: string } | { kind: "vidseek" };

export type RecordingMedia =
  | { kind: "video"; src: string; segments: ClipSegment[] }
  | { kind: "stills"; frames: { from: number; src: string }[] };

export type Recording = {
  media: RecordingMedia;
  sourceSize: SourceSize;
  // The web page inside the source, without the browser's tab strip, toolbar or window frame.
  // The camera never shows anything outside it, so the window never shows bars.
  pageRect: SourceRect;
  // Camera framings in source px (center + visible width; the height follows from 16:9).
  // Omit for the whole page. Keep moves slow; at most ~1.6x on 1x recordings.
  camera?: CameraKeyframe[];
};

// A real click in the recording, marked with a ripple.
export type RealClick = { sourceX: number; sourceY: number } & ({ sourceTime: number } | { sceneTime: number });

export type ProductSceneSource = {
  address: AddressLabel;
  recording: Recording;
  clicks?: RealClick[];
};

// Chrome recordings (1912–1920 × 1146–1152). Measured on frames: the tab strip + toolbar
// end with a hairline at y=86, so the page starts at y=87 in every clip. Clips recorded with the
// window frame visible (the extension side panel clips and the site logins) also have an 8px
// frame on the left, page bottom at y=1144 and the panel's edge at x≈1910.
export const CHROME_UI_HEIGHT = 87;
const framedChromePage = (pageRight: number): SourceRect => ({
  x: 8,
  y: CHROME_UI_HEIGHT,
  width: pageRight - 8,
  height: 1144 - CHROME_UI_HEIGHT,
});
const websitePage = (sourceSize: SourceSize, pageRight = sourceSize.width): SourceRect => ({
  x: 0,
  y: CHROME_UI_HEIGHT,
  width: pageRight,
  height: sourceSize.height - CHROME_UI_HEIGHT,
});

const YOUTUBE: AddressLabel = { kind: "site", domain: "youtube.com" };
const VIDSEEK: AddressLabel = { kind: "vidseek" };

export const productSceneSources = {
  askAnything: {
    address: YOUTUBE,
    recording: {
      media: {
        kind: "video",
        src: "clips/youtube_vid_question_a.mp4",
        segments: [
          { start: 0, end: 15.2, speed: 8 },
          { start: 15.2, end: 15.6, speed: 1 },
          { start: 15.6, end: 24.8, speed: 8 },
          { start: 24.8, end: 26.8, speed: 1 },
          { start: 26.8, holdSeconds: 1.3 },
        ],
      },
      sourceSize: { width: 1912, height: 1150 },
      pageRect: framedChromePage(1910),
      // The question lands in the side panel at 2.0 s and the answer at 3.45 s: ease onto the panel.
      camera: [
        { at: 0, centerX: 959, centerY: 615, width: 1879 },
        { at: 1.7, centerX: 959, centerY: 615, width: 1879 },
        { at: 3.1, centerX: 1360, centerY: 396, width: 1100 },
      ],
    },
  },
  jumpToMoment: {
    address: VIDSEEK,
    recording: {
      media: {
        kind: "video",
        src: "clips/coursera_questions_a.mp4",
        segments: [
          { start: 1.6, end: 2.8, speed: 1 },
          { start: 2.8, end: 11.5, speed: 8 },
          { start: 11.5, end: 12.8, speed: 1 },
          { start: 13.6, end: 15.8, speed: 1 },
          { start: 15.8, holdSeconds: 0.6 },
        ],
      },
      sourceSize: { width: 1916, height: 1146 },
      pageRect: websitePage({ width: 1916, height: 1146 }),
      // Page header to panel bottom, then the player + answer for the timestamp click.
      camera: [
        { at: 0, centerX: 958, centerY: 555, width: 1662 },
        { at: 2.0, centerX: 958, centerY: 555, width: 1662 },
        { at: 3.3, centerX: 842, centerY: 565, width: 1110 },
      ],
    },
    clicks: [{ sourceTime: 14.2, sourceX: 1191, sourceY: 699 }],
  },
  comments: {
    address: YOUTUBE,
    recording: {
      media: {
        kind: "video",
        src: "clips/youtube_question_b.mp4",
        segments: [
          { start: 0, end: 9.6, speed: 8 },
          { start: 9.6, end: 11, speed: 4 },
          { start: 11, end: 11.6, speed: 1 },
          { start: 11.6, end: 18.1, speed: 8 },
          { start: 18.1, end: 21.6, speed: 1 },
          { start: 21.6, holdSeconds: 0.4 },
        ],
      },
      sourceSize: { width: 1916, height: 1152 },
      pageRect: framedChromePage(1911),
      // The comment summary arrives at ~3.4 s in the lower half of the side panel.
      camera: [
        { at: 0, centerX: 959, centerY: 615, width: 1879 },
        { at: 2.0, centerX: 959, centerY: 615, width: 1879 },
        { at: 3.4, centerX: 1360, centerY: 560, width: 1100 },
      ],
    },
  },
  followUps: {
    address: VIDSEEK,
    recording: {
      media: {
        kind: "video",
        src: "clips/ted_questions_a_b.mp4",
        segments: [
          // Question a: "what does Sam think about agents? are they advancing too fast?"
          { start: 7.0, end: 11.0, speed: 8 },
          { start: 11.0, end: 12.0, speed: 1 },
          { start: 12.2, end: 21.5, speed: 8 },
          { start: 21.5, end: 23.5, speed: 1 },
          // Follow-up b: "how can we limit the agents?" (the long wait and the layout reflow are cut)
          { start: 33.5, end: 37, speed: 8 },
          { start: 37, end: 37.8, speed: 1 },
          { start: 47, end: 48.6, speed: 8 },
          { start: 48.6, end: 49.8, speed: 1 },
          { start: 50, end: 53.6, speed: 6 },
          { start: 53.6, end: 55.7, speed: 1 },
          { start: 55.7, holdSeconds: 0.4 },
        ],
      },
      sourceSize: { width: 1916, height: 1148 },
      // A dark page scrollbar runs down the right edge from x=1905.
      pageRect: websitePage({ width: 1916, height: 1148 }, 1904),
      camera: [
        { at: 0, centerX: 952, centerY: 555, width: 1662 },
        { at: 2.4, centerX: 952, centerY: 555, width: 1662 },
        { at: 3.6, centerX: 955, centerY: 575, width: 1330 },
      ],
    },
    clicks: [{ sourceTime: 53.9, sourceX: 1382, sourceY: 874 }],
  },
  itWatches: {
    address: { kind: "site", domain: "archive.org" },
    recording: {
      media: {
        kind: "video",
        src: "clips/Internet_archive_question_a.mp4",
        segments: [
          { start: 0, end: 2.4, speed: 2 },
          { start: 5.4, end: 6.4, speed: 1 }, // skips the typed-then-deleted " for how"
          { start: 6.4, end: 10.4, speed: 4 }, // "Looking at what the video shows..."
          { start: 50.4, end: 54.2, speed: 8 },
          { start: 54.2, end: 56.2, speed: 1 },
          { start: 56.2, holdSeconds: 3.2 },
        ],
      },
      sourceSize: { width: 1918, height: 1148 },
      pageRect: framedChromePage(1911),
      camera: [
        { at: 0, centerX: 959, centerY: 615, width: 1879 },
        { at: 2.2, centerX: 959, centerY: 615, width: 1879 },
        { at: 3.6, centerX: 1360, centerY: 420, width: 1150 },
      ],
    },
  },
  itReads: {
    address: VIDSEEK,
    recording: {
      media: {
        kind: "video",
        src: "clips/moodle_question_a.mp4",
        segments: [
          { start: 2.0, end: 4.6, speed: 4 },
          { start: 4.6, end: 5.6, speed: 1 },
          { start: 5.8, end: 15.8, speed: 8 },
          { start: 15.8, end: 17.3, speed: 1 },
          { start: 21.0, end: 23.4, speed: 1 },
          { start: 23.4, end: 25.0, speed: 1 },
          { start: 25.0, holdSeconds: 3.0 },
        ],
      },
      sourceSize: { width: 1920, height: 1148 },
      pageRect: websitePage({ width: 1920, height: 1148 }),
      camera: [
        { at: 0, centerX: 960, centerY: 555, width: 1662 },
        { at: 2.6, centerX: 960, centerY: 555, width: 1662 },
        { at: 3.9, centerX: 842, centerY: 560, width: 1110 },
      ],
    },
    clicks: [{ sourceTime: 21.8, sourceX: 1161, sourceY: 699 }],
  },
  // Still captures until the new website recordings arrive. 2370×1314 @2x; the page fills the top-left
  // 2133×1184 and the rest of the capture is unused browser area.
  library: {
    address: VIDSEEK,
    recording: {
      media: { kind: "stills", frames: [{ from: 0, src: "stills/library_rows_v2.png" }] },
      sourceSize: { width: 2370, height: 1314 },
      pageRect: { x: 0, y: 0, width: 2133, height: 1184 },
      camera: [
        { at: 0, centerX: 1066, centerY: 592, width: 2105 },
        { at: 0.6, centerX: 1066, centerY: 592, width: 2105 },
        { at: 5.6, centerX: 1066, centerY: 640, width: 1660 },
      ],
    },
  },
  chatPins: {
    address: VIDSEEK,
    recording: {
      media: {
        kind: "stills",
        frames: [
          { from: 0, src: "stills/chat_history.png" },
          { from: 1.65, src: "stills/chat_before_pin.png" },
          { from: 4.1, src: "stills/chat_pinned.png" },
          { from: 6.45, src: "stills/chat_pin_open.png" },
        ],
      },
      sourceSize: { width: 2370, height: 1314 },
      pageRect: { x: 0, y: 0, width: 2133, height: 1184 },
      camera: [
        { at: 0, centerX: 1066, centerY: 592, width: 2105 },
        { at: 0.2, centerX: 1066, centerY: 592, width: 2105 },
        { at: 1.3, centerX: 1130, centerY: 545, width: 1560 },
        { at: 2.2, centerX: 1130, centerY: 545, width: 1560 },
        { at: 3.4, centerX: 1330, centerY: 600, width: 1300 },
      ],
    },
    clicks: [
      { sceneTime: 1.55, sourceX: 1625, sourceY: 350 }, // open "Chat 1"
      { sceneTime: 4.0, sourceX: 1225, sourceY: 912 }, // "Pin"
      { sceneTime: 6.35, sourceX: 1640, sourceY: 495 }, // the pinned answer's link
    ],
  },
} satisfies Record<string, ProductSceneSource>;

// "It watches": the answer's 08:39–08:44 chip lifts off and opens into the real moment.
export const whiskReveal = {
  // Scene seconds when the chip lifts; the circle opens 0.35 s later.
  revealAt: 5.9,
  chipSource: { x: 1716, y: 321 }, // the chip's center in the Internet Archive recording
  chipLabel: "08:39–08:44",
  momentLabel: "08:39",
  foundLabel: "Found it: whisking the eggs",
  footage: {
    // 8:34–8:50 of the cooking show, 1454×1080 (4:3). Its edges have 3–14px of dark ramp.
    media: { kind: "video", src: "clips/ia_whisk.mp4", segments: [{ start: 4.0, end: 7.2, speed: 1 }] },
    sourceSize: { width: 1454, height: 1080 },
    pageRect: { x: 8, y: 4, width: 1432, height: 1075 },
    // Cover-crop to 16:9 around the bowl; a slow push keeps it alive. Times from the circle opening.
    camera: [
      { at: 0, centerX: 727, centerY: 448, width: 1432 },
      { at: 2.6, centerX: 742, centerY: 452, width: 1330 },
    ],
  } satisfies Recording,
};

// "It reads": the formula lifts off the real slide. Retarget `rect` and `holdSourceTime` for a new recording.
export const formulaLift = {
  liftAt: 8.2, // scene seconds
  holdSourceTime: 25.0, // the source frame the lifted formula is cut from
  rect: { x: 452, y: 358, width: 340, height: 86 }, // the formula on the slide, source px
  citation: "READ FROM THE SLIDE · 37:27",
  answer: "The minimum seam cost to each pixel is its energy plus the cheapest of the three pixels above it.",
};

// The supported-site carousel inside the window. Coursera gets a new clip of the extension's
// Scan/Download press; replace its entry when it arrives.
export type FindVideoTile = {
  chipLabel: string;
  address: AddressLabel;
  recording: Recording;
};
const siteLogin = (src: string, sourceSize: SourceSize, sourceStart: number, pageRight: number): Recording => ({
  media: { kind: "video", src, segments: [{ start: sourceStart, end: sourceStart + 2.5, speed: 1 }] },
  sourceSize,
  pageRect: framedChromePage(pageRight),
});
export const findVideoTiles: FindVideoTile[] = [
  { chipLabel: "YouTube", address: YOUTUBE, recording: siteLogin("clips/youtube-login.mp4", { width: 1914, height: 1150 }, 0, 1910) },
  {
    chipLabel: "Internet Archive",
    address: { kind: "site", domain: "archive.org" },
    recording: siteLogin("clips/Internet_archive-login.mp4", { width: 1916, height: 1150 }, 0.3, 1911),
  },
  { chipLabel: "TED", address: { kind: "site", domain: "ted.com" }, recording: siteLogin("clips/ted-login.mp4", { width: 1918, height: 1152 }, 37.2, 1911) },
  {
    chipLabel: "Coursera",
    address: { kind: "site", domain: "coursera.org" },
    recording: siteLogin("clips/coursera-login.mp4", { width: 1916, height: 1148 }, 0, 1909),
  },
  {
    chipLabel: "Moodle / Panopto",
    address: { kind: "site", domain: "panopto.eu" },
    recording: siteLogin("clips/moodle-login.mp4", { width: 1914, height: 1148 }, 0, 1910),
  },
];
// Global seconds each tile takes over (on the 0.5 s beat grid); the last runs until askAnything.
export const findVideoTileStarts = [19.5, 21.0, 22.0, 23.0, 24.0];
