import React from "react";
import { AbsoluteFill, Freeze, interpolate, Sequence, useCurrentFrame } from "remotion";
import { Headline, HeadlineSwap } from "../components/HeadlineSwap";
import { ProductWindow } from "../components/ProductWindow";
import { AddressLabel, findVideoTiles, findVideoTileStarts, productSceneSources } from "../product/recordings";
import {
  HEADLINE,
  HEADLINE_ENTRANCE,
  HEADLINE_EXIT,
  Push,
  pushProgress,
  pushWindow,
  SECTION_RENDER_END,
  WINDOW,
  windowRectFor,
  windowTransformAt,
} from "../product/stage";
import { colors, fonts } from "../theme";
import { SceneId, scenes, toFrames, visualPlaybackRates } from "../timeline";
import {
  AskAnythingContent,
  ChatPinsContent,
  CommentsContent,
  FindVideoTileContent,
  FollowUpsContent,
  ItReadsContent,
  ItWatchesContent,
  JumpToMomentContent,
  LibraryContent,
} from "./ProductWindowScenes";

// Push lengths, in frames. Each push is centered on its boundary (a 0.5 s beat).
const MONTAGE_PUSH_FRAMES = 8;
const GROW_PUSH_FRAMES = 14; // the montage's last site → askAnything, combined with the window growing
const PRODUCT_PUSH_FRAMES = 12;

const HEADLINES: Record<"findVideo" | ProductSceneId, Headline> = {
  findVideo: { lead: "Across the sites", accent: "you already watch." },
  askAnything: { lead: "ASK", accent: "ANYTHING." },
  jumpToMoment: { lead: "CLICK.", accent: "JUMP." },
  comments: { lead: "WHAT DO VIEWERS", accent: "THINK?" },
  followUps: { lead: "GO", accent: "DEEPER." },
  itWatches: { lead: "IT", accent: "WATCHES." },
  itReads: { lead: "IT", accent: "READS." },
  library: { lead: "YOUR LIBRARY.", accent: "ALL IN ONE PLACE." },
  chatPins: { lead: "PREVIOUS CHATS.", accent: "IMPORTANT ANSWERS." },
};

type ProductSceneId = keyof typeof productSceneSources;

const PRODUCT_SCENES: { id: ProductSceneId & SceneId; Content: React.FC }[] = [
  { id: "askAnything", Content: AskAnythingContent },
  { id: "jumpToMoment", Content: JumpToMomentContent },
  { id: "comments", Content: CommentsContent },
  { id: "followUps", Content: FollowUpsContent },
  { id: "itWatches", Content: ItWatchesContent },
  { id: "itReads", Content: ItReadsContent },
  { id: "library", Content: LibraryContent },
  { id: "chatPins", Content: ChatPinsContent },
];

// Everything that plays inside the window, in order. Each item pushes the previous one out.
type WindowItem = {
  key: string;
  startFrame: number;
  pushIn: Push | null;
  address: AddressLabel;
  headline: Headline;
  playbackRate: number;
  Content: React.FC;
};

const WINDOW_ITEMS: WindowItem[] = [
  ...findVideoTiles.map((tile, index): WindowItem => ({
    key: `site-${tile.chipLabel}`,
    startFrame: toFrames(findVideoTileStarts[index]),
    pushIn: index === 0 ? null : { boundaryFrame: toFrames(findVideoTileStarts[index]), durationInFrames: MONTAGE_PUSH_FRAMES },
    address: tile.address,
    headline: HEADLINES.findVideo,
    playbackRate: 1,
    Content: () => <FindVideoTileContent tile={tile} />,
  })),
  ...PRODUCT_SCENES.map(({ id, Content }, index): WindowItem => ({
    key: id,
    startFrame: toFrames(scenes[id].start),
    pushIn: { boundaryFrame: toFrames(scenes[id].start), durationInFrames: index === 0 ? GROW_PUSH_FRAMES : PRODUCT_PUSH_FRAMES },
    address: productSceneSources[id].address,
    headline: HEADLINES[id],
    playbackRate: visualPlaybackRates[id] ?? 1,
    Content,
  })),
];

const MONTAGE_PUSHES = WINDOW_ITEMS.slice(1, findVideoTiles.length).map((item) => item.pushIn as Push);
const GROW_PUSH = WINDOW_ITEMS[findVideoTiles.length].pushIn as Push;
const PRODUCT_PUSHES = WINDOW_ITEMS.slice(findVideoTiles.length + 1).map((item) => item.pushIn as Push);
const SECTION_END_FRAME = toFrames(SECTION_RENDER_END);

const visibleRange = (index: number) => {
  const item = WINDOW_ITEMS[index];
  const next = WINDOW_ITEMS[index + 1];
  return {
    from: item.pushIn ? pushWindow(item.pushIn).from : item.startFrame,
    to: next?.pushIn ? pushWindow(next.pushIn).to : SECTION_END_FRAME,
  };
};

// The item's horizontal offset: entering from the right, then leaving to the left, fully opaque.
const pushOffset = (index: number, frame: number) => {
  const item = WINDOW_ITEMS[index];
  const next = WINDOW_ITEMS[index + 1];
  if (item.pushIn && frame < pushWindow(item.pushIn).to) return (1 - pushProgress(item.pushIn, frame)) * WINDOW.contentWidth;
  if (next?.pushIn && frame > pushWindow(next.pushIn).from) return -pushProgress(next.pushIn, frame) * WINDOW.contentWidth;
  return 0;
};

