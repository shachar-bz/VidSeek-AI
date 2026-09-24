"""Runs Surya OCR in its own Python environment and answers read requests over stdin and stdout.

This file is not part of the backend at runtime. `engine.py` starts it with the interpreter of
the separate environment Surya is installed in (`VIDSEEK_OCR_PYTHON`, see `requirements.txt`),
because Surya needs a newer torch and an older Pillow than the backend runs on. So it imports
nothing from `backend`, only the standard library, Pillow and Surya.

The protocol is one JSON message per line:

    worker -> {"ready": true, "surya_version": "0.22.1"}         once, after the models load
           or {"fatal": "..."}                                    and exits, when they cannot
    engine -> {"id": 7, "images": ["<base64 PNG>", ...]}
    worker -> {"id": 7, "pages": [{"blocks": [{"html", "label", "confidence"}, ...]}, ...]}
           or {"id": 7, "error": "..."}                           the worker carries on

Surya's text detector runs first, on the CPU, and a frame it finds no text line on is answered
with no blocks without ever reaching the OCR model. The frames that do show text are read
whole-page by Surya's VLM, which runs under llama.cpp's `llama-server`; Surya starts that
server itself and stops it when this process exits, which is when the engine closes stdin.

Surya logs to stdout, which is the protocol channel here, so everything but the protocol is
redirected to stderr before Surya is imported; the engine drains stderr into its own log.
"""

from __future__ import annotations

import base64
import io
import json
import sys
import traceback
from importlib.metadata import version


def main() -> int:
    protocol = sys.stdout
    sys.stdout = sys.stderr
    try:
        from PIL import Image
        from surya.detection import DetectionPredictor
        from surya.inference import SuryaInferenceManager
        from surya.recognition import RecognitionPredictor

        detector = DetectionPredictor.local()
        manager = SuryaInferenceManager()
        manager.start()
        recognizer = RecognitionPredictor(manager)
    except Exception as error:
        traceback.print_exc()
        _send(protocol, {"fatal": f"{type(error).__name__}: {error}"})
        return 1
    _send(protocol, {"ready": True, "surya_version": version("surya-ocr")})

    for line in sys.stdin.buffer:
        if not line.strip():
            continue
        request_id = None
        try:
            request = json.loads(line)
            request_id = request.get("id")
            images = [
                Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGB")
                for encoded in request["images"]
            ]
            _send(protocol, {"id": request_id, "pages": read_pages(images, detector, recognizer)})
        except Exception as error:
            traceback.print_exc()
            _send(protocol, {"id": request_id, "error": f"{type(error).__name__}: {error}"})
    manager.stop()
    return 0


def read_pages(images, detector, recognizer) -> list[dict]:
    """One page of blocks per image, in reading order; no blocks where no text line was found."""
    pages: list[dict] = [{"blocks": []} for _ in images]
    detections = detector(images)
    with_text = [position for position, found in enumerate(detections) if found.bboxes]
    if not with_text:
        return pages
    results = recognizer([images[position] for position in with_text], full_page=True)
    for position, result in zip(with_text, results):
        pages[position] = {
            "blocks": [
                {"html": block.html, "label": block.label, "confidence": block.confidence}
                for block in sorted(result.blocks, key=lambda block: block.reading_order)
                if block.html and not block.skipped and not block.error
            ]
        }
    return pages


def _send(stream, message: dict) -> None:
    # ASCII with escapes, so Hebrew arrives intact whatever encoding the pipe was given.
    stream.write(json.dumps(message) + "\n")
    stream.flush()


if __name__ == "__main__":
    sys.exit(main())
