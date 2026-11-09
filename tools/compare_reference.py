"""Exact character Levenshtein and aligned terminology scoring against approved text.

The reference is editorially revised, so CER here measures final-copy editing
distance, not pure verbatim speech-recognition error rate.
"""
from pathlib import Path
import csv
import hashlib
import json
import sys
import unicodedata

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from subtitle_tool.captions import normalize_tencent,normalize_aliyun

OUT=ROOT/'outputs/research-20261109'
EVIDENCE=ROOT/'evidence/video-test-20261109'
REFERENCE=ROOT/'中医药采访-徐从剑.txt'
TERMS=['围绝经期','内异症','子宫内膜异位症','雌孕激素','营养干预','肌少症','抗炎饮食']

def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKC',text).lower()
                   if not c.isspace() and not unicodedata.category(c).startswith(('P','Z')))

def levenshtein(reference,hypothesis):
    """Unit-cost global alignment; ties prefer substitute, delete, then insert."""
    n,m=len(reference),len(hypothesis)
    width=m+1
    trace=bytearray((n+1)*width)
    previous=list(range(m+1))
    for j in range(1,m+1): trace[j]=3
    for i,rc in enumerate(reference,1):
        row=[i]+[0]*m
        trace[i*width]=2
        for j,hc in enumerate(hypothesis,1):
            if rc==hc:
                row[j]=previous[j-1]
                trace[i*width+j]=0
            else:
                values=(previous[j-1]+1,previous[j]+1,row[j-1]+1)
                best=min(values)
                row[j]=best
                trace[i*width+j]=values.index(best)+1
        previous=row
    operations=[]
    counts={'equal':0,'substitute':0,'delete':0,'insert':0}
    i,j=n,m
    while i or j:
        direction=trace[i*width+j]
        if direction in (0,1):
            i-=1;j-=1
            tag='equal' if direction==0 else 'substitute'
            operations.append((tag,i,j));counts[tag]+=1
        elif direction==2:
            i-=1;operations.append(('delete',i,None));counts['delete']+=1
        else:
            j-=1;operations.append(('insert',None,j));counts['insert']+=1
    operations.reverse()
    assert counts['substitute']+counts['delete']+counts['insert']==previous[m]
    return counts,operations

def aligned_terms(reference,hypothesis,operations):
    matched={i:j for op,i,j in operations if i is not None and j is not None}
    result=[]
    for term in TERMS:
        start=0
        while (start:=reference.find(term,start))>=0:
            positions=[matched[i] for i in range(start,start+len(term)) if i in matched]
            text=hypothesis[min(positions):max(positions)+1] if positions else ''
            result.append(dict(term=term,reference_start=start,hypothesis=text,correct=text==term))
            start+=len(term)
    return result

