import { describe, expect, it } from "vitest";

import { TEXTURE_CHARACTERS, textureBlock } from "../src/texture";

/** A small deterministic source, so a block can be compared against itself. */
function seededRandom(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state * 1664525 + 1013904223) % 4294967296;
    return state / 4294967296;
  };
}

describe("login backdrop texture", () => {
  it("fills exactly the requested grid", () => {
    const rows = textureBlock({ columns: 40, rows: 12 }, seededRandom(7)).split("\n");

    expect(rows).toHaveLength(12);
    expect(rows.every((row) => row.length === 40)).toBe(true);
  });

  it("draws only from its own alphabet", () => {
    const block = textureBlock({ columns: 60, rows: 30 }, seededRandom(11));

    expect([...block.replace(/\n/g, "")].every((mark) => TEXTURE_CHARACTERS.includes(mark))).toBe(true);
  });

  it("is reproducible for a given random source", () => {
    const shape = { columns: 20, rows: 8 };

    expect(textureBlock(shape, seededRandom(3))).toBe(textureBlock(shape, seededRandom(3)));
  });

  it("varies how crowded each row is", () => {
    // A field of uniform density reads as static; the rows are meant to differ.
    const rows = textureBlock({ columns: 80, rows: 40 }, seededRandom(5)).split("\n");
    const marksPerRow = rows.map((row) => row.replace(/ /g, "").length);

    expect(Math.max(...marksPerRow) - Math.min(...marksPerRow)).toBeGreaterThan(10);
  });
});
