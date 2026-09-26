"""Compose the promo soundtrack with ElevenLabs Music.

Two cues: music_plan_hook.json (the tense bed under the hook) and
music_plan_main.json (starts on the drop and runs to the end card). Writes
public/audio/music_<cue>.mp3. Pass cue names to regenerate only those.
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_voiceover import PROJECT_DIR, read_api_key  # noqa: E402


def compose_cue(cue_name: str) -> None:
    plan = json.loads((PROJECT_DIR / "scripts" / f"music_plan_{cue_name}.json").read_text())
    request = urllib.request.Request(
        "https://api.elevenlabs.io/v1/music?output_format=mp3_44100_192",
        data=json.dumps({"composition_plan": plan, "model_id": "music_v1"}).encode(),
        headers={"xi-api-key": read_api_key(), "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        audio = response.read()
    output_path = PROJECT_DIR / "public" / "audio" / f"music_{cue_name}.mp3"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio)
    print(f"wrote {output_path} ({len(audio)} bytes)")


def main() -> None:
    for cue_name in sys.argv[1:] or ["hook", "main"]:
        compose_cue(cue_name)


if __name__ == "__main__":
    main()
