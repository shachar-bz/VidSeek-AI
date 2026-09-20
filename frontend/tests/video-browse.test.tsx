import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { VideoTranscript } from "../src/api/types";
import { activeTranscriptIndex } from "../src/pages/video/format";
import { TranscriptPanel } from "../src/pages/video/TranscriptPanel";
import { playbackRefreshDelay } from "../src/pages/video/VideoPlayer";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("video playback", () => {
  it("refreshes a normal signed URL five minutes before expiry", () => {
    const now = Date.parse("2026-09-20T10:00:00Z");
    expect(playbackRefreshDelay({
      url: "https://signed.example/video",
      expires_at: "2026-09-20T11:00:00Z",
      expires_in_seconds: 3600
    }, now)).toBe(55 * 60 * 1000);
  });

  it("uses a bounded midpoint refresh when the URL lifetime is shorter than the margin", () => {
    const now = Date.parse("2026-09-20T10:00:00Z");
    expect(playbackRefreshDelay({
      url: "https://signed.example/video",
      expires_at: "2026-09-20T10:02:00Z",
      expires_in_seconds: 120
    }, now)).toBe(60 * 1000);
  });
});

describe("transcript", () => {
  const transcript: VideoTranscript = {
    video_id: "video-1",
    timing_fidelity: "caption",
    lines: [
      { index: 0, start_seconds: 0, end_seconds: 3, text: "Opening" },
      { index: 1, start_seconds: 4, end_seconds: 8, text: "Middle" },
      { index: 2, start_seconds: 9, end_seconds: 12, text: "Closing" }
    ]
  };

  it("finds an active line with logarithmic lookup semantics", () => {
    expect(activeTranscriptIndex(transcript.lines, 5)).toBe(1);
    expect(activeTranscriptIndex(transcript.lines, 8.5)).toBe(-1);
  });

  it("qualifies partial timestamps while preserving seeking and exact range copy", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const onSeek = vi.fn();
    render(<TranscriptPanel transcript={transcript} currentTime={5} approximate onSeek={onSeek} />);

    expect(screen.getByText(/timestamps are approximate/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "≈0:04" }));
    expect(onSeek).toHaveBeenCalledWith(4);

    fireEvent.click(screen.getByLabelText("Select transcript line 1"));
    fireEvent.click(screen.getByLabelText("Select transcript line 2"));
    fireEvent.click(screen.getByRole("button", { name: "Copy selected (2)" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("[≈0:00] Opening\n[≈0:04] Middle"));
  });
});
