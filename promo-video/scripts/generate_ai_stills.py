"""Generate the four AI stills of Alex with the ElevenLabs Image API from ai_stills.json.

The first still is generated from text; the others reference it so Alex looks the same
in every shot. Writes public/stills/<id>.png. Needs an API key with the
"Image & Video" permission (a Pro plan or above). After it succeeds, set
AI_STILLS_AVAILABLE = true in src/timeline.ts.
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_voiceover import PROJECT_DIR, read_api_key  # noqa: E402

API_ROOT = "https://api.elevenlabs.io/v1/flows/image"


def call_api(api_key: str, url: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def generate_still(api_key: str, plan: dict, prompt: str, reference_generation_id: str | None) -> tuple[str, bytes]:
    body = {
        "model_id": plan["modelId"],
        "prompt": f"{plan['style']} {plan['character']} {prompt}",
        "aspect_ratio": plan["aspectRatio"],
        "resolution": plan["resolution"],
    }
    if reference_generation_id:
        body["images"] = [{"type": "generation", "generation_id": reference_generation_id}]
    generation_id = call_api(api_key, API_ROOT, body)["id"]
    while True:
        time.sleep(3)
        status = call_api(api_key, f"{API_ROOT}/get/{generation_id}")
        if status["status"] == "completed":
            with urllib.request.urlopen(status["content_url"]) as response:
                return generation_id, response.read()
        if status["status"] == "failed":
            sys.exit(f"generation failed: {status.get('failure_reason')} {status.get('error_message')}")


def main() -> None:
    plan = json.loads((PROJECT_DIR / "scripts" / "ai_stills.json").read_text())
    output_dir = PROJECT_DIR / "public" / "stills"
    output_dir.mkdir(parents=True, exist_ok=True)
    api_key = read_api_key()
    reference_generation_id = None
    for still in plan["stills"]:
        generation_id, image = generate_still(api_key, plan, still["prompt"], reference_generation_id)
        reference_generation_id = reference_generation_id or generation_id
        (output_dir / f"{still['id']}.png").write_bytes(image)
        print(f"wrote {still['id']}.png")


if __name__ == "__main__":
    main()
