import React from "react";
import { AbsoluteFill, OffthreadVideo, staticFile } from "remotion";

// One continuous take preserves the source's camera moves and internal cuts.
// Stretch 14 seconds to 14.5 to cover the outgoing transition into the question.
export const ElevenLabsHook: React.FC = () => (
  <AbsoluteFill style={{ background: "#14151b" }}>
    <OffthreadVideo
      src={staticFile("clips/Elevenlabs_vid.mp4")}
      muted
      playbackRate={14 / 14.5}
      style={{ width: "100%", height: "100%", objectFit: "cover" }}
    />
  </AbsoluteFill>
);
