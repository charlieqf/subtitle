"""Reproducible provider experiment; resumes accepted tasks, never blindly resubmits."""
from pathlib import Path
import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone

import requests
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.asr.v20190614 import asr_client, models

SECRETS = []

def now():
    return datetime.now(timezone.utc).isoformat()

def clean(value):
    if isinstance(value, dict):
        return {k: ('[REDACTED]' if k.lower() in {'url','file_url','file_urls','transcription_url',
            'authorization','signature','policy','oss_access_key_id','upload_dir','data'} and
            isinstance(v, (str, list)) else clean(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(x) for x in value]
    if isinstance(value, str):
        secrets = SECRETS + [os.environ[k] for k in ['DASHSCOPE_API_KEY','TENCENT_SECRET_ID',
            'TENCENT_SECRET_KEY','ALIYUN_WORKSPACE_ID'] if os.environ.get(k)]
        for secret in secrets:
            value = value.replace(secret, '[REDACTED]')
        return re.sub(r'(?:https?://|oss://)[^\s"<>]+', '[URL REDACTED]', value)
    return value

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)

def load_credentials(path):
    allowed = {'TENCENT_APP_ID','TENCENT_SECRET_ID','TENCENT_SECRET_KEY','DASHSCOPE_API_KEY',
               'ALIYUN_WORKSPACE_ID','ALIYUN_ASR_BASE_URL','ALIYUN_WORKSPACE_BASE_URL'}
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            key, sep, value = line.partition('=')
            if sep and key in allowed:
                os.environ.setdefault(key, value)
    SECRETS.extend(os.environ[k] for k in allowed if k in os.environ and os.environ[k])

def tencent_client():
    hp = HttpProfile(endpoint='asr.tencentcloudapi.com', reqTimeout=120)
    profile = ClientProfile(httpProfile=hp)
    return asr_client.AsrClient(credential.Credential(os.environ['TENCENT_SECRET_ID'],
                                  os.environ['TENCENT_SECRET_KEY']), 'ap-guangzhou', profile)

def tencent_call(client, action, payload):
    if not hasattr(models, action + 'Request'):
        return json.loads(client.call(action, payload))['Response']
    request = getattr(models, action + 'Request')()
    request.from_json_string(json.dumps(payload, ensure_ascii=False))
    return json.loads(getattr(client, action)(request).to_json_string())

def account(label, evidence_dir):
    data = tencent_call(tencent_client(), 'DescribePidOrders',
                        {'AvailableType': 0, 'Page': 1, 'PageSize': 100})
    save(Path(evidence_dir) / f'account-{label}.json', dict(checked_at=now(), response=data))
    current = [x for x in data.get('PidOrders', []) if x.get('EffectiveTime','').startswith('2026-11')]
    print(json.dumps(dict(label=label, request_id=data.get('RequestId'),
                         packages=[{k:x.get(k) for k in ['Name','RestNum','RestNumFloat','SubProductCode']}
                                   for x in current]), ensure_ascii=False), flush=True)

def run(args):
    emit = getattr(args, 'progress', None) or (lambda event: None)
    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=True)
    state_path = folder / 'job.json'
    audio = Path(args.audio).resolve()
    with audio.open('rb') as handle:
        fingerprint = hashlib.file_digest(handle, 'sha256').hexdigest()
    vocabulary = json.loads(Path(args.vocabulary).read_text(encoding='utf-8')) if args.vocabulary else None
    identity = dict(provider=args.provider, model=args.model, audio_sha256=fingerprint,
                    vocabulary=vocabulary, filter_modal=args.filter_modal)
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state['identity'] != identity:
            raise RuntimeError('Experiment identity changed; use a new name')
        if state['status'] == 'SUCCEEDED':
            emit(dict(name=args.name, status='ALREADY_SUCCEEDED'))
            return
        if not state.get('task_id'):
            raise RuntimeError('Previous submission has no task ID; inspect evidence and use a new name only after resolution')
    else:
        state = dict(uuid=str(uuid.uuid4()), identity=identity, created_at=now(),
                     started_epoch=time.time(), status='PREPARING', input_bytes=audio.stat().st_size,
                     events=[])
    client = tencent_client() if args.provider == 'tencent' else None
    base = os.environ.get('ALIYUN_ASR_BASE_URL', 'https://dashscope.aliyuncs.com/api/v1')
    headers = {'Authorization': 'Bearer ' + os.environ['DASHSCOPE_API_KEY']} if args.provider == 'aliyun' else {}
    if not state.get('task_id'):
        if args.provider == 'tencent':
            if audio.stat().st_size > 5_000_000:
                raise RuntimeError('Audio exceeds conservative 5 MB inline limit')
            payload = dict(EngineModelType=args.model, ChannelNum=1, ResTextFormat=3,
                           SourceType=1, Data=base64.b64encode(audio.read_bytes()).decode(),
                           DataLen=audio.stat().st_size, SpeakerDiarization=1,
                           FilterDirty=0, FilterModal=args.filter_modal, FilterPunc=0,
                           SentenceMaxLength=20)
            if vocabulary:
                payload['HotwordList'] = ','.join(f'{k}|{v}' for k,v in vocabulary.items())
            save(folder / 'request.json', payload)
            state['status'] = 'SUBMITTING'
            save(state_path, state)
            try:
                response = tencent_call(client, 'CreateRecTask', payload)
            except TencentCloudSDKException as exc:
                state.update(status='REJECTED' if exc.get_code() not in ['ClientNetworkError','RequestTimeout']
                             else 'SUBMISSION_UNKNOWN', error=clean(str(exc)))
                save(state_path, state)
                raise
            save(folder / 'submission.json', response)
            state['task_id'] = response['Data']['TaskId']
        else:
            response = requests.get(base + '/uploads', headers=headers,
                params={'action':'getPolicy','model':args.model}, timeout=30)
            if response.status_code != 200:
                save(folder / 'upload-error.json', response.json())
                raise RuntimeError(f'Upload policy rejected HTTP {response.status_code}')
            body = response.json()
            policy = body.get('data') or body.get('output')
            object_key = policy['upload_dir'] + '/' + state['uuid'] + audio.suffix
            fields = {k:(None,v) for k,v in dict(OSSAccessKeyId=policy['oss_access_key_id'],
                       Signature=policy['signature'], policy=policy['policy'], key=object_key,
                       success_action_status='200', **{'x-oss-object-acl':policy['x_oss_object_acl'],
                       'x-oss-forbid-overwrite':policy['x_oss_forbid_overwrite']}).items()}
            with audio.open('rb') as stream:
                fields['file'] = (audio.name, stream, 'audio/mpeg' if audio.suffix.lower()=='.mp3' else 'audio/flac')
                upload = requests.post(policy['upload_host'], files=fields, timeout=(600,120))
            if upload.status_code != 200:
                raise RuntimeError(f'OSS upload rejected HTTP {upload.status_code}')
            state['upload_completed_at'] = now()
            payload = dict(model=args.model, input={'file_urls':['oss://' + object_key]},
                           parameters=dict(channel_id=[0], diarization_enabled=True, language_hints=['zh']))
            if vocabulary:
                payload['parameters']['vocabulary'] = vocabulary
            save(folder / 'request.json', payload)
            state['status'] = 'SUBMITTING'
            save(state_path, state)
            response = requests.post(base + '/services/audio/asr/transcription',
                headers={**headers, 'X-DashScope-Async':'enable','X-DashScope-OssResourceResolve':'enable'},
                json=payload, timeout=(30,120))
            result = response.json()
            save(folder / 'submission.json', result)
            if response.status_code != 200 or not result.get('output',{}).get('task_id'):
                state.update(status='REJECTED', error=clean(result))
                save(state_path, state)
                raise RuntimeError(f'Submission rejected HTTP {response.status_code}')
            state['task_id'] = result['output']['task_id']
        state.update(status='SUBMITTED', submitted_at=now(), submitted_epoch=time.time())
        save(state_path, state)
        emit(dict(name=args.name, status=state['status'], task_id=state['task_id']))
    deadline = time.monotonic() + args.wait_seconds
    while time.monotonic() < deadline:
        try:
            if args.provider == 'tencent':
                result = tencent_call(client, 'DescribeTaskStatus', {'TaskId':state['task_id']})
                payload = result['Data']
                status = {0:'PENDING',1:'RUNNING',2:'SUCCEEDED',3:'FAILED'}[payload['Status']]
            else:
                response = requests.get(base + '/tasks/' + str(state['task_id']), headers=headers, timeout=30)
                response.raise_for_status()
                result = response.json()
                payload = result['output']
                status = payload['task_status']
            save(folder / 'latest-response.json', result)
            state['events'].append(dict(at=now(), status=status,
                                 request_id=result.get('RequestId',result.get('request_id'))))
            state['status'] = status
            if status in ['SUCCEEDED','FAILED','CANCELED']:
                state['elapsed_seconds'] = round(time.time() - state['started_epoch'], 3)
                state['inference_elapsed_seconds'] = round(time.time() - state['submitted_epoch'], 3)
                if status == 'SUCCEEDED':
                    if args.provider == 'aliyun':
                        for index, item in enumerate(payload['results']):
                            if item.get('subtask_status') != 'SUCCEEDED':
                                raise RuntimeError('A transcription subtask failed')
                            transcript = requests.get(item['transcription_url'], timeout=60)
                            transcript.raise_for_status()
                            save(folder / f'transcription-{index}.json', transcript.json())
                    else:
                        save(folder / 'transcription-0.json', payload)
                save(state_path, state)
                emit(dict(name=args.name,status=status,elapsed=state['elapsed_seconds'],
                          error=payload.get('ErrorMsg',payload.get('message'))))
                return
            save(state_path, state)
        except (requests.RequestException, TencentCloudSDKException) as exc:
            if state['status'] == 'SUCCEEDED':
                state['status'] = 'RESULT_PENDING'
            state['events'].append(dict(at=now(), poll_error=clean(str(exc))))
            save(state_path, state)
        time.sleep(5)
    emit(dict(name=args.name,status='POLL_BUDGET_REACHED',task_id=state['task_id']))
