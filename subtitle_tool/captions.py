"""Timestamp-preserving normalization, conservative cleanup, and SRT interchange."""
import re
import unicodedata

FILLERS = frozenset({'呃', '嗯'})

def punctuation(text):
    return bool(text) and all(unicodedata.category(c).startswith('P') or c.isspace() for c in text)

def normalize_tencent(data):
    segments = []
    for sentence in data['ResultDetail']:
        start = sentence['StartMs']
        segments.append(dict(start_ms=start, end_ms=sentence['EndMs'], text=sentence['FinalSentence'],
            speaker=sentence.get('SpeakerId'), words=[dict(text=w['Word'],
                start_ms=start+w['OffsetStartMs'], end_ms=start+w['OffsetEndMs'])
                for w in sentence.get('Words', [])]))
    return segments

def normalize_aliyun(data):
    segments = []
    for track in data['transcripts']:
        for sentence in track['sentences']:
            words = []
            for w in sentence.get('words', []):
                words.append(dict(text=w['text']+w.get('punctuation',''),
                                  start_ms=w['begin_time'], end_ms=w['end_time']))
            segments.append(dict(start_ms=sentence['begin_time'], end_ms=sentence['end_time'],
                text=sentence['text'], speaker=sentence.get('speaker_id'), words=words))
    return sorted(segments,key=lambda s:s['start_ms'])

def build_captions(segments, *, clean_fillers=True, max_chars=22, gap_ms=500, max_duration_ms=6000):
    if max_chars < 4 or gap_ms < 0 or max_duration_ms <= 0:
        raise ValueError('Invalid caption limits')
    captions, edits = [], []
    for segment in segments:
        words = []
        for original in segment['words']:
            w = dict(original)
            core = w['text'].strip('，。！？、；：,.!?;: ')
            if clean_fillers and core in FILLERS:
                edits.append(dict(action='remove_filler', **w))
                continue
            if punctuation(w['text']):
                if words:
                    words[-1]['text'] += w['text']
                continue
            if w['end_ms'] <= w['start_ms']:
                # Retain zero-length tokens in text; flag them for review in validation.
                w['end_ms'] = w['start_ms']
            words.append(w)
        if not segment['words']:
            # Never invent per-word timings from character count.
            if segment['text'].strip():
                captions.append(dict(start_ms=segment['start_ms'],end_ms=segment['end_ms'],
                    text=segment['text'], timing_source='sentence', review_reason='missing_word_timestamps'))
            continue
        group = []
        def flush():
            if group:
                captions.append(dict(start_ms=group[0]['start_ms'],end_ms=max(w['end_ms'] for w in group),
                    text=''.join(w['text'] for w in group), timing_source='words'))
                group.clear()
        for w in words:
            if group and (len(''.join(x['text'] for x in group))+len(w['text']) > max_chars or
                w['start_ms']-group[-1]['end_ms'] >= gap_ms or
                w['end_ms']-group[0]['start_ms'] > max_duration_ms):
                flush()
            group.append(w)
        flush()
    return captions, edits

def validate(cues, duration_ms=None):
    issues = []
    previous_end = 0
    for index, cue in enumerate(cues,1):
        start,end=cue['start_ms'],cue['end_ms']
        for bad,reason in [(start<0,'negative_time'),(end<=start,'nonpositive_duration'),
            (start<previous_end,'overlap'),(duration_ms is not None and end>duration_ms,'past_media_end'),
            (not cue['text'].strip(),'empty_text'),(end-start<700,'short_display'),
            (len(cue['text'].replace('\n',''))/max((end-start)/1000,0.001)>12,'fast_reading')]:
            if bad: issues.append(dict(cue=index,reason=reason,start_ms=start,end_ms=end,text=cue['text']))
        previous_end=end
    return issues

def timestamp(ms):
    if ms < 0:
        raise ValueError('Negative timestamp')
    seconds,millis=divmod(round(ms),1000)
    minutes,seconds=divmod(seconds,60)
    hours,minutes=divmod(minutes,60)
    return f'{hours:02}:{minutes:02}:{seconds:02},{millis:03}'

def to_srt(cues):
    fatal=[x for x in validate(cues) if x['reason'] in {'negative_time','nonpositive_duration','overlap','empty_text'}]
    if fatal:
        raise ValueError(f'Invalid subtitle timeline: {fatal[0]}')
    return '\n\n'.join(f"{i}\n{timestamp(c['start_ms'])} --> {timestamp(c['end_ms'])}\n{c['text']}"
                       for i,c in enumerate(cues,1))+'\n'

def parse_srt(text):
    cues=[]
    text=text.lstrip('\ufeff').replace('\r\n','\n').replace('\r','\n').strip()
    if not text:
        raise ValueError('Empty SRT')
    pattern=r'(\d{2,}):([0-5]\d):([0-5]\d)[,.](\d{3})'
    for block in re.split(r'\n\s*\n',text):
        lines=block.splitlines()
        if len(lines)<3 or not lines[0].strip().isdigit():
            raise ValueError('Invalid SRT block')
        match=re.fullmatch(pattern+r'\s*-->\s*'+pattern,lines[1].strip())
        if not match:
            raise ValueError('Invalid SRT timestamp')
        values=list(map(int,match.groups()))
        def ms(v): return ((v[0]*60+v[1])*60+v[2])*1000+v[3]
        cues.append(dict(start_ms=ms(values[:4]),end_ms=ms(values[4:]),text='\n'.join(lines[2:])))
    to_srt(cues)
    return cues
