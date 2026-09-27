import React from "react";
import { AbsoluteFill, interpolate, Sequence, useCurrentFrame } from "remotion";
import { fullPageCamera, ScreenRecording } from "../components/ScreenRecording";
import { colors, fonts } from "../theme";
import { FPS } from "../timeline";

// Supported-site carousel. Coursera is already ready in the supplied recording,
// so no artificial click, flash or click sound is attributed to it.
const sites = [
  { name: "YouTube", src: "youtube-login.mp4", start: 0, width: 1914, height: 1150 },
  { name: "Internet Archive", src: "Internet_archive-login.mp4", start: 0.3, width: 1916, height: 1150 },
  { name: "TED", src: "ted-login.mp4", start: 37.2, width: 1918, height: 1152 },
  { name: "Coursera", src: "coursera-login.mp4", start: 0, width: 1916, height: 1148 },
  { name: "Moodle / Panopto", src: "moodle-login.mp4", start: 0, width: 1914, height: 1148 },
];
const STEP = 1.05;
const SiteCard: React.FC<{site: typeof sites[number]}> = ({site}) => {
  const seconds = useCurrentFrame() / FPS;
  const enter = interpolate(seconds, [0, 0.16], [1, 0], {extrapolateRight: "clamp"});
  return <div style={{position: "absolute", left: 180, top: 100, transform: `translateX(${enter * 160}px)`, opacity: 1 - enter}}>
    <ScreenRecording src={`clips/${site.src}`} sourceWidth={site.width} sourceHeight={site.height}
      segments={[{start: site.start, end: site.start + 2.5, speed: 1}]}
      camera={fullPageCamera(site.width, site.height, 1560, 830)} boxWidth={1560} boxHeight={830} borderRadius={16} />
  </div>;
};
export const FindVideoMontage: React.FC = () => {
  const seconds = useCurrentFrame() / FPS;
  const active = Math.min(sites.length - 1, Math.floor(seconds / STEP));
  return <AbsoluteFill style={{fontFamily: fonts.sans}}>
    <div style={{position: "absolute", top: 20, width: "100%", textAlign: "center", fontSize: 46, fontWeight: 800, color: colors.ink}}>Across the sites you already watch.</div>
    {sites.map((site, index) => <Sequence key={site.src} from={Math.round(index * STEP * FPS)} durationInFrames={Math.round((index === 4 ? 2.1 : STEP) * FPS)}>
      <SiteCard site={site} />
    </Sequence>)}
    <div style={{position: "absolute", left: 70, right: 70, bottom: 100, display: "flex", justifyContent: "center", gap: 18}}>
      {sites.map((site, index) => <div key={site.name} style={{padding: "13px 25px", borderRadius: 999, background: active === index ? colors.cobalt : "white", color: active === index ? "white" : colors.inkMuted, fontSize: 27, fontWeight: 700, border: `1px solid ${colors.mistBorder}`}}>{site.name}</div>)}
    </div>
    <div style={{position: "absolute", bottom: 67, width: "100%", textAlign: "center", color: colors.inkMuted, fontSize: 20}}>And many more video sites</div>
  </AbsoluteFill>;
};