def main():
    original=REFERENCE.read_text(encoding='utf-8-sig')
    ref=normalize(original)
    lines=[]
    offset=0
    for index,line in enumerate(original.splitlines(),1):
        normalized=normalize(line)
        lines.append((offset,offset+len(normalized),index,line))
        offset+=len(normalized)
    cases=[(p.name,p) for p in sorted(OUT.iterdir()) if (p/'transcription-0.json').exists()
           and p.name not in {'aliyun-short','tencent-control-43s','tencent-offset-2s'}]
    app=ROOT/'outputs/python-api-demo/provider'
    if (app/'transcription-0.json').exists(): cases.append(('tencent-large-hotwords',app))
    results=[]; differences=[]; all_term_details={}
    for name,folder in cases:
        state=json.loads((folder/'job.json').read_text(encoding='utf-8'))
        raw=json.loads((folder/'transcription-0.json').read_text(encoding='utf-8'))
        provider=state['identity']['provider']
        segments=normalize_tencent(raw) if provider=='tencent' else normalize_aliyun(raw)
        hypothesis=normalize(''.join(s['text'] for s in segments))
        counts,ops=levenshtein(ref,hypothesis)
        distance=sum(counts[k] for k in ['substitute','delete','insert'])
        terms=aligned_terms(ref,hypothesis,ops)
        all_term_details[name]=terms
        normalized_path=folder/'transcript.json'
        if name=='tencent-large-hotwords': normalized_path=folder.parent/'transcript.json'
        clean_text=normalize(''.join(c['text'] for c in json.loads(normalized_path.read_text(encoding='utf-8'))['captions'])) if normalized_path.exists() else hypothesis
        clean_counts,_=levenshtein(ref,clean_text)
        clean_distance=sum(clean_counts[k] for k in ['substitute','delete','insert'])
        results.append(dict(name=name,provider=provider,model=state['identity']['model'],
            reference_characters=len(ref),hypothesis_characters=len(hypothesis),
            counts=counts,edit_distance=distance,cer=distance/len(ref),
            reference_agreement=1-distance/len(ref),
            conservative_cleanup=dict(edit_distance=clean_distance,cer=clean_distance/len(ref),
                                      reference_agreement=1-clean_distance/len(ref),counts=clean_counts),
            terminology_correct=sum(x['correct'] for x in terms),terminology_total=len(terms),
            terminology_accuracy=sum(x['correct'] for x in terms)/len(terms),
            per_term={t:dict(correct=sum(x['correct'] for x in terms if x['term']==t),
                             total=sum(x['term']==t for x in terms)) for t in TERMS}))
        # Consecutive non-matching operations, preserving context and approximate ASR sentence time.
        spans=[];pos=0
        for segment in segments:
            text=normalize(segment['text']);spans.append((pos,pos+len(text),segment['start_ms']));pos+=len(text)
        cursor=0;group=[]
        def flush():
            if not group:return
            ris=[i for _,i,_ in group if i is not None]
            his=[j for _,_,j in group if j is not None]
            r0=min(ris) if ris else cursor
            r1=max(ris)+1 if ris else cursor
            h0=min(his) if his else None
            refline=next((index for start,end,index,line in lines if start<=r0<end),None)
            time_ms=next((start_ms for start,end,start_ms in spans if h0 is not None and start<=h0<end),None)
            differences.append(dict(engine=name,reference_line=refline,approx_sentence_start_ms=time_ms,
                reference=''.join(ref[i] for _,i,_ in group if i is not None),
                hypothesis=''.join(hypothesis[j] for _,_,j in group if j is not None),
                reference_context=ref[max(0,r0-14):min(len(ref),r1+14)],
                operation_types=','.join(sorted({op for op,_,_ in group}))))
            group.clear()
        for operation in ops:
            op,i,j=operation
            if op=='equal':flush()
            else:group.append(operation)
            if i is not None:cursor=i+1
        flush()
    results.sort(key=lambda x:(x['cer'],-x['terminology_accuracy']))
    report=dict(reference=REFERENCE.name,
        reference_sha256=hashlib.sha256(REFERENCE.read_bytes()).hexdigest(),
        normalization='Unicode NFKC; lowercase Latin; remove punctuation and whitespace; preserve numerals, pronouns, fillers and repetitions.',
        reference_type='Approved editorial subtitles, not verified verbatim transcription; no timestamps.',
        interpretation='1-CER is agreement with final edited copy, not standalone ASR accuracy. Term accuracy uses aligned occurrences of seven predefined medical terms.',
        results=results)
    for filename,data in [('reference-comparison.json',report),('term-comparison-details.json',all_term_details)]:
        (EVIDENCE/filename).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    with (EVIDENCE/'reference-differences.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(differences[0]));writer.writeheader();writer.writerows(differences)
    for x in results:
        print(f"{x['name']}: N={len(ref)}, S/D/I={x['counts']['substitute']}/{x['counts']['delete']}/{x['counts']['insert']}, "
              f"CER={x['cer']:.4%}, agreement={x['reference_agreement']:.4%}, "
              f"clean_agreement={x['conservative_cleanup']['reference_agreement']:.4%}, "
              f"terms={x['terminology_correct']}/{x['terminology_total']}")

if __name__=='__main__': main()
