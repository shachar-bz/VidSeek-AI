import { act, fireEvent, render, screen } from "@testing-library/react";
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

describe("CC button visibility", () => {
  it("follows the native controls: shown while paused, hidden after idle playback, back on pointer move", async () => {
    const { container } = render(
      <VideoPlayer videoId="v1" available title="Demo" captionLines={captionLines} onTimeChange={() => undefined} />
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });

    const controls = container.querySelector(".video-player__controls")!;
    const frame = container.querySelector(".video-player__frame")!;
    const video = container.querySelector("video")!;
    expect(screen.getByRole("button", { name: /subtitles on/i })).toBeTruthy();
    expect(controls.classList.contains("video-player__controls--visible")).toBe(true);

    fireEvent.play(video);
    expect(controls.classList.contains("video-player__controls--visible")).toBe(false);

    fireEvent.pointerMove(frame);
    expect(controls.classList.contains("video-player__controls--visible")).toBe(true);
    act(() => { vi.advanceTimersByTime(3_000); });
    expect(controls.classList.contains("video-player__controls--visible")).toBe(false);

    fireEvent.pointerMove(frame);
    fireEvent.pointerLeave(frame);
    expect(controls.classList.contains("video-player__controls--visible")).toBe(false);

    fireEvent.pause(video);
    expect(controls.classList.contains("video-player__controls--visible")).toBe(true);
  });
});
