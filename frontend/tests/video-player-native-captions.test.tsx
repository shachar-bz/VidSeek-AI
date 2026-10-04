import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VideoPlayer } from "../src/pages/video/VideoPlayer";

vi.mock("../src/api/video", () => ({
  getPlaybackUrl: vi.fn().mockResolvedValue({
    url: "https://signed.example/video",
    expires_at: "2099-01-01T00:00:00Z",
    expires_in_seconds: 3600
  })
}));

const captionLines = [{ index: 0, start_seconds: 0, end_seconds: 3, text: "Opening" }];

beforeEach(() => {
  vi.useFakeTimers();
  URL.createObjectURL = vi.fn(() => "blob:captions");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("native caption controls", () => {
  it("provides a caption track with native controls and no controls overlay", async () => {
    const { container } = render(
      <VideoPlayer videoId="v1" available title="Demo" captionLines={captionLines} captionLanguage="he" onTimeChange={() => undefined} />
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });

    const video = container.querySelector("video")!;
    const track = video.querySelector("track")!;
    expect(video.controls).toBe(true);
    expect(track.kind).toBe("captions");
    expect(track.src).toBe("blob:captions");
    expect(track.srclang).toBe("he");
    expect(screen.queryByRole("button", { name: /subtitles|full screen/i })).toBeNull();
    expect(container.querySelector(".video-player__controls")).toBeNull();
    expect(container.querySelector(".video-player__fullscreen-hitbox")).toBeNull();
  });
});
