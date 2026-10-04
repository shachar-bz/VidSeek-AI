import { scenes } from "../timeline";
import { chatPinsSceneSource, librarySceneSource, libraryTakeEvents } from "./libraryChatsRecording";
import type { Recording } from "./recordings";
import { outputSecondsAtSourceTime } from "./recordingTiming";

// Absolute composition seconds of the visible clicks (and the pin landing) in the library and chatPins
// scenes, derived from the take's event log through each scene's segments, so they follow any re-cut.
// Both scenes play at 1x scene time (no visualPlaybackRates entry).
const absoluteSeconds = (sceneStart: number, recording: Recording, sourceSeconds: number) => {
  if (recording.media.kind !== "video") throw new Error("library take scenes are video recordings");
  return Math.round((sceneStart + outputSecondsAtSourceTime(recording.media.segments, sourceSeconds)) * 1000) / 1000;
};

const library = (sourceSeconds: number) => absoluteSeconds(scenes.library.start, librarySceneSource.recording, sourceSeconds);
const chatPins = (sourceSeconds: number) => absoluteSeconds(scenes.chatPins.start, chatPinsSceneSource.recording, sourceSeconds);

export const uiSoundMomentsLibrary: { at: number; kind: "click" | "pop"; scene: string }[] = [
  { at: library(libraryTakeEvents.clickSearch), kind: "click", scene: "library" },
  { at: library(libraryTakeEvents.clickVideoRow), kind: "click", scene: "library" },
  { at: chatPins(libraryTakeEvents.clickChat), kind: "click", scene: "chatPins" },
  { at: chatPins(libraryTakeEvents.clickPin), kind: "click", scene: "chatPins" },
  { at: chatPins(libraryTakeEvents.pinListed), kind: "pop", scene: "chatPins" },
  { at: chatPins(libraryTakeEvents.clickPinnedEntry), kind: "click", scene: "chatPins" },
];
