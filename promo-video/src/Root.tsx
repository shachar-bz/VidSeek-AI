import { Composition } from "remotion";
import { VidSeekPromo } from "./VidSeekPromo";
import { FPS, TOTAL_DURATION_SECONDS } from "./timeline";

export const RemotionRoot: React.FC = () => (
  <Composition
    id="VidSeekPromo"
    component={VidSeekPromo}
    durationInFrames={Math.round(TOTAL_DURATION_SECONDS * FPS)}
    fps={FPS}
    width={1920}
    height={1080}
  />
);
