"""Generate one narration file per line in voiceover_lines.json with ElevenLabs TTS.

Reads ELEVENLABS_VIDEO from promo-video/.env (or the environment) and writes
public/audio/vo/<line id>.mp3. Existing files are skipped unless --force is given.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


def read_api_key() -> str:
    if os.environ.get("ELEVENLABS_VIDEO"):
        return os.environ["ELEVENLABS_VIDEO"]
    for env_path in (PROJECT_DIR / ".env", PROJECT_DIR.parents[3] / "promo-video" / ".env"):
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("ELEVENLABS_VIDEO="):
                    return line.split("=", 1)[1].strip().strip('"')
    sys.exit("ELEVENLABS_VIDEO not found in environment or .env")


def synthesize_line(api_key: str, voice_id: str, model_id: str, text: str) -> bytes:
    request = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_192",
        data=json.dumps({
            "text": text,
            "model_id": model_id,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.25, "use_speaker_boost": True},
        }).encode(),
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return response.read()


def main() -> None:
    force = "--force" in sys.argv
    only_ids = {arg for arg in sys.argv[1:] if not arg.startswith("--")}
    script = json.loads((PROJECT_DIR / "scripts" / "voiceover_lines.json").read_text())
    output_dir = PROJECT_DIR / "public" / "audio" / "vo"
    output_dir.mkdir(parents=True, exist_ok=True)
    api_key = read_api_key()
    for line in script["lines"]:
        if only_ids and line["id"] not in only_ids:
            continue
        output_path = output_dir / f"{line['id']}.mp3"
        if output_path.exists() and not force:
            continue
        output_path.write_bytes(synthesize_line(api_key, script["voiceId"], script["modelId"], line["text"]))
        print(f"wrote {output_path.name}")


if __name__ == "__main__":
    main()
