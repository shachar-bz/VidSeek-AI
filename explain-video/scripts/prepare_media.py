"""Extract review stills from existing authentic product recordings."""
import argparse, shutil, subprocess
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
def prepare(media):
    target=ROOT/'assets/source-frames';target.mkdir(parents=True,exist_ok=True)
    clips=media/'promo-video/public/clips/v3'
    for name,clip,t in [('extension','coursera_scan',5),('workspace','library_chats_pins',8),('library','library_chats_pins',0)]:
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',str(clips/f'{clip}.mp4'),'-frames:v','1',str(target/f'{name}.png')],check=True)
    Image.open(target/'extension.png').crop((1400,0,2882,834)).save(target/'extension-detail.png')
    shutil.copy2(media/'promo-video/public/brand/vidseek-icon.png',ROOT/'assets/vidseek-icon.png')
    print('Prepared authentic source stills and logo.')
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--media-root',type=Path,default=ROOT.parent);prepare(parser.parse_args().media_root)
