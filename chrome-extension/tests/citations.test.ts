// Cited timestamps are split out of an answer so each one can seek the video.
import { describe, expect, it } from "vitest";

import { formatTimestamp, splitAnswerCitations } from "../src/citations";

describe("answer citations", () => {
  it("splits single times and ranges out of the text", () => {
    expect(splitAnswerCitations("See [1:05] and [1:02:03 – 1:04:00].")).toEqual([
      { kind: "text", text: "See " },
      { kind: "citation", text: "[1:05]", seconds: 65 },
      { kind: "text", text: " and " },
      { kind: "citation", text: "[1:02:03 – 1:04:00]", seconds: 3723 },
      { kind: "text", text: "." },
    ]);
  });

  it("leaves brackets that are not times alone", () => {
    expect(splitAnswerCitations("A list [1] and [1:75].")).toEqual([
      { kind: "text", text: "A list [1] and [1:75]." },
    ]);
  });

  it("formats seconds the way the agent cites them", () => {
    expect(formatTimestamp(65.9)).toBe("1:05");
    expect(formatTimestamp(3723)).toBe("1:02:03");
  });
});
