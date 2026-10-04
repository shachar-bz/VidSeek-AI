"""Generate consistent editable SVGs and 1080p PNGs for the narrated walkthrough."""
import base64, html, json, math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'assets/scenes'; OUT.mkdir(parents=True,exist_ok=True)
BG='#F7F9FC'; INK='#17243A'; MUTED='#64748B'; LINE='#CDD7E4'; BLUE='#315ACB'; TEAL='#067C7A'; PURPLE='#7451BA'; WHITE='#FFFFFF'; ORANGE='#AF651C'
SANS='/System/Library/Fonts/Avenir Next.ttc'
MONO='/System/Library/Fonts/Menlo.ttc'
class Canvas:
    def __init__(self):
        self.img=Image.new('RGB',(1920,1080),BG); self.draw=ImageDraw.Draw(self.img)
        self.svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080"><rect width="1920" height="1080" fill="{BG}"/>']
    def rect(self,x,y,w,h,fill=WHITE,stroke=LINE,r=16,sw=2):
        self.draw.rounded_rectangle((x,y,x+w,y+h),radius=r,fill=fill,outline=stroke,width=sw)
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
    def text(self,x,y,text,size=30,color=INK,bold=False,mono=False):
        font_path = MONO if mono else ('/System/Library/Fonts/Supplemental/Arial Unicode.ttf' if any(ch in text for ch in '→↔±') else SANS)
        font=ImageFont.truetype(font_path,size,index=0)
        # Draw using top anchoring, matching SVG's before-edge baseline.
        self.draw.text((x,y),text,font=font,fill=color,anchor='lt',stroke_width=0)
        family='Menlo, monospace' if mono else 'Avenir Next, Arial, sans-serif'
        self.svg.append(f'<text x="{x}" y="{y}" fill="{color}" font-family="{family}" font-size="{size}" font-weight="{600 if bold else 400}" dominant-baseline="text-before-edge">{html.escape(text)}</text>')
    def line(self,x1,y1,x2,y2,color=LINE,width=3):
        self.draw.line((x1,y1,x2,y2),fill=color,width=width)
        self.svg.append(f'<path d="M{x1} {y1} L{x2} {y2}" fill="none" stroke="{color}" stroke-width="{width}"/>')
    def arrow(self,x1,y1,x2,y2,color=MUTED):
        self.line(x1,y1,x2,y2,color,3)
        a=math.atan2(y2-y1,x2-x1)
        pts=[(x2,y2),(x2-13*math.cos(a-.5),y2-13*math.sin(a-.5)),(x2-13*math.cos(a+.5),y2-13*math.sin(a+.5))]
        self.draw.polygon(pts,fill=color)
        self.svg.append('<polygon points="'+' '.join(f'{x},{y}' for x,y in pts)+f'" fill="{color}"/>')
    def image(self,path,x,y,w,h):
        im=Image.open(path).convert('RGBA'); im=im.resize((w,h),Image.Resampling.LANCZOS); self.img.paste(im,(x,y),im)
        uri='data:image/png;base64,'+base64.b64encode(Path(path).read_bytes()).decode()
        self.svg.append(f'<image href="{uri}" x="{x}" y="{y}" width="{w}" height="{h}"/>')
    def card(self,x,y,w,h,title,lines=(),color=BLUE,mono=False):
        self.rect(x,y,w,h,stroke=color,sw=2)
        self.rect(x,y,6,h,fill=color,stroke=color,r=2)
        self.text(x+24,y+20,title,32,color,bold=True,mono=mono)
        for i,t in enumerate(lines): self.text(x+24,y+72+i*39,t,26,MUTED)
    def save(self,name):
        self.img.save(OUT/f'{name}.png'); (OUT/f'{name}.svg').write_text('\n'.join(self.svg+['</svg>']))

