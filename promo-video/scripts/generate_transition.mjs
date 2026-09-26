import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(project, 'public/audio/sfx/soft_transition.mp3');
if (fs.existsSync(output) && !process.argv.includes('--force')) process.exit(0);
let key = process.env.ELEVENLABS_VIDEO;
for (const file of [path.join(project, '.env'), path.resolve(project, '../../../../promo-video/.env')]) {
  if (!key && fs.existsSync(file)) key = fs.readFileSync(file, 'utf8').match(/^ELEVENLABS_VIDEO=["']?([^\r\n"']+)/m)?.[1];
}
if (!key) throw new Error('ELEVENLABS_VIDEO is not configured');
const prompt = 'A single very soft short airy swish, a smooth gentle breath of air passing left to right, premium minimal interface transition. One continuous clean gesture with a soft attack and natural fading tail. No vinyl scratch, no stutter, no repeated pulses, no glitch, no percussion, no voices, no music, no harsh high frequencies.';
const response = await fetch('https://api.elevenlabs.io/v1/sound-generation', {
  method: 'POST', headers: {'xi-api-key': key, 'Content-Type': 'application/json'},
  body: JSON.stringify({text: prompt, duration_seconds: 0.65, prompt_influence: 0.7, model_id: 'eleven_text_to_sound_v2', loop: false}),
  signal: AbortSignal.timeout(120000),
});
if (!response.ok) throw new Error(`ElevenLabs generation failed: HTTP ${response.status}`);
fs.writeFileSync(output, Buffer.from(await response.arrayBuffer()));
console.log('Generated soft_transition.mp3');
