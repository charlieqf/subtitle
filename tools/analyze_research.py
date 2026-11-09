"""Export provider comparisons; metrics are diagnostics, not human-reference accuracy."""
from pathlib import Path
import difflib
import json
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tmp/python-deps'))
from subtitle_tool.api import export_transcript
from subtitle_tool.captions import normalize_tencent,normalize_aliyun,punctuation

OUT=ROOT/'outputs/research-20261109'
EVIDENCE=ROOT/'evidence/video-test-20261109'
TERMS=['围绝经期','雌孕激素','子宫内膜异位症','内异症','营养干预','肌少症','抗炎饮食','魁北克','人民卫生出版社']

def read(path): return json.loads(path.read_text(encoding='utf-8'))
def write(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def words(segments): return [w for s in segments for w in s['words'] if not punctuation(w['text'])]
def percentile(values,p):
    values=sorted(values)
    if not values: return None
    i=(len(values)-1)*p
    a=int(i); b=min(a+1,len(values)-1)
    return values[a]+(values[b]-values[a])*(i-a)

summary={}
all_segments={}
tracks={}
for folder in OUT.iterdir():
    path=folder/'transcription-0.json'
    if not path.exists():continue
    state=read(folder/'job.json')
    provider=state['identity']['provider']
    raw=read(path)
    segments=normalize_tencent(raw) if provider=='tencent' else normalize_aliyun(raw)
    all_segments[folder.name]=segments
    duration=(raw.get('AudioDuration',0)*1000 if provider=='tencent' else raw['properties']['original_duration_in_milliseconds'])
    artifacts=export_transcript(raw,provider,folder,metadata=dict(duration_ms=round(duration),audio_offset_ms=0,
                                model=state['identity']['model'],task_id=state['task_id']))
    normalized=read(folder/'transcript.json')
    text=''.join(s['text'] for s in segments)
    token_list=words(segments)
    summary[folder.name]=dict(provider=provider,model=state['identity']['model'],
        task_id=state['task_id'],duration_seconds=duration/1000,elapsed_seconds=state['elapsed_seconds'],
        inference_elapsed_seconds=state['inference_elapsed_seconds'],sentence_count=len(segments),
        word_count=len(token_list),cue_count=artifacts['cue_count'],removed_fillers=artifacts['removed_fillers'],
        first_word_ms=token_list[0]['start_ms'],last_word_end_ms=token_list[-1]['end_ms'],
        speakers=sorted({str(s['speaker']) for s in segments}),
        validation_counts={reason:sum(x['reason']==reason for x in normalized['validation'])
                           for reason in sorted({x['reason'] for x in normalized['validation']})},
        word_errors=[w for w in token_list if w['start_ms']<0 or w['end_ms']<w['start_ms'] or w['end_ms']>duration],
        term_occurrences={t:text.count(t) for t in TERMS})
    if duration>200000:
        tracks[folder.name]=normalized['captions']

if 'tencent-control-43s' in all_segments and 'tencent-offset-2s' in all_segments:
    a=words(all_segments['tencent-control-43s']); b=words(all_segments['tencent-offset-2s'])
    matched=[]
    for match in difflib.SequenceMatcher(None,[w['text'] for w in a],[w['text'] for w in b],autojunk=False).get_matching_blocks():
        for i in range(match.size):
            wa,wb=a[match.a+i],b[match.b+i]
            matched.append(dict(text=wa['text'],start_delta_ms=wb['start_ms']-wa['start_ms'],
                end_delta_ms=wb['end_ms']-wa['end_ms'],start_error_ms=wb['start_ms']-wa['start_ms']-2000,
                end_error_ms=wb['end_ms']-wa['end_ms']-2000))
    errors=[abs(x[k]) for x in matched for k in ['start_error_ms','end_error_ms']]
    offset=dict(description='Same 43 seconds of source PCM; second input prepends 2000 ms of digital silence.',
        interpretation='Translation invariance test, NOT absolute alignment accuracy against a human reference.',
        matched_words=len(matched),control_words=len(a),shifted_words=len(b),
        median_abs_residual_ms=statistics.median(errors),p95_abs_residual_ms=percentile(errors,.95),
        max_abs_residual_ms=max(errors),first_words=matched[:8],all_matched_words=matched)
    write(EVIDENCE/'offset-test.json',offset)

diffs={}
for left,right in [('tencent-standard-baseline','tencent-standard-hotwords'),
                   ('tencent-large-baseline','tencent-large-filter')]:
    if left not in all_segments or right not in all_segments:continue
    a=''.join(s['text'] for s in all_segments[left]);b=''.join(s['text'] for s in all_segments[right])
    changes=[]
    for op,i,j,k,l in difflib.SequenceMatcher(None,a,b,autojunk=False).get_opcodes():
        if op!='equal': changes.append(dict(operation=op,before=a[i:j],after=b[k:l],context=a[max(0,i-12):min(len(a),j+12)]))
    diffs[right]=changes
write(EVIDENCE/'hypothesis-differences.json',diffs)
write(EVIDENCE/'summary.json',summary)
write(OUT/'review-tracks.json',tracks)
print(json.dumps(summary,ensure_ascii=False,indent=2))
