// Generate the lighter post-intro cue, leaving the opening music intact.
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";
const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = path.join(project, "public/audio/music_main_light.mp3");
if (fs.existsSync(output) && !process.argv.includes("--force")) process.exit(0);
const key = process.env.ELEVENLABS_VIDEO ?? fs.readFileSync(path.join(project, ".env"), "utf8").match(/^ELEVENLABS_VIDEO=["']?([^\r\n"']+)/m)?.[1];
if (!key) throw new Error("ELEVENLABS_VIDEO is not configured");
const plan = JSON.parse(fs.readFileSync(path.join(project, "scripts/music_plan_light.json"), "utf8"));
const response = await fetch("https://api.elevenlabs.io/v1/music?output_format=mp3_44100_192", {
  method: "POST", headers: {"xi-api-key": key, "Content-Type": "application/json"},
  body: JSON.stringify({composition_plan: plan, model_id: "music_v1"}), signal: AbortSignal.timeout(600000),
});
if (!response.ok) throw new Error(`Music generation failed: HTTP ${response.status}`);
fs.writeFileSync(output, Buffer.from(await response.arrayBuffer()));
console.log("Generated music_main_light.mp3");
