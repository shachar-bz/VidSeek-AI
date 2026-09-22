import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ConversationSummary, VideoDetail } from "../src/api/types";
import { buildCaptionsVtt } from "../src/pages/video/captions";
import { nextChatName, starterQuestionsForVideo } from "../src/pages/video/ConversationWorkspace";
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

describe("chat naming", () => {
  function summary(title: string | null): ConversationSummary {
    return {
      conversation_id: `c-${title ?? "none"}`,
      video_id: "video-1",
      title,
      created_at: "2026-09-22T10:00:00Z",
      updated_at: "2026-09-22T10:00:00Z",
      message_count: 0
    };
  }

  it("numbers the first chat and then continues past the highest number in use", () => {
    expect(nextChatName([])).toBe("Chat 1");
    expect(nextChatName([summary("Chat 1"), summary("Chat 2")])).toBe("Chat 3");
  });

  it("ignores renamed and unnamed chats when picking the next number", () => {
    expect(nextChatName([summary("Water cycle questions"), summary(null), summary("Chat 4")])).toBe("Chat 5");
  });
});

describe("caption track", () => {
  it("writes one cue per line and ends a cue before the next one starts", () => {
    const vtt = buildCaptionsVtt([
      { index: 0, start_seconds: 0, end_seconds: 6, text: "Opening line" },
      { index: 1, start_seconds: 3.25, end_seconds: 5, text: "Second line" }
    ]);

    expect(vtt.startsWith(`WEBVTT

`)).toBe(true);
    expect(vtt).toContain(`00:00:00.000 --> 00:00:03.250
Opening line`);
    expect(vtt).toContain(`00:00:03.250 --> 00:00:05.000
Second line`);
  });

  it("keeps markup and stray arrows out of cue text", () => {
    const vtt = buildCaptionsVtt([{ index: 0, start_seconds: 1, end_seconds: 2, text: "a <b> & c" }]);

    expect(vtt).toContain("a &lt;b&gt; &amp; c");
  });
});
