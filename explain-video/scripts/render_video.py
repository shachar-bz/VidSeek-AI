"""Render the plan with FFmpeg, original narration, and recut authentic recordings.

Usage: python scripts/render_video.py --media-root /path/to/main/checkout
Requires ffmpeg and ffprobe. Does not control any UI or contact external services.
"""
import argparse, json, subprocess, math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FPS=30
OUT=ROOT/'out'; OUT.mkdir(exist_ok=True)
PARTS=OUT/'segments'; PARTS.mkdir(exist_ok=True)
RECORDINGS=ROOT/'recordings'; RECORDINGS.mkdir(exist_ok=True)
def run(args):
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',*map(str,args)],check=True)
def frames(t):return round(t*FPS)
def encode(output,inputs,filters,n):
    run([*inputs,'-filter_complex',filters,'-map','[v]','-an','-frames:v',n,'-r',FPS,'-c:v','libx264','-preset','veryfast','-tune','stillimage','-crf','18','-pix_fmt','yuv420p','-video_track_timescale','30000',output])
def prepare(media):
    ext=media/'promo-video/public/clips/v3/coursera_scan.mp4'
    library=media/'promo-video/public/clips/v3/library_chats_pins.mp4'
    if not ext.exists() or not library.exists():raise FileNotFoundError('Pass --media-root pointing to the checkout containing the authentic promo recordings.')
    run(['-i',ext,'-an','-vf','crop=1482:834:1400:0,scale=1126:634,fps=30','-c:v','libx264','-crf','16','-preset','veryfast',RECORDINGS/'extension-discovery.mp4'])
    # Tighten idle intervals but retain actual search, open and conversation clicks.
    run(['-i',library,'-filter_complex','[0:v]trim=start=0:end=8,setpts=(PTS-STARTPTS)/1.4,scale=1344:756,fps=30[a];[0:v]trim=start=9.6:end=11.8,setpts=PTS-STARTPTS,scale=1344:756,fps=30[b];[a][b]concat=n=2:v=1:a=0[v]','-map','[v]','-an','-c:v','libx264','-crf','16','-preset','veryfast',RECORDINGS/'library-resume.mp4'])
    metadata={'extension-discovery.mp4':{'source':str(ext),'source_range':[0,6.566667],'crop':[1400,0,1482,834],'muted':True},'library-resume.mp4':{'source':str(library),'edits':[{'range':[0,8],'speed':1.4},{'range':[9.6,11.8],'speed':1}],'muted':True}}
    (RECORDINGS/'provenance.json').write_text(json.dumps(metadata,indent=2))
def render(media):
    prepare(media)
    scenes=json.loads((ROOT/'assets/timeline.json').read_text());segments=[]
    for s in scenes:
        pieces=[(s['start'],s['end'],s['id'])]
        if s['kind']=='progressive':pieces=[(s['start'],131.4,'11-progressive-text'),(131.4,133.9,'11-progressive-visual'),(133.9,s['end'],s['id'])]
        for start,end,asset in pieces:
            n=frames(end)-frames(start);path=PARTS/f'{asset}.mp4'
            image=ROOT/f'assets/scenes/{asset}.png'
            inputs=['-loop','1','-framerate',FPS,'-i',image]
            if s['kind'] in ['discovery','library']:
                clip='extension-discovery' if s['kind']=='discovery' else 'library-resume'
                inputs += ['-i',RECORDINGS/f'{clip}.mp4']
                x,y=(98,272) if s['kind']=='discovery' else (288,235)
                filters=f'[0:v]format=yuv420p[bg];[1:v]fps=30,tpad=stop_mode=clone:stop_duration=30[clip];[bg][clip]overlay={x}:{y}:shortest=1,format=yuv420p[v]'
            else:filters='[0:v]format=yuv420p[v]'
            encode(path,inputs,filters,n);segments.append(path)
            print(f'Rendered {asset}: {n} frames',flush=True)
    manifest=OUT/'concat.txt';manifest.write_text('\n'.join(f"file '{p.as_posix()}'" for p in segments)+'\n')
    run(['-f','concat','-safe','0','-i',manifest,'-i',ROOT/'explaning-audio.mp3','-map','0:v:0','-map','1:a:0','-c:v','copy','-af','loudnorm=I=-16:TP=-1.5:LRA=11','-c:a','aac','-b:a','256k','-ar','48000','-t',frames(scenes[-1]['end'])/FPS,'-movflags','+faststart',OUT/'vidseek-architecture.mp4'])
    # A separate silent visual layer is useful in an editor with the untouched original MP3.
    run(['-f','concat','-safe','0','-i',manifest,'-c:v','copy','-an','-movflags','+faststart',OUT/'vidseek-visual-layer.mp4'])
    print('Final narrated video and silent visual layer exported.',flush=True)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--media-root',type=Path,default=ROOT.parent);args=parser.parse_args();render(args.media_root)
