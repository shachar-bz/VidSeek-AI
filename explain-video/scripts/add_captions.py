"""Create transcript-authoritative SRT/VTT captions and an offline captioned export.

Uses cached local word timings. FFmpeg does not need libass: transparent caption
cards form a timed PNG stream, composited over the existing final video.
"""
import difflib, json, re, subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'out'; CAPTIONS=ROOT/'assets/captions'; CAPTIONS.mkdir(exist_ok=True)
FONT_PATH='/System/Library/Fonts/Supplemental/Arial.ttf'
FPS=30

def normalized(text):
    return re.sub(r'[^a-z0-9]', '', text.lower().replace('’', "'"))

def transcript_words():
    transcript=re.sub(r'\[[^]]+\]', '', (ROOT/'text-for-audio.txt').read_text()).strip()
    words=transcript.split()
    recognized=json.loads((ROOT/'assets/narration-recognition.json').read_text())['chunks']
    recognized=[w for w in recognized if normalized(w['text'])]
    matches=difflib.SequenceMatcher(None,[normalized(w) for w in words],[normalized(w['text']) for w in recognized],autojunk=False)
    timings=[None]*len(words)
    corrections=[]
    for tag,a,b,c,d in matches.get_opcodes():
        if tag=='equal':
            for i,j in zip(range(a,b),range(c,d)):timings[i]=list(recognized[j]['timestamp'])
        elif b>a:
            start=recognized[c]['timestamp'][0] if c<len(recognized) else recognized[-1]['timestamp'][1]
            end=recognized[d-1]['timestamp'][1] if d>c else start
            for i in range(a,b):
                timings[i]=[start+(end-start)*(i-a)/(b-a),start+(end-start)*(i-a+1)/(b-a)]
            corrections.append({'transcript':' '.join(words[a:b]),'recognized':' '.join(w['text'].strip() for w in recognized[c:d]),'start':start,'end':end})
    assert all(t is not None and t[0] is not None and t[1] is not None for t in timings)
    return words,timings,corrections

def balanced_lines(text):
    words=text.split()
    if len(text)<=46:return [text]
    choices=[]
    for i in range(1,len(words)):
        left,right=' '.join(words[:i]),' '.join(words[i:])
        score=abs(len(left)-len(right))
        if len(left)>50 or len(right)>50:score+=100
        if left.endswith((',',':',';','—')):score-=5
        protected={('shachar','ben'),('ben','zur'),('fastapi','backend'),('chrome','extension')}
        if (normalized(words[i-1]),normalized(words[i])) in protected:score+=1000
        choices.append((score,left,right))
    _,left,right=min(choices)
    return [left,right]

def build_cues():
    words,timings,corrections=transcript_words();groups=[];current=[]
    for i,word in enumerate(words):
        if current and (len(' '.join(words[j] for j in current+[i]))>90 or timings[i][1]-timings[current[0]][0]>4.8):
            groups.append(current);current=[]
        current.append(i)
        text=' '.join(words[j] for j in current)
        if word.endswith(('.', '?', '!')) or (word.endswith((',', ';', ':')) and len(text)>=58):
            groups.append(current);current=[]
    if current:groups.append(current)
    balanced_groups=[]
    for group in groups:
        if len(group)<=3 and balanced_groups:
            previous=balanced_groups[-1]
            combined=previous+group
            if len(' '.join(words[j] for j in combined))<=110 and timings[combined[-1]][1]-timings[combined[0]][0]<=6:
                balanced_groups[-1]=combined
                continue
        balanced_groups.append(group)
    cues=[]
    for group in balanced_groups:
        start=max(0,round((timings[group[0]][0]-.04)*FPS)/FPS)
        end=round((timings[group[-1]][1]+.16)*FPS)/FPS
        text=' '.join(words[j] for j in group)
        cues.append({'start':start,'end':end,'text':text,'lines':balanced_lines(text)})
    for i,cue in enumerate(cues[:-1]):cue['end']=min(cue['end'],cues[i+1]['start']-1/FPS)
    outro=next(s for s in json.loads((ROOT/'assets/timeline.json').read_text()) if s['kind']=='outro')
    start=round(outro['start']*FPS)/FPS+.35
    cues.append({'start':round(start*FPS)/FPS,'end':round((start+outro['audio_duration'])*FPS)/FPS,'text':'Thanks for watching.','lines':['Thanks for watching.']})
    assert ' '.join(c['text'] for c in cues[:-1])==' '.join(words)
    assert all(c['end']>c['start'] and len(c['lines'])<=2 for c in cues)
    assert all(a['end']<=b['start'] for a,b in zip(cues,cues[1:]))
    return cues,corrections

def timecode(t,separator=','):
    ms=round(t*1000);hours,ms=divmod(ms,3600000);minutes,ms=divmod(ms,60000);seconds,ms=divmod(ms,1000)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{ms:03d}'