def header(c,s):
    c.image(ROOT/'assets/vidseek-icon.png',96,56,46,46)
    c.text(158,62,'VidSeek AI',30,INK,bold=True)
    c.text(1450,65,'UNDER THE HOOD',23,MUTED)
    c.text(96,134,s['title'],54,INK,bold=True)
    c.line(96,214,1824,214)

def roadmap(c,active):
    labels=['Browser + web app','Acquire media','Text / visual indexes','Azure storage','Agent + tools','Grounded answer']
    colors=[INK,INK,TEAL,BLUE,PURPLE,INK]
    for i,label in enumerate(labels):
        x=96+i*292; col=colors[i] if i in active else LINE
        c.rect(x,895,265,64,fill=WHITE,stroke=col,r=10,sw=3 if i in active else 1)
        c.text(x+14,915,label,22,colors[i] if i in active else MUTED)
        if i<5: c.arrow(x+268,927,x+289,927,LINE)
    c.text(96,995,'ARCHITECTURE / IMPLEMENTATION',20,MUTED)
    c.text(1500,995,'Shachar Ben Zur',22,MUTED)

def frame(c,x,y,w,h,t,phase=0,caption='ILLUSTRATIVE FRAME'):
    c.rect(x,y,w,h,fill='#E8EEF6',stroke=LINE,r=8)
    c.rect(x+12,y+12,88,32,fill=INK,stroke=INK,r=5)
    c.text(x+20,y+16,t,21,WHITE,mono=True)
    c.line(x+28,y+h-42,x+w-28,y+h-42,'#8CA1BA',3)
    c.rect(x+35+phase,y+66,58,55,fill=TEAL,stroke=TEAL,r=8)
    c.text(x+15,y+h-28,caption,13,MUTED)

def intro(c):
    c.text(98,276,'Videos → searchable knowledge',56,INK,bold=True)
    c.text(100,365,'Architecture, data flow and implementation decisions',32,MUTED)
    for x,title,lines,col in [(100,'What was said',['Timestamped transcript','Memories + chapters'],BLUE),(684,'What was shown',['Frame embeddings','Keyframes + on-screen text'],TEAL),(1268,'When it happened',['Evidence with timestamps','One conversation'],PURPLE)]:
        c.card(x,470,548,230,title,lines,col)
    c.text(100,753,'Built and explained by Shachar Ben Zur',28,MUTED)

def architecture(c):
    c.card(96,280,400,180,'Web app',['Video workspace','Conversations + library'],INK)
    c.card(96,530,400,180,'Chrome extension',['Browser-session discovery','Page + player + network'],INK)
    c.arrow(496,370,660,480); c.arrow(496,620,660,480)
    c.card(670,370,490,245,'FastAPI backend',['Acquisition + processing','Text / visual indexes','Agent + retrieval tools'],PURPLE)
    c.arrow(1160,460,1320,365,BLUE); c.arrow(1160,530,1320,620,TEAL)
    c.card(1330,270,490,200,'Azure PostgreSQL',['Structured records','pgvector embeddings'],BLUE)
    c.card(1330,530,490,200,'Azure Blob Storage',['Video files','Stored media'],TEAL)
    c.text(690,760,'Clients request work; backend orchestrates it; storage persists results.',26,MUTED)

def discovery(c):
    # Live recording fades away to reveal this acquisition diagram.
    c.text(116,310,'From browser evidence to usable media',38,INK)
    c.card(116,450,310,205,'Browser session',['DOM + player','Network capture'],INK)
    c.arrow(426,550,491,550,TEAL)
    c.card(500,450,310,205,'Candidates',['Observed streams','Playback context'],TEAL)
    c.arrow(810,550,881,550,TEAL)
    c.card(890,450,310,205,'Main video',['Select content','Exclude ads'],TEAL)
    c.text(116,745,'Captured evidence drives media selection.',28,MUTED)
    c.card(1290,285,534,215,'Browser evidence',['Page elements / DOM','Embedded players','Network activity'],INK)
    c.arrow(1557,500,1557,544,TEAL)
    c.card(1290,550,534,175,'Select the main video',['Playback reveals streams','Separate content from ads'],TEAL)
    c.text(1290,756,'Browser-session discovery',24,MUTED)

