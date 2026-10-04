"""Recognize the narration locally; no audio is sent to an external service."""
import json
import subprocess
from pathlib import Path
import numpy as np
import torch
from transformers import pipeline
folder = Path(__file__).resolve().parents[1]
audio = subprocess.check_output(['ffmpeg','-v','error','-i',str(folder/'explaning-audio.mp3'),'-f','f32le','-ac','1','-ar','16000','pipe:1'])
recognizer = pipeline('automatic-speech-recognition', model='/private/tmp/vidseek-explain-whisper', device='mps' if torch.backends.mps.is_available() else 'cpu')
result = recognizer({'array':np.frombuffer(audio,dtype=np.float32).copy(),'sampling_rate':16000}, chunk_length_s=25, stride_length_s=4, return_timestamps='word')
(folder/'assets/narration-recognition.json').write_text(json.dumps(result,indent=2))
print(result['text'])
print('Saved local word timestamps.')