def card(lines,path):
    image=Image.new('RGBA',(1920,1080),(0,0,0,0));draw=ImageDraw.Draw(image)
    if lines:
        font=ImageFont.truetype(FONT_PATH,34)
        width=max(draw.textlength(line,font=font) for line in lines)
        assert width<=1320,width
        # This occupies only the footer, below the architecture rail and product image.
        box_width=round(max(640,width+70));x=(1920-box_width)//2
        draw.rounded_rectangle((x,977,x+box_width,1073),radius=12,fill=(15,25,43,244))
        y=996 if len(lines)==2 else 1015
        for i,line in enumerate(lines):
            tx=(1920-draw.textlength(line,font=font))/2
            draw.text((tx,y+i*39),line,font=font,fill='white',anchor='lt')
    image.save(path)

def normalize_source():
    # Each segment must be decoded independently: the old concatenated H.264
    # stream changes decoder state at scene boundaries during continuous reads.
    # Lossless RGB intermediates give every segment the same unambiguous format.
    target=OUT/'caption-source';target.mkdir(exist_ok=True)
    original_manifest=OUT/'concat.txt'
    parts=re.findall(r"file '([^']+)'",original_manifest.read_text())
    normalized=[]
    for source_name in parts:
        source=Path(source_name);destination=target/source.name
        if not destination.exists() or destination.stat().st_mtime<source.stat().st_mtime:
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(source),'-vf','format=rgb24','-an','-c:v','libx264rgb','-crf','0','-preset','veryfast','-pix_fmt','rgb24','-r','30','-color_range','pc',str(destination)],check=True)
        normalized.append(destination)
    manifest=target/'concat.txt';manifest.write_text('\n'.join(f"file '{p.as_posix()}'" for p in normalized)+'\n')
    destination=OUT/'caption-source.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(manifest),'-i',str(OUT/'vidseek-architecture.mp4'),'-map','0:v:0','-map','1:a:0','-c','copy','-movflags','+faststart',str(destination)],check=True)
    return destination

def create():
    source_video=normalize_source()
    cues,corrections=build_cues()
    (CAPTIONS/'cues.json').write_text(json.dumps(cues,indent=2,ensure_ascii=False))
    (CAPTIONS/'alignment-corrections.json').write_text(json.dumps(corrections,indent=2,ensure_ascii=False))
    srt='\n\n'.join(f'{i+1}\n{timecode(c["start"])} --> {timecode(c["end"])}\n'+ '\n'.join(c['lines']) for i,c in enumerate(cues))+'\n'
    vtt='WEBVTT\n\n'+'\n\n'.join(f'{timecode(c["start"],".")} --> {timecode(c["end"],".")}\n'+ '\n'.join(c['lines']) for c in cues)+'\n'
    (OUT/'vidseek-architecture.srt').write_text(srt)
    (OUT/'vidseek-architecture.vtt').write_text(vtt)
    frames_dir=OUT/'caption-cards';frames_dir.mkdir(exist_ok=True)
    blank=frames_dir/'blank.png';card([],blank)
    total_frames=int(json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=nb_frames','-of','json',str(OUT/'vidseek-architecture.mp4')]))['streams'][0]['nb_frames'])
    segments=[];cursor=0
    for i,cue in enumerate(cues):
        start,end=round(cue['start']*FPS),round(cue['end']*FPS)
        if start>cursor:segments.append((blank,start-cursor))
        path=frames_dir/f'{i+1:03d}.png';card(cue['lines'],path)
        segments.append((path,end-start));cursor=end
    if cursor<total_frames:segments.append((blank,total_frames-cursor))
    assert sum(n for _,n in segments)==total_frames
    manifest=frames_dir/'captions.ffconcat'
    manifest.write_text('ffconcat version 1.0\n'+''.join(f"file '{p.as_posix()}'\noption framerate 30\nduration {n/FPS:.9f}\n" for p,n in segments)+f"file '{blank.as_posix()}'\noption framerate 30\n")
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(source_video),'-f','concat','-safe','0','-i',str(manifest),'-filter_complex','[0:v]format=rgb24,drawbox=x=0:y=991:w=iw:h=89:color=0xF7F9FC:t=fill[base];[1:v]fps=30,format=rgba[captions];[base][captions]overlay=0:0:eof_action=pass:repeatlast=0:format=rgb,scale=in_range=pc:out_range=tv:out_color_matrix=bt709,format=yuv420p[v]','-map','[v]','-map','0:a:0','-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-r','30','-frames:v',str(total_frames),'-c:a','copy','-movflags','+faststart',str(OUT/'vidseek-architecture-captioned.mp4')],check=True)
    report={'cue_count':len(cues),'wording':'Supplied transcript; stage directions removed; closing line appended.','timing':'Cached local Whisper word timings; replacement blocks interpolated locally.','layout':'Up to two balanced lines; white Arial 34px on navy box below the diagram rail.','corrections':len(corrections),'frames':total_frames,'duration_seconds':total_frames/FPS}
    (OUT/'caption-verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
if __name__=='__main__':create()