def parsing(c):
    c.card(96,425,340,170,'Captured payload',['Only observed data','URLs + metadata'],INK)
    c.arrow(436,470,545,335); c.arrow(436,550,545,650)
    c.card(550,270,510,150,'Known structure',['Deterministic parser'],BLUE)
    c.card(550,570,510,170,'Unfamiliar structure',['LLM selects references','No invented resource URLs'],PURPLE)
    c.arrow(1060,345,1260,475,BLUE); c.arrow(1060,655,1260,530,PURPLE)
    c.card(1270,420,550,195,'Validate → accept',['Selection exists in capture','Materialize observed resource'],TEAL)
    c.text(550,782,'The model proposes a selection; captured data remains the authority.',28,MUTED)

def transcription(c):
    c.card(96,285,640,160,'Existing timestamped captions',['Use available caption timing'],BLUE)
    c.card(96,590,340,150,'Audio',['Extract / acquire'],INK)
    c.arrow(436,665,530,665,BLUE)
    c.card(540,590,560,150,'ElevenLabs transcription',['Speech → timed transcript'],BLUE)
    c.arrow(736,365,1230,470,BLUE); c.arrow(1100,665,1230,565,BLUE)
    c.card(1240,420,580,200,'Timestamped transcript',['Text + start / end times','Input to the text pipeline'],BLUE)
    c.text(96,805,'Use captions when available; transcribe when needed.',28,MUTED)

def reuse(c):
    c.card(96,445,420,160,'Source identity',['Normalized source URL'],INK)
    c.arrow(516,525,620,525)
    c.card(630,445,390,160,'Look up saved video',['Before downloading'],BLUE)
    c.arrow(1020,480,1170,355,TEAL); c.arrow(1020,565,1170,670,MUTED)
    c.text(1060,349,'HIT',24,TEAL,bold=True); c.text(1060,664,'MISS',24,MUTED,bold=True)
    c.card(1180,275,640,190,'Reuse existing results',['Saved video + analysis','Link to the personal library'],TEAL)
    c.card(1180,600,640,180,'Acquire and persist',['Download / transcript / indexes','Database records + Blob media'],BLUE)

def parallel(c):
    c.card(96,435,380,175,'Acquired video',['Media + timed transcript'],INK)
    c.arrow(476,470,610,355,BLUE); c.arrow(476,565,610,655,TEAL)
    c.card(620,275,640,200,'Text pathway',['Transcript → memories → chapters','E5 semantic embeddings'],BLUE)
    c.card(620,575,640,200,'Visual pathway',['2-second frames → SigLIP 2 vectors','Stable keyframes → local OCR'],TEAL)
    c.arrow(1260,375,1400,480,BLUE); c.arrow(1260,675,1400,565,TEAL)
    c.card(1410,430,410,200,'Searchable evidence',['Timestamped records','Vectors + screen text'],PURPLE)

def memories(c):
    for x,title,lines in [(96,'Transcript',['Timestamped speech']),(534,'Memories',['One idea per passage']),(972,'Chapters',['Titles + summaries','Groups of memories']),(1410,'Embeddings',['E5 · 384 dimensions','Semantic retrieval'])]:
        c.card(x,290,410,190,title,lines,BLUE)
        if x<1410:c.arrow(x+410,385,x+432,385,BLUE)
    c.text(96,545,'LLM segmentation preserves links to the source timeline.',31,MUTED)
    c.card(96,600,1000,190,'Comparable vectors',['Embed passages and questions','Rank matches by semantic similarity'],BLUE)
    c.card(1160,600,660,190,'Search by meaning',['Question vector ↔ passage vectors','Retrieve relevant timestamped passages'],BLUE)

