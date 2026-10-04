// Renders preview stills at given seconds with one bundle, for quick visual checks.
// Usage: node scripts/render_stills.mjs <output dir> <second> [second...]
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";
import path from "node:path";
import { fileURLToPath } from "node:url";

const projectDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const [outputDir, ...secondsArgs] = process.argv.slice(2);
if (!outputDir || secondsArgs.length === 0) {
  console.error("Usage: node scripts/render_stills.mjs <output dir> <second> [second...]");
  process.exit(1);
}

const serveUrl = await bundle({ entryPoint: path.join(projectDir, "src/index.ts"), publicDir: path.join(projectDir, "public") });
const browserOptions = {
  browserExecutable: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  chromeMode: "chrome-for-testing",
};
const composition = await selectComposition({ serveUrl, id: "VidSeekPromo", ...browserOptions });
for (const secondsArg of secondsArgs) {
  const seconds = Number(secondsArg);
  const frame = Math.round(seconds * composition.fps);
  const output = path.join(outputDir, `still_${seconds.toFixed(2).padStart(6, "0")}.jpg`);
  await renderStill({ composition, serveUrl, frame, output, imageFormat: "jpeg", jpegQuality: 80, scale: 0.5, ...browserOptions });
  console.log(`rendered ${output}`);
}