const RatedContent: React.FC<{ item: WindowItem }> = ({ item }) => (
  <Sequence layout="none" playbackRate={item.playbackRate}>
    <item.Content />
  </Sequence>
);

const WindowItemLayer: React.FC<{ index: number; frame: number }> = ({ index, frame }) => {
  const item = WINDOW_ITEMS[index];
  const { from, to } = visibleRange(index);
  if (frame < from || frame >= to) return null;
  const offset = pushOffset(index, frame);
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        top: 0,
        width: WINDOW.contentWidth,
        height: WINDOW.contentHeight,
        overflow: "hidden",
        background: colors.white,
        transform: `translateX(${offset}px)`,
        // A hairline marks the seam between the outgoing and incoming page.
        boxShadow: offset > 0 ? `-1px 0 0 ${colors.mistBorder}, -18px 0 36px rgba(30,36,90,0.10)` : "none",
      }}
    >
      {from < item.startFrame && (
        // Before its start, the incoming page holds its first frame while it slides in.
        <Sequence from={from} durationInFrames={item.startFrame - from} layout="none">
          <Freeze frame={0}>
            <RatedContent item={item} />
          </Freeze>
        </Sequence>
      )}
      <Sequence from={item.startFrame} durationInFrames={to - item.startFrame} layout="none">
        <RatedContent item={item} />
      </Sequence>
    </div>
  );
};

// The swap in progress at a frame (or the settled state between swaps).
type Swap<T> = { push: Push; from: T; to: T };
const swapStateAt = <T,>(swaps: Swap<T>[], frame: number, initial: T): { from: T; to: T; progress: number } => {
  let settled = initial;
  for (const swap of swaps) {
    const { from, to } = pushWindow(swap.push);
    if (frame >= from && frame < to) return { from: swap.from, to: swap.to, progress: pushProgress(swap.push, frame) };
    if (frame >= to) settled = swap.to;
  }
  return { from: settled, to: settled, progress: 1 };
};

const ADDRESS_SWAPS: Swap<AddressLabel>[] = WINDOW_ITEMS.slice(1).map((item, index) => ({
  push: item.pushIn as Push,
  from: WINDOW_ITEMS[index].address,
  to: item.address,
}));

const HEADLINE_SWAPS: Swap<Headline | null>[] = [
  { push: HEADLINE_ENTRANCE, from: null, to: HEADLINES.findVideo },
  ...WINDOW_ITEMS.slice(1)
    .map((item, index) => ({ push: item.pushIn as Push, from: WINDOW_ITEMS[index].headline, to: item.headline }))
    .filter((swap) => swap.from !== swap.to),
  { push: HEADLINE_EXIT, from: HEADLINES.chatPins, to: null },
];

// Supported-site chips under the pulled-back window; the active site is cobalt.
const SiteChips: React.FC<{ top: number; opacity: number; activeIndex: number }> = ({ top, opacity, activeIndex }) => (
  <div style={{ position: "absolute", left: 0, width: 1920, top, opacity, fontFamily: fonts.sans }}>
    <div style={{ display: "flex", justifyContent: "center", gap: 16 }}>
      {findVideoTiles.map((tile, index) => (
        <div
          key={tile.chipLabel}
          style={{
            padding: "11px 24px",
            borderRadius: 999,
            background: activeIndex === index ? colors.cobalt : colors.white,
            color: activeIndex === index ? colors.white : colors.inkMuted,
            fontSize: 25,
            fontWeight: 700,
            border: `1px solid ${activeIndex === index ? colors.cobalt : colors.mistBorder}`,
          }}
        >
          {tile.chipLabel}
        </div>
      ))}
    </div>
    <div style={{ marginTop: 14, textAlign: "center", color: colors.inkMuted, fontSize: 21, fontWeight: 500 }}>And many more video sites</div>
  </div>
);

// One continuous browser window from findVideo to the end of chatPins: page content pushes sideways
// inside it on the beat, the headline above it swaps with a mask wipe, and the window itself dips on
// each push like a camera easing back.
export const ProductSection: React.FC = () => {
  const frame = useCurrentFrame();
  if (frame < WINDOW_ITEMS[0].startFrame || frame >= SECTION_END_FRAME) return null;
  const transform = windowTransformAt(frame, { montage: MONTAGE_PUSHES, product: PRODUCT_PUSHES, growToFullSize: GROW_PUSH });
  const rect = windowRectFor(transform);
  const address = swapStateAt(ADDRESS_SWAPS, frame, WINDOW_ITEMS[0].address);
  const headline = swapStateAt(HEADLINE_SWAPS, frame, null);
  const activeSite = MONTAGE_PUSHES.filter((push) => frame >= push.boundaryFrame).length;
  const growWindow = pushWindow(GROW_PUSH);
  const chipsOpacity = transform.opacity * interpolate(frame, [growWindow.from - 2, growWindow.from + 6], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill>
      {chipsOpacity > 0 && <SiteChips top={rect.bottom + 24} opacity={chipsOpacity} activeIndex={activeSite} />}
      <ProductWindow transform={transform} address={address}>
        {WINDOW_ITEMS.map((item, index) => (
          <WindowItemLayer key={item.key} index={index} frame={frame} />
        ))}
      </ProductWindow>
      <HeadlineSwap left={rect.left} bottom={rect.top - HEADLINE.gapAboveWindow} {...headline} />
    </AbsoluteFill>
  );
};
