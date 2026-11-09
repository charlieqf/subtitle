"""Repository experiment runner; provider implementation lives in subtitle_tool."""
from pathlib import Path
import argparse
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tmp' / 'python-deps'))
from subtitle_tool.providers import account, clean, load_credentials, run
OUT = ROOT / 'outputs' / 'research-20261109'
p = argparse.ArgumentParser()
p.add_argument('--account')
p.add_argument('--provider', choices=['tencent','aliyun'])
p.add_argument('--model')
p.add_argument('--name')
p.add_argument('--audio',default=str(OUT / 'audio-s16.flac'))
p.add_argument('--vocabulary')
p.add_argument('--filter-modal',type=int,default=0)
p.add_argument('--wait-seconds',type=int,default=600)
a=p.parse_args()
a.progress=lambda event: print(json.dumps(event,ensure_ascii=False),flush=True)
load_credentials(ROOT / '.private' / 'provider-credentials.env')
try:
    if a.account:
        account(a.account, ROOT / 'evidence' / 'video-test-20261109')
    else:
        a.output=OUT / a.name
        run(a)
except Exception as exc:
    print(json.dumps(dict(error_type=type(exc).__name__,error=clean(str(exc))),ensure_ascii=False),flush=True)
    sys.exit(1)
