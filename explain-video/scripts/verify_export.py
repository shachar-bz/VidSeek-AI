"""Check delivery timing, recording exit, diagram labels, and appended audio."""
import io, json, math, re, subprocess
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'out'; VIDEO=OUT/'vidseek-architecture.mp4'
def frame(t):
    data=subprocess.check_output(['ffmpeg','-v','error','-ss',str(t),'-i',str(VIDEO),'-frames:v','1','-f','image2pipe','-c:v','png','pipe:1'])
    return Image.open(io.BytesIO(data)).convert('RGB')
def verify():
    scenes=json.loads((ROOT/'assets/timeline.json').read_text())
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(VIDEO)]))
    video=next(s for s in probe['streams'] if s['codec_type']=='video');audio=next(s for s in probe['streams'] if s['codec_type']=='audio')
    expected_frames=round(scenes[-1]['end']*30)
    assert (video['width'],video['height'],video['r_frame_rate'],int(video['nb_frames']))==(1920,1080,'30/1',expected_frames)
    assert audio['sample_rate']=='48000'
    assert all(s['cue_match']==1 for s in scenes if 'cue_match' in s)
    assert sum(round(s['end']*30)-round(s['start']*30) for s in scenes)==expected_frames
    # The exited recording must reveal the authored diagram, rather than a frozen frame.
    base=np.asarray(Image.open(ROOT/'assets/scenes/03-discovery.png').convert('RGB'),dtype=float)[272:906,98:1224]
    visible=np.asarray(frame(37),dtype=float)[272:906,98:1224]
    exited=np.asarray(frame(44),dtype=float)[272:906,98:1224]
    exit_error=float(np.abs(exited-base).mean());visible_error=float(np.abs(visible-base).mean())
    assert exit_error<5 and visible_error>15,(exit_error,visible_error)
    forbidden=re.compile(r'MODEL_NAME|QUERY_PREFIX|PASSAGE_PREFIX|MAX_VISUAL_TOOL_CALLS|MAX_LOOKS|SLACK_SECONDS|change_hold_samples|(?:get|view|search|memories)_[a-z_]+')
    assert all(not forbidden.search(p.read_text()) for p in (ROOT/'assets/scenes').glob('*.svg'))
    outro=next(s for s in scenes if s['kind']=='outro')
    end_samples=np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-ss',str(round(outro['start']*30)/30+.35),'-i',str(VIDEO),'-t','1.306','-vn','-f','f32le','-ac','1','-ar','16000','pipe:1']),dtype=np.float32)
    outro_rms=float(np.sqrt(np.mean(end_samples**2)));assert outro_rms>.01,outro_rms
    qa=OUT/'qa';qa.mkdir(exist_ok=True)
    sheet=Image.new('RGB',(1920,math.ceil(len(scenes)/4)*306),'#CDD7E4')
    for i,s in enumerate(scenes):
        t=s['start']+min(3,(s['end']-s['start'])/2)
        im=frame(t);im.save(qa/f"{s['id']}.jpg",quality=95)
        sheet.paste(im.resize((480,270)),((i%4)*480,(i//4)*306))
        ImageDraw.Draw(sheet).text(((i%4)*480+12,(i//4)*306+277),f"{s['id']} / {t:.2f}s",font=ImageFont.truetype('/System/Library/Fonts/Avenir Next.ttc',16),fill='#17243A')
    sheet.save(OUT/'video-contact-sheet.jpg',quality=95)
    for t in [39,39.75,40.2,44,232.2,233,234]:frame(t).save(qa/f'check-{t}.jpg',quality=95)
    measurement=subprocess.run(['ffmpeg','-hide_banner','-nostats','-i',str(VIDEO),'-vn','-af','ebur128=peak=true:framelog=verbose','-f','null','-'],capture_output=True,text=True,check=True)
    summary=measurement.stderr[measurement.stderr.rfind('Summary:'):]
    (OUT/'audio-verification.txt').write_text(summary)
    report={'duration_seconds':float(probe['format']['duration']),'resolution':'1920x1080','fps':30,'frames':expected_frames,'audio':'AAC mono 48 kHz; original narration + supplied end-audio.mp3','scene_cues':'20 original narration cues remain unchanged; one closing card appended','checks':{'recording_visible_during_playback':visible_error>15,'recording_absent_at_44_seconds':exit_error<5,'recording_exit_pixel_error':exit_error,'no_code_or_function_identifiers_in_diagrams':True,'closing_audio_rms':outro_rms,'closing_audio_start':round(outro['start']*30)/30+.35},'audio_measurement':summary}
    (OUT/'verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='audio_measurement'},indent=2))
if __name__=='__main__':verify()
