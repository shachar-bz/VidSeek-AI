import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AnswerText } from "../src/pages/video/ConversationWorkspace";
import { splitMessageCitations, timestampSeconds } from "../src/pages/video/format";

describe("timestampSeconds", () => {
  it("reads a minute and a second", () => {
    expect(timestampSeconds("12:14")).toBe(734);
  });

  it("reads an hour when the video runs that long", () => {
    expect(timestampSeconds("1:23:45")).toBe(5025);
  });
});

describe("splitMessageCitations", () => {
  it("keeps an answer without citations in one piece", () => {
    expect(splitMessageCitations("The video doesn't explain that.")).toEqual([
      { kind: "text", text: "The video doesn't explain that." }
    ]);
  });

  it("separates a citation from the claim it supports", () => {
    expect(splitMessageCitations("Deterministic methods first. [12:14] Then the model.")).toEqual([
      { kind: "text", text: "Deterministic methods first. " },
      { kind: "citation", text: "[12:14]", seconds: 734 },
      { kind: "text", text: " Then the model." }
    ]);
  });

  it("points a range at the moment it starts", () => {
    expect(splitMessageCitations("Explained here. [12:14–12:37]")).toEqual([
      { kind: "text", text: "Explained here. " },
      { kind: "citation", text: "[12:14–12:37]", seconds: 734 }
    ]);
  });

  it("leaves brackets that were never a timestamp as prose", () => {
    expect(splitMessageCitations("The speaker [the host] explains it.")).toEqual([
      { kind: "text", text: "The speaker [the host] explains it." }
    ]);
  });
});

describe("AnswerText", () => {
  it("seeks the video to the cited moment when the citation is clicked", () => {
    const onSeek = vi.fn();
    render(<AnswerText content="Used last. [12:14]" approximate={false} onSeek={onSeek} />);

    fireEvent.click(screen.getByRole("button", { name: "[12:14]" }));

    expect(onSeek).toHaveBeenCalledWith(734);
  });

  it("says a timestamp is approximate when the video's timing is partial", () => {
    render(<AnswerText content="Used last. [12:14]" approximate onSeek={vi.fn()} />);

    expect(screen.getByRole("button", { name: "[12:14]" }).getAttribute("title")).toBe(
      "Seek using this approximate timestamp"
    );
  });

  it("offers nothing to click when the answer cites nothing", () => {
    render(<AnswerText content="The video doesn't explain that." approximate={false} onSeek={vi.fn()} />);

    expect(screen.queryByRole("button")).toBeNull();
  });
});
