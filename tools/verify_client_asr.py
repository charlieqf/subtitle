"""Audit existing real Tencent MP3 jobs; does not submit or upload anything."""
from pathlib import Path
from difflib import SequenceMatcher
import json
import statistics
import subprocess
import sys
import argparse
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from subtitle_tool import export_transcript
from subtitle_tool.captions import normalize_tencent
from subtitle_tool.media import _ffmpeg
from tools.compare_reference import normalize,levenshtein,aligned_terms

OUT=ROOT/'outputs/client-handoff-20261109'
RESEARCH=ROOT/'outputs/research-20261109'
EVIDENCE=ROOT/'evidence/client-handoff-20261109'
EVIDENCE.mkdir(parents=True,exist_ok=True)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def words(raw):
    return [dict(text=normalize(w['text']),start_ms=w['start_ms'],end_ms=w['end_ms'])
            for s in normalize_tencent(raw) for w in s['words'] if normalize(w['text'])]


def timing(reference,hypothesis,expected_offset=0):
    pairs=[]
    matcher=SequenceMatcher(a=[w['text'] for w in reference],b=[w['text'] for w in hypothesis],autojunk=False)
    for block in matcher.get_matching_blocks():
        for a,b in zip(reference[block.a:block.a+block.size],hypothesis[block.b:block.b+block.size]):
            pairs.extend(b[key]-a[key]-expected_offset for key in ['start_ms','end_ms'])
    absolute=sorted(abs(x) for x in pairs)
    return dict(matched_words=len(pairs)//2,median_signed_ms=statistics.median(pairs),
                p95_absolute_ms=absolute[int(.95*(len(absolute)-1))],maximum_absolute_ms=max(absolute))


def decode(path):
    result=subprocess.run([_ffmpeg(),'-hide_banner','-nostdin','-i',str(path),'-map','0:a:0',
        '-ac','1','-ar','16000','-f','f32le','-'],capture_output=True,check=True)
    return np.frombuffer(result.stdout,dtype='<f4')


def waveform(source,audio,positions):
    reference=decode(source)
    encoded=decode(audio)
    samples=[]
    for seconds in positions:
        start=int(seconds*16000)
        size=2*16000
        margin=1600
        left=reference[start:start+size]
        search=encoded[start-margin:start+size+margin]
        coarse=int(np.argmax(np.correlate(search[::8],left[::8],mode='valid')))*8-margin
        scores=[]
        for shift in range(coarse-8,coarse+9):
            right=encoded[start+shift:start+shift+size]
            scores.append(float(np.dot(left,right)/(np.linalg.norm(left)*np.linalg.norm(right))))
        shift=coarse-8+int(np.argmax(scores))
        samples.append(dict(at_seconds=seconds,lag_samples=shift,lag_ms=shift/16,correlation=max(scores)))
    return dict(source_decoded_samples=len(reference),mp3_decoded_samples=len(encoded),samples=samples)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bitrate',type=int,choices=[48,64],default=64)
    args=parser.parse_args()
    suffix='' if args.bitrate==48 else '-64k'
    base=read(RESEARCH/'tencent-large-baseline/transcription-0.json')
    short=read(RESEARCH/f'tencent-large-mp3-{args.bitrate}k/transcription-0.json')
    long=read(RESEARCH/f'tencent-large-mp3-599s{suffix}/transcription-0.json')
    reference=normalize((ROOT/'中医药采访-徐从剑.txt').read_text(encoding='utf-8-sig'))
    quality={}
    for name,raw in [('flac',base),(f'mp3_{args.bitrate}k',short)]:
        hypothesis=normalize(''.join(s['text'] for s in normalize_tencent(raw)))
        counts,ops=levenshtein(reference,hypothesis)
        terms=aligned_terms(reference,hypothesis,ops)
        quality[name]=dict(terminology_correct=sum(t['correct'] for t in terms),terminology_total=len(terms),
            reference_edit_distance=sum(counts[k] for k in ['substitute','delete','insert']),
            reference_characters=len(reference),counts=counts)
    imports={}
    for name,raw,prepared in [('interview',short,read(OUT/f'interview-mp3{suffix}/prepare.json')),
                              ('long',long,read(OUT/f'long-mp3{suffix}/prepare.json'))]:
        before=json.dumps(raw,ensure_ascii=False,sort_keys=True)
        result=export_transcript(raw,'tencent',OUT/(name+'-import'+suffix),metadata=prepared)
        assert json.dumps(raw,ensure_ascii=False,sort_keys=True)==before
        transcript=read(Path(result['json']))
        assert result['removed_fillers']==0
        assert not any(v['reason'] in ['negative_time','nonpositive_duration','overlap','past_media_end','empty_text']
                       for v in transcript['validation'])
        imports[name]=dict(cues=result['cue_count'],removed_fillers=0,
            first_word_ms=words(raw)[0]['start_ms'],last_word_ms=words(raw)[-1]['end_ms'],
            applied_offset_ms=transcript['timeline']['applied_offset_ms'])
    prepared_short=read(OUT/f'interview-mp3{suffix}/prepare.json')
    prepared_long=read(OUT/f'long-mp3{suffix}/prepare.json')
    result=dict(quality=quality,
        short_mp3_vs_flac_timestamps=timing(words(base),words(short)),
        long_first_cycle_vs_short=timing(words(short),[w for w in words(long) if w['start_ms']<237000]),
        imports=imports,
        audio_preparation={name:dict(bytes=p['audio']['bytes'],duration_ms=p['audio']['decoded_duration_ms'],
            sha256=p['audio']['sha256'],first_decoded_pts_ms=p['audio']['first_decoded_pts_ms'])
            for name,p in [('interview',prepared_short),('long',prepared_long)]},
        waveform_interview=waveform(Path(prepared_short['metadata']['source']),Path(prepared_short['audio']['path']),[10,120,220]),
        waveform_long=waveform(Path(prepared_long['metadata']['source']),Path(prepared_long['audio']['path']),[10,300,580]),
        jobs={name:{k:read(RESEARCH/folder/'job.json')[k] for k in ['task_id','status','input_bytes','elapsed_seconds']}
              for name,folder in [('interview',f'tencent-large-mp3-{args.bitrate}k'),('long',f'tencent-large-mp3-599s{suffix}')]},
        limitations=['Long fixture repeats the original interview; it is a duration/transport test, not independent content.',
                    'Timestamp comparisons measure stability relative to existing ASR, not accuracy against human word labels.',
                    'MP3 PTS includes gapless skip metadata; do not add first_decoded_pts_ms to video offset.'])
    for key in ['waveform_interview','waveform_long']:
        assert all(abs(s['lag_samples'])<=1 for s in result[key]['samples']),result[key]
    (EVIDENCE/f'asr-mp3-{args.bitrate}k-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
