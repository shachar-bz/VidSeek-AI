import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { VideoTranscript } from "../src/api/types";
import { activeTranscriptIndex } from "../src/pages/video/format";
import { TranscriptPanel } from "../src/pages/video/TranscriptPanel";
import { sourceLabel } from "../src/pages/shared";
import { languageName } from "../src/pages/video/VideoPage";
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

  it("qualifies partial timestamps, seeks from a line, and marks the spoken one", () => {
    const onSeek = vi.fn();
    render(<TranscriptPanel transcript={transcript} activeIndex={1} approximate onSeek={onSeek} />);

    expect(screen.getByText(/timestamps are approximate/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "≈0:04 Middle" }));
    expect(onSeek).toHaveBeenCalledWith(4);

    const active = screen.getByText("Middle").closest("li");
    expect(active?.className).toContain("transcript-line--active");
    expect(screen.getByText("Opening").closest("li")?.className).not.toContain("transcript-line--active");
  });

  it("offers no per-line selection or copy controls", () => {
    render(<TranscriptPanel transcript={transcript} activeIndex={-1} approximate={false} onSeek={vi.fn()} />);

    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /copy/i })).toBeNull();
  });

});

describe("video page metadata", () => {
  it("names the platform a video came from", () => {
    expect(sourceLabel({ source_site: "www.youtube.com" })).toBe("YouTube");
    expect(sourceLabel({ source_site: "www.coursera.org" })).toBe("Coursera");
  });

  it("names the transcript language rather than showing its code", () => {
    expect(languageName("en")).toBe("English");
    expect(languageName("not a language")).toBe("not a language");
  });
});
