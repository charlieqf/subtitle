"""Cross-check every reported edit distance with an independent implementation."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'tmp/metric-deps'))
from rapidfuzz.distance import Levenshtein
from compare_reference import normalize,levenshtein,aligned_terms
from subtitle_tool.captions import normalize_tencent,normalize_aliyun

report=json.loads((ROOT/'evidence/video-test-20261109/reference-comparison.json').read_text(encoding='utf-8'))
reference=normalize((ROOT/report['reference']).read_text(encoding='utf-8-sig'))
checked=[]
for row in report['results']:
    folder=ROOT/'outputs/research-20261109'/row['name']
    if row['name']=='tencent-large-hotwords': folder=ROOT/'outputs/python-api-demo/provider'
    raw=json.loads((folder/'transcription-0.json').read_text(encoding='utf-8'))
    segments=normalize_tencent(raw) if row['provider']=='tencent' else normalize_aliyun(raw)
    text=normalize(''.join(s['text'] for s in segments))
    assert Levenshtein.distance(reference,text)==row['edit_distance']
    assert row['counts']['equal']+row['counts']['substitute']+row['counts']['delete']==len(reference)
    assert row['counts']['equal']+row['counts']['substitute']+row['counts']['insert']==len(text)
    normalized_path=folder/'transcript.json'
    if row['name']=='tencent-large-hotwords': normalized_path=folder.parent/'transcript.json'
    cleaned=normalize(''.join(c['text'] for c in json.loads(normalized_path.read_text(encoding='utf-8'))['captions']))
    assert Levenshtein.distance(reference,cleaned)==row['conservative_cleanup']['edit_distance']
    checked.append(row['name'])

for a,b in [('kitten','sitting'),('医学采访','医学访谈'),('围绝经期','微绝经期'),('','增加'),('删除','')]:
    counts,ops=levenshtein(a,b)
    assert sum(counts[k] for k in ['substitute','insert','delete'])==Levenshtein.distance(a,b)
test_ref='甲内异症乙内异症丙'
test_hyp='甲类风湿乙内异症丙'
counts,ops=levenshtein(test_ref,test_hyp)
terms=aligned_terms(test_ref,test_hyp,ops)
assert [t['correct'] for t in terms]==[False,True]
evidence=dict(status='passed',library='rapidfuzz',engines=checked,
              checked_metrics=['raw edit distance','cleaned edit distance','S/D/I invariants','aligned term positions'])
(ROOT/'evidence/video-test-20261109/reference-metrics-verification.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
print(json.dumps(evidence))
