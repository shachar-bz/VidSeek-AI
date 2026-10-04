import type { ProductSceneSource, Recording, SourceSize } from "./recordings";

// The "library" and "chatPins" scenes are two cuts of ONE continuous website take,
// public/clips/v3/library_chats_pins.mp4 (event log and region boxes: library_chats_pins.json).
// The take was recorded at 1920×1080 CSS px × 1.5 with no browser UI, so the whole frame is the page.
// Its cursor and cobalt click rings are baked in: these scenes add no ClickRipple of their own.
// The cut between the two scenes falls on the library row click, where the take navigates to the video page,
// so the window's sideways push plays the role of that navigation.

const LIBRARY_TAKE_SRC = "clips/v3/library_chats_pins.mp4";
const LIBRARY_TAKE_SIZE: SourceSize = { width: 2880, height: 1620 };
const LIBRARY_TAKE_PAGE = { x: 0, y: 0, width: LIBRARY_TAKE_SIZE.width, height: LIBRARY_TAKE_SIZE.height };
const VIDSEEK_ADDRESS = { kind: "vidseek" } as const;

// Source seconds of the take's visible events (library_chats_pins.json).
export const libraryTakeEvents = {
  clickSearch: 2.201,
  typingStart: 2.701,
  libraryFiltered: 3.715,
  clickVideoRow: 6.281,
  // The last frame (191) that still shows the library, with the row's click ring; the next frame is the new page.
  lastLibraryFrame: 191 / 30,
  // The TED player's loading spinner is gone from here on.
  videoPageSettled: 7.85,
  clickChat: 10.908,
  conversationLoaded: 11.244,
  scrollStart: 13.257,
  scrollDone: 14.806,
  clickPin: 16.667,
  pinListed: 16.869,
  clickPinnedEntry: 19.289,
  messageHighlighted: 19.421,
} as const;

// Library: the full list while the narration says "your own library", then the search for "Altman" filters it
// to one row ("Searchable") and the row is clicked ("one click away"). Typing and the idle waits are sped up.
const libraryRecording: Recording = {
  media: {
    kind: "video",
    src: LIBRARY_TAKE_SRC,
    segments: [
      { start: 0.6, holdSeconds: 1.5 }, // the whole library at rest
      { start: 0.6, end: 2.2, speed: 1.6 }, // cursor to the search box, click
      { start: 2.2, end: 3.8, speed: 2 }, // types "Altman"; the list filters to one row
      { start: 3.8, end: 5.0, speed: 3 },
      { start: 5.0, end: 6.37, speed: 1.6 }, // cursor to the row, click
      { start: libraryTakeEvents.lastLibraryFrame, holdSeconds: 0.8 }, // held through the push
    ],
  },
  sourceSize: LIBRARY_TAKE_SIZE,
  pageRect: LIBRARY_TAKE_PAGE,
  // A: heading to the sixth row, under the header bar and above the pagination (y 170–1575).
  // B: the search box and the filtered row, y 140–916. Its right edge (x 1712) falls after the "Stage" filter's
  // label and before the unfiltered list's Tags chips, and its bottom between the unfiltered second and third
  // rows' text, so it cuts no text before or after the filter. The push lands as the list filters.
  camera: [
    { at: 0, centerX: 1440, centerY: 872.5, width: 2498 },
    { at: 1.6, centerX: 1440, centerY: 872.5, width: 2498 },
    { at: 3.25, centerX: 1022, centerY: 528, width: 1380 },
  ],
};

// Chats and pins, on the video page: the page, a push onto the Chats sidebar + chat panel while "Chat 1" is
// opened, a pan down to the answer's "Pin" and the Pinned answers list while it is pinned, and a pan up to the
// highlighted message once its pinned entry is clicked.
// Close framings share x 1474–2740: the left edge is right of the video player and transcript (both end at
// x 1467), so no dark strip or cut transcript line shows. Vertical edges sit between text lines at each rest:
// D y 340–1052 (chat list; the loaded conversation's lines 1026–1046 and 1057–1078 straddle the bottom),
// E y 683–1395 (from the chat's line gap 680–689 down past the "Pin" line, above the composer),
// F y 484–1196 (above the highlight outline at 508, bottom in the line gap 1191–1201).
const CLOSE_FRAMING_WIDTH = 1266;
const CLOSE_FRAMING_CENTER_X = 1474 + CLOSE_FRAMING_WIDTH / 2;
const chatPinsRecording: Recording = {
  media: {
    kind: "video",
    src: LIBRARY_TAKE_SRC,
    segments: [
      { start: libraryTakeEvents.videoPageSettled, end: 9.64, speed: 1.15 }, // the video page; cursor idles
      { start: 9.64, end: 10.91, speed: 1.5 }, // cursor to "Chat 1", click
      { start: 10.91, end: 11.3, speed: 1 }, // the conversation opens
      { start: 11.3, end: 13.25, speed: 3 },
      { start: 13.25, end: 14.85, speed: 2 }, // scroll up the history
      { start: 14.85, end: 16.67, speed: 2 }, // cursor to "Pin"
      { start: 16.67, end: 17.99, speed: 1 }, // click: "Pinned", the new entry lands under Pinned answers
      { start: 17.99, end: 19.29, speed: 1.6 }, // cursor to the new pinned entry
      { start: 19.29, end: 20.55, speed: 1 }, // click: the original message is highlighted
    ],
  },
  sourceSize: LIBRARY_TAKE_SIZE,
  pageRect: LIBRARY_TAKE_PAGE,
  camera: [
    { at: 0, centerX: 1440, centerY: 875, width: 2507 }, // W: title to the panels' bottom (y 170–1580)
    { at: 0.3, centerX: 1440, centerY: 875, width: 2507 },
    { at: 1.35, centerX: CLOSE_FRAMING_CENTER_X, centerY: 696, width: CLOSE_FRAMING_WIDTH }, // D
    { at: 2.9, centerX: CLOSE_FRAMING_CENTER_X, centerY: 696, width: CLOSE_FRAMING_WIDTH },
    { at: 4.1, centerX: CLOSE_FRAMING_CENTER_X, centerY: 1039, width: CLOSE_FRAMING_WIDTH }, // E
    { at: 7.05, centerX: CLOSE_FRAMING_CENTER_X, centerY: 1039, width: CLOSE_FRAMING_WIDTH },
    { at: 7.9, centerX: CLOSE_FRAMING_CENTER_X, centerY: 840, width: CLOSE_FRAMING_WIDTH }, // F
  ],
};

export const librarySceneSource: ProductSceneSource = { address: VIDSEEK_ADDRESS, recording: libraryRecording };
export const chatPinsSceneSource: ProductSceneSource = { address: VIDSEEK_ADDRESS, recording: chatPinsRecording };
