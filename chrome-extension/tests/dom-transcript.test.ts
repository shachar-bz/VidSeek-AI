// Generic transcript discovery rejects ambiguous/partial evidence and reads virtual lists.
// @vitest-environment jsdom
import { beforeEach, expect, it } from "vitest";
import { discoverDomTranscript } from "../src/dom-transcript";

beforeEach(() => {
  document.body.innerHTML = '<video src="https://example.test/movie.mp4"></video>';
  Object.defineProperty(document.querySelector("video"), "duration", { value: 100, configurable: true });
});

function panel(times = [0, 30, 60, 95], attributes = 'aria-label="Transcript"') {
  const element = document.createElement("section");
  element.innerHTML = `<div ${attributes}>${times.map((time) =>
    `<div class="row"><div><span>Spoken sentence at ${time}.</span></div><span>${Math.floor(time / 60)}:${String(time % 60).padStart(2, "0")}</span></div>`).join("")}</div>`;
  document.body.append(element);
  return element.firstElementChild as HTMLElement;
}
const cues = (result: Awaited<ReturnType<typeof discoverDomTranscript>>) => JSON.parse(result[0]!.text!).cues;

it("extracts speech and timestamps without site names or provider classes", async () => {
  const region = panel();
  region.setAttribute("lang", "he");
  region.querySelector(".row")!.insertAdjacentHTML("beforeend", '<button>Copy</button><span hidden>Retry</span>');
  const result = await discoverDomTranscript();
  expect(result).toHaveLength(1);
  expect(result[0]).toMatchObject({ format: "json", language: "he", is_visible_transcript: false });
  expect(cues(result)).toEqual([0, 30, 60, 95].map((start, i, times) => ({
    text: `Spoken sentence at ${start}.`, start, end: times[i + 1] ?? 100,
  })));
});

it("reads Panopto-shaped sibling text and clocks without depending on its identifiers", async () => {
  const region = panel([0, 30, 60, 95], 'id="transcriptTabPane"');
  region.innerHTML = [0, 30, 60, 95].map((time) => `<li id="UserCreatedTranscript-${time}">
    <div style="display:none"><a>Retry</a></div><div class="index-event-row">
    <div aria-label="User Created Transcript"></div><div class="event-text"><span>Words ${time}</span>
    <div class="event-timestamp"></div></div><div class="event-time">${Math.floor(time / 60)}:${String(time % 60).padStart(2, "0")}</div></div></li>`).join("");
  expect(cues(await discoverDomTranscript())[0]).toEqual({ text: "Words 0", start: 0, end: 30 });
});

it("uses accessible labels and shadow roots", async () => {
  const region = panel([0, 30, 60, 95], 'aria-labelledby="heading"');
  const shadow = document.body.appendChild(document.createElement("div")).attachShadow({ mode: "open" });
  shadow.innerHTML = '<h2 id="heading">כתוביות</h2>';
  shadow.append(region);
  expect(await discoverDomTranscript()).toHaveLength(1);
});

it("reads seek-button rows and hour/millisecond clocks", async () => {
  Object.defineProperty(document.querySelector("video"), "duration", { value: 3605 });
  const region = panel();
  const times = Array.from({ length: 13 }, (_, i) => `${Math.floor(i * 5 / 60)}:${String(i * 5 % 60).padStart(2, "0")}:00.250`);
  region.innerHTML = times.map((time) => `<button><span>${time}</span><span>A spoken sentence.</span></button>`).join("");
  const result = cues(await discoverDomTranscript());
  expect(result[0].start).toBe(0.25);
  expect(result.at(-1)).toMatchObject({ start: 3600.25, end: 3605 });
});

it.each([
  ["late viewport", [30, 60, 95]],
  ["early viewport", [0, 30, 60]],
  ["unordered", [0, 60, 30, 95]],
  ["duplicate clock", [0, 30, 30, 95]],
  ["outside duration", [0, 30, 101]],
] as const)("rejects %s", async (_label, times) => {
  panel([...times]);
  expect(await discoverDomTranscript()).toEqual([]);
});

it("does not turn chapter lists or hidden stale panels into captions", async () => {
  panel([0, 30, 60, 95], 'aria-label="Chapters"');
  const hidden = panel();
  hidden.style.display = "none";
  expect(await discoverDomTranscript()).toEqual([]);
});

it("requires an unambiguous player and known duration", async () => {
  panel();
  Object.defineProperty(document.querySelector("video"), "duration", { value: NaN });
  expect(await discoverDomTranscript()).toEqual([]);
  document.body.append(document.createElement("video"));
  expect(await discoverDomTranscript()).toEqual([]);
});

it("rejects an earlier page's discovery and advertisement players", async () => {
  panel();
  expect(await discoverDomTranscript("https://example.test/old-video")).toEqual([]);
  document.querySelector("video")!.title = "Advertisement";
  expect(await discoverDomTranscript()).toEqual([]);
});

function virtualPanel(disjoint = false) {
  const region = panel([30, 40, 50]);
  region.style.overflowY = "auto";
  Object.defineProperties(region, { clientHeight: { value: 100 }, scrollHeight: { value: 300 } });
  let position = 80;
  Object.defineProperty(region, "scrollTop", { get: () => position, set: (value: number) => {
    position = Math.min(200, value);
    const times = position < 70 ? [0, 10, 20, 30] : position < 140 ? [20, 30, 40, 50, 60] :
      position < 200 ? [50, 60, 70, 80] : disjoint ? [85, 90, 95] : [70, 80, 90, 95];
    region.innerHTML = times.map((time) => `<p><span>Words ${time}</span><time>${Math.floor(time / 60)}:${String(time % 60).padStart(2, "0")}</time></p>`).join("");
  } });
  return region;
}

it("collects overlapping virtualized windows and restores scroll position", async () => {
  const region = virtualPanel();
  const promise = discoverDomTranscript();
  expect(cues(await promise).map((cue: {start: number}) => cue.start)).toEqual([0,10,20,30,40,50,60,70,80,90,95]);
  expect(region.scrollTop).toBe(80);
});

it("rejects missing windows and restores scroll even when collection fails", async () => {
  const region = virtualPanel(true);
  const promise = discoverDomTranscript();
  expect(await promise).toEqual([]);
  expect(region.scrollTop).toBe(80);
});

it("abstains when the video changes during lazy loading", async () => {
  const region = virtualPanel();
  const promise = discoverDomTranscript();
  document.querySelector("video")!.src = "https://example.test/another.mp4";
  expect(await promise).toEqual([]);
  expect(region.scrollTop).toBe(80);
});
