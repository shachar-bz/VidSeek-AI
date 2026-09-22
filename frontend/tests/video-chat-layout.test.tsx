import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { VideoDetail } from "../src/api/types";
import { starterQuestionsForVideo } from "../src/pages/video/ConversationWorkspace";
import { VideoDetailsTabs } from "../src/pages/video/OutlineInsights";

const video: VideoDetail = {
  video_id: "video-1",
  title: "The Water Cycle",
  custom_title: null,
  original_title: "The Water Cycle",
  source_site: "example.com",
  source_url: "https://example.com/video",
  duration_seconds: 600,
  tags: [],
  added_at: "2026-09-22T10:00:00Z",
  stage: "ready",
  transcript_source: "captions",
  transcript_language: "en",
  transcript_timing_fidelity: "caption",
  conversation_count: 0,
  insights: {
    summary: "Water moves continuously through the atmosphere and the ground.",
    takeaways: ["Evaporation", "Condensation", "Precipitation", "Collection", "The cycle repeats"],
    suggested_questions: ["How does condensation lead to precipitation?"]
  }
};

describe("video chat layout", () => {
  it("puts all five key points under the Summary tab", () => {
    render(
      <VideoDetailsTabs
        video={video}
        transcript={null}
        outline={null}
        activeLineIndex={-1}
        approximate={false}
        onSeek={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole("tab", { name: "Summary" }));

    expect(screen.getByRole("heading", { name: "5 key points" })).toBeTruthy();
    for (const point of video.insights?.takeaways ?? []) {
      expect(screen.getByText(point)).toBeTruthy();
    }
  });

  it("always offers three starter questions, preserving generated questions first", () => {
    const questions = starterQuestionsForVideo(video);

    expect(questions).toHaveLength(3);
    expect(questions[0]).toBe("How does condensation lead to precipitation?");
  });
});
