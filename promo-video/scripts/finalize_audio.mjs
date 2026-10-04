#!/usr/bin/env node
// Two-pass EBU R128 mastering. ffmpeg loudnorm oversamples to 192 kHz for true-peak limiting.
import { spawn } from 'node:child_process';
import { resolve } from 'node:path';
const [input, output] = process.argv.slice(2);
if (!input || !output || resolve(input) === resolve(output)) {
  console.error('Usage: node scripts/finalize_audio.mjs input.mp4 output.mp4 (distinct paths)');
  process.exit(1);
}
const run = (args) => new Promise((ok, fail) => {
  const child = spawn('ffmpeg', args, { stdio: ['ignore', 'ignore', 'pipe'] });
  let log = '';
  child.stderr.on('data', (chunk) => { log += chunk; });
  child.on('error', fail);
  child.on('close', (code) => code === 0 ? ok(log) : fail(new Error(log)));
});
const stats = (log) => {
  const blocks = [...log.matchAll(/\{\s*"input_i"[\s\S]*?\}/g)];
  if (!blocks.length) throw new Error('ffmpeg did not report loudness measurements');
  return JSON.parse(blocks.at(-1)[0]);
};
// Leave 0.2 dB headroom for AAC intersample overshoot; delivered peak is about -1.5 dBTP.
const target = 'loudnorm=I=-16:TP=-1.7:LRA=11';
const before = stats(await run(['-hide_banner', '-i', input, '-map', '0:a:0', '-af', `${target}:print_format=json`, '-f', 'null', '-']));
for (const key of ['input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset']) {
  if (!Number.isFinite(Number(before[key]))) throw new Error(`Invalid first-pass ${key}: ${before[key]}`);
}
const filter = `${target}:measured_I=${before.input_i}:measured_TP=${before.input_tp}:measured_LRA=${before.input_lra}:measured_thresh=${before.input_thresh}:offset=${before.target_offset}:linear=false:print_format=json`;
// -n protects earlier deliverables; choose a new filename or remove the intended output explicitly.
await run(['-hide_banner', '-n', '-i', input, '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy', '-af', filter, '-ar', '48000', '-c:a', 'aac', '-b:a', '320k', '-movflags', '+faststart', output]);
const after = stats(await run(['-hide_banner', '-i', output, '-map', '0:a:0', '-af', `${target}:print_format=json`, '-f', 'null', '-']));
console.log(JSON.stringify({ input, output, before: { integratedLUFS: before.input_i, truePeakDBTP: before.input_tp }, after: { integratedLUFS: after.input_i, truePeakDBTP: after.input_tp } }, null, 2));
if (Math.abs(Number(after.input_i) + 16) > 0.3 || Number(after.input_tp) > -1.45) {
  throw new Error('Encoded audio missed loudness/true-peak tolerance; inspect reported measurements');
}
