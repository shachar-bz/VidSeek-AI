import { act, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { VideoTranscript } from "../src/api/types";
import { activeTranscriptIndex, startedLineIndex } from "../src/pages/video/format";
import { TranscriptPanel } from "../src/pages/video/TranscriptPanel";

const transcript: VideoTranscript = {
  video_id: "video-1",
  timing_fidelity: "caption",
  lines: [
    { index: 0, start_seconds: 0, end_seconds: 3, text: "Opening" },
    { index: 1, start_seconds: 4, end_seconds: 8, text: "Middle" },
    { index: 2, start_seconds: 9, end_seconds: 12, text: "Closing" }
  ]
};

describe("jumping into a gap between lines", () => {
  it("syncs to the line that came before, while nothing is highlighted as spoken", () => {
    expect(activeTranscriptIndex(transcript.lines, 8.5)).toBe(-1);
    expect(startedLineIndex(transcript.lines, 8.5)).toBe(1);
    expect(startedLineIndex(transcript.lines, -1)).toBe(-1);
  });
});

describe("transcript following", () => {
  const scrollTo = vi.fn();

  beforeEach(() => {
    vi.useFakeTimers();
    scrollTo.mockClear();
    Element.prototype.scrollTo = scrollTo as unknown as typeof Element.prototype.scrollTo;
  });

  afterEach(() => {
    vi.useRealTimers();
    delete (Element.prototype as { scrollTo?: unknown }).scrollTo;
  });

  function renderPanel(activeIndex: number, syncTarget: { index: number } | null = null) {
    const view = render(
      <TranscriptPanel transcript={transcript} activeIndex={activeIndex} syncTarget={syncTarget} onSeek={vi.fn()} />
    );
    return {
      list: view.container.querySelector("ol")!,
      update: (next: number, target: { index: number } | null = syncTarget) =>
        view.rerender(<TranscriptPanel transcript={transcript} activeIndex={next} syncTarget={target} onSeek={vi.fn()} />)
    };
  }

  it("scrolls as the spoken line advances", () => {
    const { update } = renderPanel(0);
    scrollTo.mockClear();
    update(1);
    expect(scrollTo).toHaveBeenCalledTimes(1);
  });

  it("leaves a reader alone, then resumes after they stop scrolling", () => {
    const { list, update } = renderPanel(0);
    fireEvent.wheel(list);
    scrollTo.mockClear();
    update(1);
    expect(scrollTo).not.toHaveBeenCalled();

    act(() => { vi.advanceTimersByTime(6_000); });
    expect(scrollTo).toHaveBeenCalledTimes(1);
  });

  it("re-syncs on a jump even after the reader scrolled away, and even into the same line", () => {
    const { list, update } = renderPanel(1);
    fireEvent.wheel(list);
    scrollTo.mockClear();

    update(1, { index: 1 });
    expect(scrollTo).toHaveBeenCalled();

    fireEvent.wheel(list);
    scrollTo.mockClear();
    update(1, { index: 1 });
    expect(scrollTo).toHaveBeenCalled();
  });
});
