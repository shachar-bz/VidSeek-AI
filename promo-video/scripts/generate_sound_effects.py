"""Generate the promo's sound effects with ElevenLabs from sound_effects.json.

Writes public/audio/sfx/<id>.mp3. Existing files are skipped unless --force is given.
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_voiceover import PROJECT_DIR, read_api_key  # noqa: E402


def main() -> None:
    force = "--force" in sys.argv
    only_ids = {arg for arg in sys.argv[1:] if not arg.startswith("--")}
    effects = json.loads((PROJECT_DIR / "scripts" / "sound_effects.json").read_text())
    output_dir = PROJECT_DIR / "public" / "audio" / "sfx"
    output_dir.mkdir(parents=True, exist_ok=True)
    api_key = read_api_key()
    for effect in effects:
        output_path = output_dir / f"{effect['id']}.mp3"
        if (only_ids and effect["id"] not in only_ids) or (output_path.exists() and not force):
            continue
        request = urllib.request.Request(
            "https://api.elevenlabs.io/v1/sound-generation",
            data=json.dumps({"text": effect["text"], "duration_seconds": effect["duration_seconds"], "prompt_influence": 0.6}).encode(),
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            output_path.write_bytes(response.read())
        print(f"wrote {output_path.name}")


if __name__ == "__main__":
    main()
