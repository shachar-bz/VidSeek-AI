import React from "react";
import { AbsoluteFill, Img, staticFile, useCurrentFrame } from "remotion";
import { CameraFrame, sourcePointToBox } from "../components/ScreenRecording";
import { ClickRipple } from "../components/ClickRipple";
import { colors, fonts } from "../theme";
import { FPS } from "../timeline";

// Real browser captures of opening a saved chat, pinning, and following its source link.
const camera = [{at: 0, centerX: 1440, centerY: 620, width: 950}];
const actions = [
  {at: 1.55, x: 1625, y: 350},
  {at: 4.0, x: 1225, y: 912},
  {at: 6.35, x: 1640, y: 495},
];
export const ChatPinsScene: React.FC = () => {
  const seconds = useCurrentFrame() / FPS;
  const file = seconds < 1.65 ? "chat_history" : seconds < 4.1 ? "chat_before_pin" : seconds < 6.45 ? "chat_pinned" : "chat_pin_open";
  return <AbsoluteFill>
    <div style={{position: "absolute", left: 65, top: 260, width: 730, fontFamily: fonts.sans}}>
      <div style={{fontSize: 60, fontWeight: 800, color: colors.ink, lineHeight: 1.15}}>Previous chats.<br/><span style={{color: colors.cobalt}}>Important answers.</span></div>
      <div style={{fontSize: 32, color: colors.inkMuted, marginTop: 32, lineHeight: 1.5}}>
        {seconds < 3.7 ? "Pick up where you left off." : seconds < 6.45 ? "Pin the answers worth keeping." : "One click back to the exact message."}
      </div>
    </div>
    <div style={{position: "absolute", left: 840, top: 85}}>
      <CameraFrame sourceWidth={2370} sourceHeight={1314} camera={camera} boxWidth={1000} boxHeight={890}
        content={<Img src={staticFile(`stills/${file}.png`)} style={{width: 2370, height: 1314}} />}>
        {actions.map(action => {
          const point = sourcePointToBox(camera, seconds, 1000, 890, action.x, action.y);
          return <ClickRipple key={action.at} x={point.x} y={point.y} at={action.at} size={65}/>;
        })}
      </CameraFrame>
    </div>
  </AbsoluteFill>;
};
