// The ad's master timeline, in seconds. The main music cue starts on its drop at
// MUSIC_DROP_SECONDS and runs at 120 BPM, so beats land every 0.5 s after it.
export const FPS = 30;
export const TOTAL_DURATION_SECONDS = 100;
export const MUSIC_DROP_SECONDS = 17;
export const BEAT_SECONDS = 0.5;

export const beat = (beatIndex: number) => MUSIC_DROP_SECONDS + beatIndex * BEAT_SECONDS;
export const toFrames = (seconds: number) => Math.round(seconds * FPS);

export type SceneId =
  | "hookFilm"
  | "hookQuestion"
  | "reveal"
  | "findVideo"
  | "askAnything"
  | "jumpToMoment"
  | "comments"
  | "followUps"
  | "itWatches"
  | "itReads"
  | "library"
  | "callback"
  | "endCard";

export const scenes: Record<SceneId, { start: number; end: number }> = {
  hookFilm: { start: 0, end: 14.2 },
  hookQuestion: { start: 14.2, end: 17 },
  reveal: { start: 17, end: 19.5 },
  findVideo: { start: 19.5, end: 27.5 },
  askAnything: { start: 27.5, end: 34 },
  jumpToMoment: { start: 34, end: 40 },
  comments: { start: 40, end: 46.5 },
  followUps: { start: 46.5, end: 56.5 },
  itWatches: { start: 56.5, end: 65 },
  itReads: { start: 65, end: 76 },
  library: { start: 76, end: 83 },
  callback: { start: 83, end: 88 },
  endCard: { start: 88, end: 100 },
};

// Narration cues: file name in public/audio/vo and the second it starts.
export const voiceoverCues: { id: string; start: number; caption: string }[] = [
  { id: "hook_intro_v2", start: 0.15, caption: "Alex wants to understand a difficult topic." },
  { id: "hook_book_v2", start: 3.15, caption: "The textbook? Overwhelming." },
  { id: "hook_chatbot_v2", start: 5.25, caption: "The chatbot sounds confident. But the answer is wrong." },
  { id: "hook_video_v2", start: 10.25, caption: "The video? Good luck finding the right moment." },
  { id: "hook_question", start: 14.4, caption: "What if Alex could just… ask the video?" },
  { id: "reveal", start: 17.6, caption: "Meet VidSeek AI." },
  { id: "find_video", start: 20.0, caption: "One click, on almost any video site. No captions? VidSeek writes them." },
  { id: "ask_anything", start: 28.0, caption: "Ask anything. Get a clear answer, with the exact moments behind it." },
  { id: "jump_to_moment", start: 34.6, caption: "Click a moment, and you're right there." },
  { id: "comments", start: 40.4, caption: "Curious what everyone else thought? It reads the comments, too." },
  { id: "follow_ups", start: 47.0, caption: "Ask a follow-up. Then another. Go as deep as you want." },
  { id: "it_watches", start: 57.0, caption: "And it doesn't just listen. It watches." },
  { id: "it_reads", start: 65.5, caption: "It even reads the slides, and what's written on the board." },
  { id: "library", start: 76.5, caption: "Every video lands in your own library. Searchable, and always one click away." },
  { id: "callback", start: 83.6, caption: "Alex got it. In seconds." },
  { id: "tagline", start: 89.0, caption: "VidSeek AI. Ask any video anything." },
];

export const voiceoverDurations: Record<string, number> = {
  hook_intro_v2: 2.351, hook_book_v2: 1.620, hook_chatbot_v2: 2.821, hook_video_v2: 2.638,
  hook_question: 2.28, reveal: 1.35,
  find_video: 4.09, ask_anything: 3.99, jump_to_moment: 1.76, comments: 3.53, follow_ups: 2.93,
  it_watches: 1.95, it_reads: 2.74, library: 4.41, callback: 1.72, tagline: 2.32,
};

// Set to true once the four AI stills of Alex exist in public/stills
// (alex_book.png, alex_chatbot.png, alex_video.png, alex_relieved.png).
export const AI_STILLS_AVAILABLE = false;