def frames(c):
    for i,t in enumerate(['00:00','00:02','00:04','00:06','00:08']):frame(c,96+i*280,275,250,180,t,i*12)
    c.text(96,500,'Sampling interval: 2 seconds  /  0.5 fps',31,TEAL,bold=True)
    c.arrow(796,462,796,565,TEAL)
    c.card(526,575,600,180,'SigLIP 2',['Images + natural-language queries','Same 768-dimensional vector space'],TEAL)
    c.arrow(1126,665,1260,665,TEAL)
    c.card(1270,575,550,180,'Frame search',['Similarity-ranked moments','Timestamped candidate frames'],TEAL)
    c.text(96,802,'Frame and query embeddings are created locally with SigLIP 2.',26,MUTED)

def ocr(c):
    c.card(96,285,780,170,'Ignore brief movement',['Temporary change → returns to reference','No new stable segment'],MUTED)
    c.card(96,505,780,185,'Keep lasting changes',['Scene difference: embedding distance','Slide / text difference: perceptual hash'],TEAL)
    c.arrow(876,598,980,598,TEAL)
    c.card(990,500,360,190,'Keyframes',['Stable boundaries','Full-resolution decode'],TEAL)
    c.arrow(1350,598,1430,598,TEAL)
    c.card(1440,500,380,190,'Local Surya OCR',['Read screen text','Index for search'],TEAL)
    c.card(990,280,830,170,'Confirm stable changes',['Two changed samples must agree','Brief segments merge into their neighbors'],TEAL)
    c.text(96,760,'Confirm changed samples and stability before opening a new segment.',28,MUTED)
    c.text(96,807,'Long segments also receive periodic keyframes.',26,MUTED)

def progressive(c,ready=3):
    c.text(96,267,'Capabilities unlock as evidence becomes ready',34,MUTED)
    stages=[(96,390,BLUE,'Transcript chat','READY FIRST'),(676,525,TEAL,'Visual search','READY NEXT'),(1256,655,TEAL,'OCR coverage','CONTINUES EXPANDING')]
    for i,(x,y,col,title,sub) in enumerate(stages):
        if i >= ready: col = MUTED
        c.rect(x,y,550,130,fill=WHITE,stroke=col,r=12,sw=3)
        c.text(x+26,y+22,title,36,col,bold=True); c.text(x+26,y+79,sub,22,MUTED)
    c.arrow(350,810,1690,810,MUTED)
    c.text(96,845,'Processing order is schematic; these are not measured durations.',23,MUTED)

def agent(c,vision=False):
    c.card(96,450,340,170,'Question',['A focused request'],INK)
    c.arrow(436,535,555,535,PURPLE)
    c.card(565,435,440,200,'Main agent',['Chooses retrieval tools','Combines evidence'],PURPLE)
    if not vision:
        c.arrow(1005,480,1150,340,BLUE); c.arrow(1005,560,1150,690,TEAL)
        c.card(1160,265,660,190,'Text retrieval',['Outline / semantic search','Chapter / memory context'],BLUE)
        c.card(1160,600,660,190,'Visual retrieval',['Search candidate moments','Inspect frames or sequences'],TEAL)
        c.text(96,760,'Retrieve focused evidence instead of loading the entire archive.',30,MUTED)
    else:
        c.card(1090,270,730,145,'Transcript evidence',['Relevant passages + timestamp ranges'],BLUE)
        c.card(1090,630,350,165,'Inspection grid',['Selected frames'],TEAL)
        c.arrow(1440,710,1490,710,TEAL)
        c.card(1500,630,320,165,'Vision model',['Observations'],TEAL)
        c.arrow(1500,630,1005,580,TEAL); c.arrow(1090,355,1005,470,BLUE)
        c.text(1070,493,'Focused observations return to the main agent',25,PURPLE)
        c.text(96,825,'Images are analyzed separately; the answer merges visual and spoken evidence.',28,MUTED)

