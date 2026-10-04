import React from "react";
import { Audio, interpolate, Sequence, staticFile } from "remotion";
import { FPS, MUSIC_DROP_SECONDS, scenes, SceneId, toFrames, TOTAL_DURATION_SECONDS, visualPlaybackRates, voiceoverCues, voiceoverDurations } from "./timeline";

import { uiSoundMoments } from "./product/uiSoundMoments";
import { uiSoundMomentsLibrary } from "./product/uiSoundMomentsLibrary";

type SoundEffectCue = { id: string; at: number; volume: number; duration?: number };

const sceneBoundaries = [
  scenes.askAnything.start,
  scenes.jumpToMoment.start,
  scenes.comments.start,
  scenes.followUps.start,
  scenes.itWatches.start,
  scenes.itReads.start,
  scenes.library.start,
  scenes.chatPins.start,
];

const moment = (scene: SceneId, local: number) => scenes[scene].start + local / (visualPlaybackRates[scene] ?? 1);

// One UI sound per interaction: a click also covers its immediate UI result.
// Answer arrivals keep their pop; trim a tail if the next interaction starts soon.
const uiMoments = [...uiSoundMoments, ...uiSoundMomentsLibrary].sort((a, b) => a.at - b.at);
const uiSoundCues: SoundEffectCue[] = uiMoments.map(({ at, kind }, index) => ({
  id: kind === "click" ? "ui_click" : "ui_pop",
  at,
  volume: kind === "click" ? 0.42 : 0.32,
  duration: Math.min(0.48, (uiMoments[index + 1]?.at ?? at + 0.52) - at - 0.04),
}));

export const soundEffectCues: SoundEffectCue[] = [
  { id: "page_flip", at: 3.15, volume: 0.3, duration: 1.2 },
  { id: "keyboard_typing", at: 5.3, volume: 0.2, duration: 1.6 },
  { id: "riser", at: 14.5, volume: 0.35 },
  { id: "impact", at: MUSIC_DROP_SECONDS, volume: 0.32 },
  // Timestamp-jump transitions between product beats.
  ...sceneBoundaries.map((at) => ({ id: "soft_transition", at: at - 0.1, volume: 0.13, duration: 0.7 })),
  // Real clicks and answers landing inside the recordings.
  { id: "ui_pop", at: moment("askAnything", 3.45), volume: 0.45 },
  { id: "ui_pop", at: moment("comments", 3), volume: 0.45 },
  { id: "ui_pop", at: moment("itWatches", 3.7), volume: 0.45 },
  { id: "soft_transition", at: moment("itWatches", 5.9), volume: 0.15, duration: 0.7 },
  ...uiSoundCues,
  { id: "shimmer", at: scenes.itReads.start + 5.3, volume: 0.35 },
  { id: "impact", at: scenes.endCard.start + 0.2, volume: 0.28 },
];

// Music levels before ducking. The main bed sits about level with the narrator between lines.
const HOOK_MUSIC_LEVEL = 0.42;
const MAIN_MUSIC_LEVEL = 0.24;

// Narration ducking: the music dips under every spoken line so the voice sits about 15 LU or more above
// the main bed (12 LU or more over the hook), measured per line with BS.1770. Everything is derived from
// voiceoverCues and voiceoverDurations, so the ducking follows the narration when cues move.
type NarrationDuckProfile = {
  depthDb: number; // How far the music dips under a line.
  attackSeconds: number; // The music starts dipping this long before a line and is fully down when it starts.
  releaseOffsetSeconds: number; // The music starts coming back this long after the line's file ends (negative = before).
  releaseSeconds: number; // ...and is back at full level this long after that.
};

// Keep the hook's gentle dip, with extra separation for the longer chatbot line.
const HOOK_MUSIC_DUCK: NarrationDuckProfile = { depthDb: -7, attackSeconds: 0.4, releaseOffsetSeconds: 0.1, releaseSeconds: 0.65 };
// Narration files end in 0.15-0.45 s of silence, so the main bed starts returning before the file ends;
// otherwise the mix falls nearly silent after the last word. Lines closer together than attack + release
// keep the music partly down between them instead of bobbing all the way up. Remotion rounds volumes to
// 1/97 steps, so the floor under a line lands on 4/97 (about -15.3 dB from MAIN_MUSIC_LEVEL).
const MAIN_MUSIC_DUCK: NarrationDuckProfile = { depthDb: -16, attackSeconds: 0.5, releaseOffsetSeconds: -0.35, releaseSeconds: 0.75 };
// Lines that need their own depth: the hook music swells under the chatbot line, so it dips further there
// to keep the line clear; the reveal follows the music drop, so a lighter dip keeps the drop's energy.
const LINE_DUCK_DEPTH_DB: Partial<Record<string, number>> = { hook_chatbot_extended: -12, reveal: -12 };

