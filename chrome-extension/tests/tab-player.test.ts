// A cited moment only seeks the tab when that tab still shows the scanned video.
import { describe, expect, it } from "vitest";

import { isSameVideoPage } from "../src/tab-player";

describe("matching a tab to the scanned video", () => {
  it("matches a YouTube video by its id, whatever else the query carries", () => {
    expect(
      isSameVideoPage(
        "https://www.youtube.com/watch?v=abc123&t=42s&list=PL1",
        "https://www.youtube.com/watch?v=abc123",
      ),
    ).toBe(true);
    expect(
      isSameVideoPage("https://youtu.be/abc123", "https://www.youtube.com/watch?v=abc123"),
    ).toBe(true);
    expect(
      isSameVideoPage(
        "https://www.youtube.com/watch?v=other",
        "https://www.youtube.com/watch?v=abc123",
      ),
    ).toBe(false);
  });

  it("matches other sites by origin and path", () => {
    expect(
      isSameVideoPage("https://course.example/lesson/4#notes", "https://course.example/lesson/4?ref=x"),
    ).toBe(true);
    expect(isSameVideoPage("https://course.example/lesson/5", "https://course.example/lesson/4")).toBe(false);
    expect(isSameVideoPage("not a url", "https://course.example/lesson/4")).toBe(false);
  });
});
