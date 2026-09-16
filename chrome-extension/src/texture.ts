/** The faint ASCII field drawn behind the login/sign up screen. */

/** The marks the field is drawn from. All are light enough to stay a texture, not a pattern. */
const MARKS = ".:-=+*~^#%";

export interface TextureShape {
  columns: number;
  rows: number;
}

/**
 * One block of the backdrop, as newline-separated rows of `columns` characters.
 *
 * Each row picks its own crowding, which is what keeps the field from reading as uniform
 * static: some rows come out nearly bare and others nearly solid, the way a page of data
 * does. `random` is a parameter so a test can pin the output down.
 */
export function textureBlock(
  { columns, rows }: TextureShape,
  random: () => number = Math.random
): string {
  const lines: string[] = [];
  for (let row = 0; row < rows; row += 1) {
    const density = 0.3 + random() * 0.55;
    let line = "";
    for (let column = 0; column < columns; column += 1) {
      line += random() < density ? MARKS[Math.floor(random() * MARKS.length)] ?? "." : " ";
    }
    lines.push(line);
  }
  return lines.join("\n");
}

/** Every character `textureBlock` can emit, for a test that has to know the alphabet. */
export const TEXTURE_CHARACTERS = `${MARKS} `;