type NarrationLine = { id: string; start: number; end: number };

const smoothstep = (progress: number) => progress * progress * (3 - 2 * progress);
const clampBothEnds = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

// Gain one line applies to the music at a given second, eased at both ends so the fader move has no corners.
const lineDuckGain = (seconds: number, line: NarrationLine, profile: NarrationDuckProfile) => {
  const floorDb = LINE_DUCK_DEPTH_DB[line.id] ?? profile.depthDb;
  const releaseStart = Math.max(line.start, line.end + profile.releaseOffsetSeconds);
  if (seconds < releaseStart) {
    // Going down evenly in decibels keeps each frame's step small near the floor.
    const attack = smoothstep(interpolate(seconds, [line.start - profile.attackSeconds, line.start], [0, 1], clampBothEnds));
    return 10 ** ((floorDb * attack) / 20);
  }
  // Coming back in linear gain lifts the music promptly after the last word, then eases into full level.
  const release = smoothstep(interpolate(seconds, [releaseStart, releaseStart + profile.releaseSeconds], [1, 0], clampBothEnds));
  return 1 - (1 - 10 ** (floorDb / 20)) * release;
};

// Returns the gain multiplier for a music cue at a given second. Where two lines' dips overlap, the deeper one wins.
const createNarrationDuck = (musicStart: number, musicEnd: number, profile: NarrationDuckProfile) => {
  const lines: NarrationLine[] = voiceoverCues
    .map((cue) => ({ id: cue.id, start: cue.start, end: cue.start + voiceoverDurations[cue.id] }))
    .filter((line) => line.end > musicStart && line.start < musicEnd);
  return (seconds: number) => Math.min(1, ...lines.map((line) => lineDuckGain(seconds, line, profile)));
};

const hookMusicDuck = createNarrationDuck(0, MUSIC_DROP_SECONDS, HOOK_MUSIC_DUCK);
const mainMusicDuck = createNarrationDuck(MUSIC_DROP_SECONDS, TOTAL_DURATION_SECONDS, MAIN_MUSIC_DUCK);

export const Soundtrack: React.FC = () => {
  const mainMusicFrames = toFrames(TOTAL_DURATION_SECONDS - MUSIC_DROP_SECONDS);
  return (
    <>
      <Sequence durationInFrames={toFrames(MUSIC_DROP_SECONDS)}>
        <Audio
          src={staticFile("audio/music_hook.mp3")}
          volume={(frame) => interpolate(frame / FPS, [0, 1, 13.8, 16.9], [0, HOOK_MUSIC_LEVEL, HOOK_MUSIC_LEVEL, 0.08], { extrapolateRight: "clamp" }) * hookMusicDuck(frame / FPS)}
        />
      </Sequence>
      <Sequence from={toFrames(MUSIC_DROP_SECONDS)} durationInFrames={mainMusicFrames}>
        <Audio
          src={staticFile("audio/music_main.mp3")}
          volume={(frame) => {
            const seconds = MUSIC_DROP_SECONDS + frame / FPS;
            const ducked = MAIN_MUSIC_LEVEL * mainMusicDuck(seconds);
            const fadeOut = interpolate(seconds, [TOTAL_DURATION_SECONDS - 3, TOTAL_DURATION_SECONDS], [1, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            return ducked * fadeOut;
          }}
        />
      </Sequence>
      {voiceoverCues.map((cue) => (
        <Sequence key={cue.id} from={toFrames(cue.start)} durationInFrames={toFrames(voiceoverDurations[cue.id] + 0.3)}>
          <Audio src={staticFile(`audio/vo/${cue.id}.mp3`)} volume={1.06} />
        </Sequence>
      ))}
      {soundEffectCues.map((cue, index) => (
        <Sequence key={`${cue.id}-${index}`} from={toFrames(cue.at)} durationInFrames={toFrames(cue.duration ?? 3)}>
          <Audio src={staticFile(`audio/sfx/${cue.id}.mp3`)} volume={(frame) => cue.volume * interpolate(
            frame / FPS, [0, 0.04, (cue.duration ?? 3) - 0.12, cue.duration ?? 3], [0, 1, 1, 0],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
          )} />
        </Sequence>
      ))}
    </>
  );
};
