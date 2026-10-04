"""Join the untouched promo v3.3 and captioned walkthrough without re-encoding video."""
import argparse
import json
import subprocess
from pathlib import Path


def run(*args):
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *map(str, args)], check=True)


def combine(root):
    promo = root / 'promo-video/out/vidseek-promo-v3.3.mp4'
    explanation = root / 'explain-video/out/vidseek-architecture-captioned.mp4'
    staging = root / 'explain-video/out/combined-staging'
    staging.mkdir(exist_ok=True)
    # The promo is stereo; duplicate the walkthrough's mono channel equally to
    # both speakers. Copy its video packets verbatim.
    stereo = staging / 'architecture-stereo.mp4'
    run('-i', explanation, '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy',
        '-video_track_timescale', '90000', '-af', 'pan=stereo|c0=c0|c1=c0', '-c:a', 'aac', '-b:a', '320k', stereo)
    manifest = staging / 'concat.txt'
    duration = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=duration', '-of', 'json', str(promo)]))['streams'][0]['duration']
    manifest.write_text(f"file '{promo.as_posix()}'\nduration {duration}\nfile '{stereo.as_posix()}'\n")
    output = root / 'vidseek-promo-and-explanation.mp4'
    run('-f', 'concat', '-safe', '0', '-i', manifest, '-map', '0:v:0', '-map', '0:a:0',
        '-c', 'copy', '-movflags', '+faststart', output)
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--media-root', type=Path, required=True)
    combine(parser.parse_args().media_root.resolve())
