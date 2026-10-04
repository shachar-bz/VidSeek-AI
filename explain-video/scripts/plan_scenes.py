"""Match editorial cues to locally recognized words, then write the visual plan."""
import json, re, difflib, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
# One persistent map, detail panels, and only two short product-recording sections.
SCENES=[
('intro','Hi everyone','VidSeek AI · Under the hood','Title + architecture preview','Logo, presenter credit and a restrained preview of acquisition → processing → retrieval.','Hold; no logo animation.','Architecture and implementation'),
('architecture','The system combines','Clients, orchestration and storage','Architecture diagram','Web app and Chrome extension connect to FastAPI. Azure PostgreSQL + pgvector stores records and vectors; Blob Storage stores media.','Same map establishes stable component positions.','backend/storage/postgres; backend/storage/blob'),
('discovery','The first challenge','Acquire the right media','Screen recording + diagram','Actual Coursera extension Find / Scan recording next to DOM, embedded-player and network inputs. Main media is selected; ad candidates are rejected.','Play the recording once; fade it out over its final 0.6 seconds to reveal the acquisition diagram. No frozen recording remains.','chrome-extension/src/discovery.ts; page-discovery.ts; background.ts'),
('parsing','Known structures','Parse first. Validate the fallback.','Data-flow diagram','Known payload → deterministic parser. Unfamiliar payload → LLM selects references → validate against captured payload → accepted resource.','Highlight the alternate route; keep acquisition mini-map.','backend/services/video_download/web/structured.py'),
('transcription','The system uses','Build a timestamped transcript','Data-flow diagram','Existing timestamped captions OR audio → ElevenLabs transcription → timestamped transcript.','Show both alternatives converging; no simulated API response.','backend/services/video_download/web/transcript.py; transcription/elevenlabs'),
('reuse','Videos and their analysis','Reuse before downloading','Decision diagram','Normalized source identity → lookup → hit: reuse saved media and analysis; miss: acquire and persist. Azure database and Blob Storage are separate.','Emphasize the cache-hit branch; hold through the pause.','backend/services/video_download/jobs.py:create; _create_deduplicated_job'),
('parallel','Now, let','Two parallel processing paths','Architecture diagram','Return to the original map, expanded around processing. Transcript branch and visual branch run side by side.','One deliberate detail cut. Text remains blue; visuals remain teal.','backend/services/video_download/jobs.py; backend/services/visual_indexing'),
('memories','An LLM divides','Transcript → memories → chapters','Processing diagram','Timestamped passages become one-idea memories and chapter groups with titles/summaries. E5 creates 384-dimensional passage vectors for pgvector semantic retrieval.','Highlight text lane. Show passage and query vectors as a conceptual flow without code.','semantic_segmentation/memories; chapters; embeddings/multilingual_text_embedding/model.py'),
('frames','The visual pipeline','Sample once every two seconds','Frame-strip diagram','Illustrative video frames at 0, 2, 4, 6, 8 seconds → SigLIP 2 → 768-dimensional vectors; natural-language query enters the same embedding space.','Highlight visual lane and sampling interval; frames remain still.','visual_indexing/sampling/frame_stream.py; embeddings/image_embedding/model.py'),
('ocr','It detects lasting','Stable changes → keyframes → OCR','Diagram + implementation view','Contrast transient movement with a lasting slide/content change. Embedding distance + perceptual hash; two stable changed samples confirm a boundary. Selected full-resolution keyframes → local Surya OCR → searchable text.','Reuse frame strip; emphasize retained keyframes and OCR route.','visual_indexing/segments/segmenter.py; sampling/keyframes.py; ocr/configured.py'),
('progressive','Because this takes time','Availability grows progressively','Capability timeline','Transcript chat ready first; frame search ready next; OCR coverage continues expanding. Timings are schematic, not performance measurements.','Hold the same timeline. Highlight transcript first, visual search at 02:11.40, and OCR at 02:13.90; no measured percentages.','video_agent/tools/visual_tools.py; services/visual_search.py'),
('agent','So, how does','Retrieve focused evidence','Agent data-flow diagram','Question → main agent → tools → relevant text / moments → evidence → answer. Full transcript and image archive stay in storage.','Rejoin original map at agent; highlight retrieval edges.','backend/video_agent/runner.py; tools'),
('texttools','For questions about spoken','Find the passage, then expand context','Tool diagram','Video outline or semantic passage search → relevant chapter/memory → full chapter or memory context → evidence with timestamp ranges.','Follow one path at a time with blue outlines; use plain-language tool labels.','video_agent/tools/get_video_outline; memories_semantic_search; get_chapter_context; get_memory_context'),
('candidates','For visual questions','Search candidates, then inspect','Illustrative inspection diagram','Visual search returns candidate times; candidate inspection composes a single contact sheet from different moments for comparison.','Use timestamped illustrative cells, explicitly labeled as examples.','video_agent/tools/search_visual_moments; view_candidates'),
('sequence','Another presents frames','Inspect actions in chronological order','Illustrative sequence diagram','Sequence inspection arranges frames from a time window in chronological order. Show a simple object moving across three frames.','Reuse inspection panel; ordered timestamps and one arrow, no looping animation.','video_agent/tools/view_sequence'),
('vision','A separate vision model','Vision observations + transcript evidence','Agent data-flow diagram','Inspection grid → separate vision model → focused observations → main agent. Transcript evidence joins the same synthesis step.','Reuse agent map; highlight the vision handoff, then the merge.','backend/video_agent/image_analysis.py; runner.py'),
('budget','A fixed visual budget','Bound the work per answer','Visual-budget diagram','At most 6 visual tool calls and 4 looks per answer. Once spent, later visual tools do no work; answer with collected evidence and state uncertainty.','Static budget limits in plain language; no code or fabricated execution trace.','backend/video_agent/visual_budget.py'),
('citations','Finally, a streaming filter','Validate timestamp support','Streaming-filter diagram','Retrieved span 02:10–02:40 accepts [02:18], drops [07:50]. Text streams through; only citation support is validated. ±1 second endpoint tolerance shown as implementation note.','One example before/after with the timestamp-support rule stated in plain language.','backend/video_agent/citations.py'),
('workspace','The website brings','One workspace around the video','UI view from real recording','Actual website: video, transcript, chat and saved conversations, framed with restrained callouts. Chapter/summary access is annotated only where visible.','Clean cut to actual workspace; hold, no feature montage.','promo-video/public/clips/v3/library_chats_pins.mp4, source 7.6s'),
('library','A personal library','Persist knowledge. Resume exploration.','Screen recording','Actual personal library search → open saved video → reopen existing conversation.','Use source 0–11.3s, muted, with a held final frame if needed. End on workspace; no sales CTA.','promo-video/public/clips/v3/library_chats_pins.mp4, source 0–11.3s'),
]
def normalized(s): return re.findall(r'[a-z0-9]+',s.lower())
def build():
    recognition=json.loads((ROOT/'assets/narration-recognition.json').read_text())
    words=recognition['chunks']; flattened=[]
    for w in words:
        for token in normalized(w['text']): flattened.append((token,w['timestamp'][0]))
    cursor=0; scenes=[]
    for i,(kind,cue,title,visual,content,transition,source) in enumerate(SCENES):
        tokens=normalized(cue); choices=[]
        for j in range(cursor,len(flattened)-len(tokens)+1):
            score=difflib.SequenceMatcher(None,tokens,[t[0] for t in flattened[j:j+len(tokens)]]).ratio()
            choices.append((score,-j,j))
        score,_,j=max(choices)
        if score<0.65: raise ValueError(f'Uncertain cue {cue}: {score}')
        start=0 if i==0 else float(flattened[j][1])
        scenes.append(dict(id=f'{i+1:02d}-{kind}',kind=kind,start=start,cue=cue,title=title,type=visual,screen=content,transition=transition,implementation=source,cue_match=score))
        cursor=j+len(tokens)
    for i,s in enumerate(scenes): s['end']=scenes[i+1]['start'] if i+1<len(scenes) else 231.967313
    end_audio_duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(ROOT/'end-audio.mp3')]))
    closing_start=scenes[-1]['end']
    scenes.append(dict(id='21-outro',kind='outro',start=closing_start,end=closing_start+2.5,cue='Thanks for watching',title='Thanks for watching',type='Closing card',screen='VidSeek icon, thanks for watching, and presenter credit.',transition='Fade the card in gently; closing audio starts 0.35 seconds into the card, followed by a short hold.',implementation='end-audio.mp3',audio_duration=end_audio_duration))
    (ROOT/'assets/timeline.json').write_text(json.dumps(scenes,indent=2))
    def tc(t): return f'{int(t)//60:02d}:{t%60:05.2f}'
    transcript=re.sub(r'\[[^]]+\]','',(ROOT/'text-for-audio.txt').read_text()).strip()
    paragraphs=[p.strip() for p in transcript.split('\n\n') if p.strip()]
    lines=['# VidSeek AI — technical walkthrough visual plan','','Duration: 03:54.47. Original narration preserved; the supplied end-audio.mp3 is appended over a quiet closing card. Local Whisper word timestamps align editorial cues; provided transcript is the authority for wording. Cues are rounded to the 30 fps edit grid for export.','','## Visual approach','','1920 × 1080, 30 fps. Warm white background, dark navy text, blue text pathway, teal visual pathway, purple agent pathway. Use the VidSeek icon, Avenir headings and plain-language diagram labels. No code excerpts or implementation identifiers appear on screen. One persistent architecture map with matching detail panels. Static holds and progressive highlights; clean cuts at changes of topic. No music, sound effects, marketing CTA, or ornamental transitions.','','Product inserts reuse authentic recordings from this project and are recut for this narration; no UI or backend activity is fabricated. Illustrative frames and citation examples are explicitly labeled. The processing timeline expresses order, not measured elapsed time.','','## Scene-by-scene plan','']
    for s in scenes:
        i=next((i for i,p in enumerate(paragraphs) if p.lower().startswith(s['cue'].lower())),None)
        relevant=paragraphs[i] if i is not None else (s['cue']+'.' if s['kind']=='outro' else s['cue']+'…')
        # Include narration up until the following cue, including explanatory follow-on paragraphs.
        next_index=None
        index=scenes.index(s)
        if index+1<len(scenes):
            next_cue=scenes[index+1]['cue'].lower()
            next_index=next((j for j,p in enumerate(paragraphs) if p.lower().startswith(next_cue)),None)
        if i is not None and next_index is not None and next_index>i: relevant=' '.join(paragraphs[i:next_index])
        lines += [f"### {s['id']} · {tc(s['start'])}–{tc(s['end'])} · {s['title']}",'',f'**Narration:** {relevant}','',f"**Visual:** {s['type']}. {s['screen']}",'',f"**Direction:** {s['transition']}",'',f"**Implementation evidence:** `{s['implementation']}`",'']
    lines += ['## Source and accuracy notes','','The visual-budget limits are current code defaults, not narrated numerical claims. The citation filter checks support for timestamp endpoints against retrieved spans (with one-second slack); it does not fact-check the answer text. Vision inspection grids go to a separate image-analysis model. The optional close-up tool can send images directly to the main agent; this video covers the two grid tools named in the narration. Azure is shown as storage, without implying that every model or the FastAPI runtime is hosted there. OCR is local and conditional on configuration.']
    (ROOT/'VISUAL_PLAN.md').write_text('\n'.join(lines)+'\n')
    for s in scenes: print(s['id'],tc(s['start']),tc(s['end']),s['cue'])
if __name__=='__main__': build()