def texttools(c):
    c.card(96,275,820,175,'Explore structure',['Browse chapter titles and summaries'],BLUE)
    c.card(1000,275,820,175,'Search by meaning',['Find relevant passages by meaning'],BLUE)
    c.arrow(506,450,506,555,BLUE); c.arrow(1410,450,1410,555,BLUE)
    c.card(96,565,820,175,'Expand a chapter',['Read the full section with timestamp ranges'],BLUE)
    c.card(1000,565,820,175,'Expand a memory',['Read the target passage and its neighbors'],BLUE)
    c.text(96,795,'Search narrows the scope. Context retrieval supplies the surrounding evidence.',28,MUTED)

def inspection(c,sequence=False):
    if not sequence:
        c.card(96,275,780,165,'Search visual moments',['Query → candidate timestamps','Candidates still need inspection'],TEAL)
        c.arrow(876,358,985,358,TEAL)
        c.card(995,275,825,165,'Inspect candidate frames',['Different moments → one contact sheet','Compare each frame independently'],TEAL)
        for i,t in enumerate(['00:12','02:34','06:20']):frame(c,360+i*430,530,390,240,t,phase=i*35,caption='ILLUSTRATIVE CONTACT-SHEET CELL')
        c.text(96,808,'Example layout: candidate times are unrelated; this is not an action sequence.',26,MUTED)
    else:
        c.card(96,270,1724,150,'Inspect a time sequence',['Frames from one time window, ordered left to right'],TEAL)
        for i,t in enumerate(['00:10','00:12','00:14']):
            frame(c,280+i*520,510,420,240,t,phase=i*95,caption='ILLUSTRATIVE SEQUENCE CELL')
            if i<2:c.arrow(715+i*520,630,785+i*520,630,TEAL)
        c.text(96,815,'Compare changes across time to examine an action.',29,MUTED)

def budget(c):
    c.card(96,285,820,215,'6 visual tool calls',['Searches + inspections share this limit','Per answer'],PURPLE)
    c.card(1000,285,820,215,'4 looks',['One grid or close view = one look','Per answer'],TEAL)
    c.card(96,555,820,230,'Evidence already collected',['Transcript passages + inspected frames','Explicit limits on visual work'],PURPLE)
    c.card(1000,555,820,230,'When the budget is spent',['Further visual calls do no work','Use the evidence already collected','Say what could not be confirmed'],PURPLE)
    c.text(96,803,'Transcript tools do not spend this visual budget.',26,MUTED)

def citations(c):
    c.card(96,280,610,180,'Retrieved tool range',['Example evidence: 02:10–02:40','Only supported times may be cited'],BLUE)
    c.card(96,550,610,170,'Incoming answer stream',['Supported [02:18]','Unsupported [07:50]'],INK)
    c.arrow(706,635,810,635,PURPLE)
    c.card(820,550,420,170,'Citation filter',['Check bracket + range','As text streams'],PURPLE)
    c.arrow(1240,635,1350,635,TEAL)
    c.card(1360,550,460,170,'Filtered stream',['Keep [02:18]','Drop [07:50]'],TEAL)
    c.line(401,460,401,495,BLUE)
    c.line(401,495,1030,495,BLUE)
    c.arrow(1030,495,1030,550,BLUE)
    c.card(820,285,1000,175,'Supported timestamp ranges',['Citations must fall inside retrieved evidence','One-second tolerance for rounded timestamps'],BLUE)
    c.text(96,795,'Checks timestamp support; it does not verify whether the prose claim is true.',28,MUTED)

def product(c,library=False):
    # Consistent matte, full-screen product insert with title above and architecture below.
    file='library' if library else 'workspace'
    c.image(ROOT/f'assets/source-frames/{file}.png',288,235,1344,756)
    if not library:
        c.rect(55,435,218,74,stroke=BLUE,r=8); c.text(73,457,'Video + transcript',22,BLUE)
        c.line(273,471,444,471,BLUE)
        c.rect(1646,435,225,74,stroke=PURPLE,r=8); c.text(1665,457,'Chat + history',22,PURPLE)
        c.line(1460,471,1646,471,PURPLE)
    c.text(96,1018,'ACTUAL PRODUCT / SAVED VIDEO WORKSPACE',20,MUTED)

