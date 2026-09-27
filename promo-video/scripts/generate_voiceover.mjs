// Node alternative to generate_voiceover.py (same voice and synthesis settings).
// Usage: node scripts/generate_voiceover.mjs [line_id ...] [--force]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const ids = args.filter((arg) => !arg.startsWith("--"));
const script = JSON.parse(fs.readFileSync(path.join(project, "scripts/voiceover_lines.json"), "utf8"));
for (const id of ids) {
  if (!script.lines.some((line) => line.id === id)) throw new Error(`Unknown narration ID: ${id}`);
}
const key = process.env.ELEVENLABS_VIDEO ?? fs.readFileSync(path.join(project, ".env"), "utf8")
  .match(/^ELEVENLABS_VIDEO=["']?([^\r\n"']+)/m)?.[1];
if (!key) throw new Error("ELEVENLABS_VIDEO is not configured");
const output = path.join(project, "public/audio/vo");
fs.mkdirSync(output, { recursive: true });
for (const line of script.lines) {
  if (ids.length && !ids.includes(line.id)) continue;
  const file = path.join(output, `${line.id}.mp3`);
  if (fs.existsSync(file) && !args.includes("--force")) continue;
  const response = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${script.voiceId}?output_format=mp3_44100_192`, {
    method: "POST",
    headers: { "xi-api-key": key, "Content-Type": "application/json" },
    body: JSON.stringify({ text: line.text, model_id: script.modelId,
      voice_settings: { stability: 0.5, similarity_boost: 0.8, style: 0.25, use_speaker_boost: true } }),
    signal: AbortSignal.timeout(120000),
  });
  if (!response.ok) throw new Error(`Narration ${line.id} failed: HTTP ${response.status}`);
  fs.writeFileSync(file, Buffer.from(await response.arrayBuffer()));
  console.log(`Generated ${line.id}.mp3`);
}