def outro(c):
    c.image(ROOT/'assets/vidseek-icon.png',876,260,168,168)
    c.text(485,510,'Thanks for watching',86,INK,bold=True)
    c.text(650,635,'VidSeek AI · Shachar Ben Zur',38,MUTED)

BUILDERS={'outro':outro,'intro':intro,'architecture':architecture,'discovery':discovery,'parsing':parsing,'transcription':transcription,'reuse':reuse,'parallel':parallel,'memories':memories,'frames':frames,'ocr':ocr,'progressive':progressive,'agent':agent,'texttools':texttools,'candidates':inspection,'sequence':lambda c:inspection(c,True),'vision':lambda c:agent(c,True),'budget':budget,'citations':citations,'workspace':product,'library':lambda c:product(c,True)}
ACTIVE={'intro':[], 'architecture':[0,1,2,3,4], 'discovery':[0,1], 'parsing':[1], 'transcription':[1,2], 'reuse':[1,3], 'parallel':[2], 'memories':[2,3], 'frames':[2,3], 'ocr':[2,3], 'progressive':[2,4], 'agent':[3,4,5], 'texttools':[3,4], 'candidates':[3,4], 'sequence':[3,4], 'vision':[4,5], 'budget':[4], 'citations':[4,5]}

def build():
    scenes=json.loads((ROOT/'assets/timeline.json').read_text())
    for s in scenes:
        c=Canvas()
        if s['kind'] != 'outro': header(c,s)
        BUILDERS[s['kind']](c)
        if s['kind'] not in ['discovery','workspace','library','outro']:roadmap(c,ACTIVE[s['kind']])
        elif s['kind']=='discovery':
            c.text(1290,821,'Browser → acquisition',25,TEAL); c.text(96,997,'ACTUAL EXTENSION / TECHNICAL DISCOVERY',20,MUTED)
        c.save(s['id']); print('Built',s['id'])
    for ready, suffix in [(1,'text'),(2,'visual')]:
        scene=next(s for s in scenes if s['kind']=='progressive')
        c=Canvas();header(c,scene);progressive(c,ready);roadmap(c,ACTIVE['progressive']);c.save('11-progressive-'+suffix)
    thumbs=[]
    for s in scenes:
        im=Image.open(OUT/f"{s['id']}.png").resize((480,270))
        tile=Image.new('RGB',(480,306),WHITE); tile.paste(im,(0,0))
        ImageDraw.Draw(tile).text((12,277),f"{s['id']} · {s['start']:.2f}s",font=ImageFont.truetype(SANS,16),fill=INK)
        thumbs.append(tile)
    sheet=Image.new('RGB',(1920,math.ceil(len(thumbs)/4)*306),LINE)
    for i,im in enumerate(thumbs):sheet.paste(im,((i%4)*480,(i//4)*306))
    sheet.save(ROOT/'out/storyboard.jpg',quality=95)
    cards='\n'.join(f'<article><h2>{s["start"]:.2f}s — {html.escape(s["title"])}</h2><img src="assets/scenes/{s["id"]}.png"><p>{html.escape(s["screen"])}</p><a href="assets/scenes/{s["id"]}.svg">Editable SVG</a></article>' for s in scenes)
    (ROOT/'STORYBOARD.html').write_text('<!doctype html><meta charset="utf-8"><title>VidSeek architecture storyboard</title><style>body{font:18px system-ui;background:#f7f9fc;color:#17243a;max-width:1400px;margin:40px auto}article{margin:40px 0;padding:24px;background:white;border:1px solid #cdd7e4;border-radius:16px}img{width:100%}h1{font-size:42px}p{line-height:1.5}video{width:100%}</style><h1>VidSeek AI · Technical walkthrough</h1><p>Original narration, architecture diagrams, and authentic product inserts.</p><video controls src="out/vidseek-architecture-captioned.mp4"></video>'+cards)
if __name__=='__main__':build()
