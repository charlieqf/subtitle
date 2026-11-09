"""Callable API shared by the three CLI workflows."""
from pathlib import Path
from types import SimpleNamespace
from importlib.resources import files
import json
import os
import platform
import subprocess
import tempfile
import copy
import shutil

from .captions import build_captions, normalize_tencent, normalize_aliyun, parse_srt, to_srt, validate
from .media import probe, prepare, _prepare, _write_json, _ffmpeg, _sha256

def _export_transcript(raw, provider, output_dir, *, metadata=None, clean_fillers=False):
    if provider not in {'tencent','aliyun'}: raise ValueError('Unknown provider')
    if not isinstance(raw,dict): raise ValueError('Raw provider result must be an object')
    if provider=='tencent':
        raw=raw.get('Response',raw)
        raw=raw.get('Data',raw)
        if not isinstance(raw,dict) or 'ResultDetail' not in raw:
            raise ValueError('Expected raw Tencent ResultDetail; normalized transcripts cannot be imported again')
        if 'Status' in raw and raw['Status']!=2:
            raise ValueError('Tencent task has not succeeded')
    metadata=copy.deepcopy(metadata or {})
    if 'metadata' in metadata and 'audio' in metadata:
        metadata=metadata['metadata']
    if metadata.get('asr_time_basis','decoded_audio_start')!='decoded_audio_start':
        raise ValueError('Unsupported ASR time basis')
    output=Path(output_dir).resolve()
    output.mkdir(parents=True,exist_ok=True)
    segments=normalize_tencent(raw) if provider=='tencent' else normalize_aliyun(raw)
    provider_segments=copy.deepcopy(segments)
    offset=metadata.get('asr_time_offset_ms',metadata.get('audio_offset_ms',0))
    if not isinstance(offset,(int,float)) or not float('-inf')<offset<float('inf'):
        raise ValueError('Invalid ASR time offset')
    offset=round(offset)
    for s in segments:
        s['start_ms']+=offset; s['end_ms']+=offset
        for w in s['words']:
            w['start_ms']+=offset; w['end_ms']+=offset
    raw_cues,_=build_captions(segments,clean_fillers=False)
    cues,edits=build_captions(segments,clean_fillers=clean_fillers)
    result=dict(schema_version=2,provider=provider,metadata=metadata,
                provider_segments=provider_segments,source_segments=segments,
                timeline=dict(provider_basis='decoded_audio_start',output_basis='media_origin',
                              applied_offset_ms=offset),edits=edits,captions=cues,
                validation=validate(cues,metadata.get('duration_ms')))
    fatal=[x for x in result['validation'] if x['reason'] in
           {'negative_time','nonpositive_duration','overlap','past_media_end','empty_text'}]
    _write_json(output/'transcript.json',result)
    if fatal: raise ValueError(f'Timeline requires review: {fatal[0]}')
    (output/'raw.srt').write_text(to_srt(raw_cues),encoding='utf-8')
    (output/'captions.srt').write_text(to_srt(cues),encoding='utf-8')
    (output/'transcript.txt').write_text('\n'.join(c['text'] for c in cues)+'\n',encoding='utf-8')
    return dict(status='SUCCEEDED',srt=str(output/'captions.srt'),raw_srt=str(output/'raw.srt'),
                json=str(output/'transcript.json'),cue_count=len(cues),removed_fillers=len(edits))

def export_transcript(raw, provider, output_dir, *, metadata=None, clean_fillers=False):
    """Import raw ASR data locally; preserve wording by default and apply offset once.

    Accepts Tencent ResultDetail, Data, or Response/Data envelopes. Inputs are never
    mutated. metadata may be prepare()['metadata'] or the complete prepare result.
    """
    with _task_lock(output_dir):
        return _export_transcript(raw,provider,output_dir,metadata=metadata,clean_fillers=clean_fillers)

def _transcribe(video, output_dir, *, provider='tencent', model=None, vocabulary=None,
               use_medical_vocabulary=True, clean_fillers=True, wait_seconds=600, progress=None):
    """Transcribe or resume a job in output_dir. Credentials come from environment.

    No automatic resubmission after an ambiguous submit. An incomplete task returns
    its persisted status, allowing the caller to invoke this function again.
    """
    from .providers import run as provider_run
    video=Path(video).resolve()
    output=Path(output_dir).resolve()
    output.mkdir(parents=True,exist_ok=True)
    if provider not in {'tencent','aliyun'}: raise ValueError('Unknown provider')
    model=model or ('16k_zh_en_2.0' if provider=='tencent' else 'fun-asr')
    legacy=output/'audio.flac'
    previous_job=output/'provider/job.json'
    if legacy.exists() and previous_job.exists():
        # Resume already submitted 0.1.x jobs with their original audio identity.
        metadata=json.loads((output/'media.json').read_text(encoding='utf-8'))
        state=json.loads(previous_job.read_text(encoding='utf-8'))
        if metadata['source_sha256']!=_sha256(video) or state['identity']['audio_sha256']!=_sha256(legacy):
            raise ValueError('Legacy task source/audio changed; choose a new directory')
        audio=legacy
    else:
        prepared=_prepare(video,output,progress=progress)
        metadata=prepared['metadata']
        audio=Path(prepared['audio']['path'])
    words=json.loads(files('subtitle_tool').joinpath('data/medical-common.json').read_text(encoding='utf-8')) if use_medical_vocabulary else {}
    if vocabulary:
        words.update(json.loads(Path(vocabulary).read_text(encoding='utf-8-sig')) if isinstance(vocabulary,(str,Path)) else vocabulary)
    if len(words)>128 or any(not isinstance(w,str) or not w or any(c in w for c in ',|\n') or
        not isinstance(weight,int) or not 1<=weight<=10 for w,weight in words.items()):
        raise ValueError('Vocabulary must contain up to 128 words with integer weights 1–10')
    vocab_path=output/'vocabulary.json'
    _write_json(vocab_path,words)
    job_dir=output/'provider'
    args=SimpleNamespace(provider=provider,model=model,name=output.name,output=job_dir,audio=audio,
                         vocabulary=vocab_path if words else None,filter_modal=0,wait_seconds=wait_seconds,
                         progress=progress)
    provider_run(args)
    state=json.loads((job_dir/'job.json').read_text(encoding='utf-8'))
    if state['status']!='SUCCEEDED': return dict(status=state['status'],job=str(job_dir/'job.json'))
    raw=json.loads((job_dir/'transcription-0.json').read_text(encoding='utf-8'))
    metadata.update(model=model,task_id=state['task_id'])
    return _export_transcript(raw,provider,output,metadata=metadata,clean_fillers=clean_fillers)

def _source_video_bitrate(video, metadata):
    if metadata.get('video_bit_rate',0):
        return int(metadata['video_bit_rate'])
    import av
    with av.open(str(video)) as container:
        stream=container.streams.video[0]
        duration=float(stream.duration*stream.time_base) if stream.duration else (metadata.get('duration_ms') or 0)/1000
        if duration<=0: raise ValueError('Cannot determine source video bitrate; select --crf or --lossless')
        encoded_bytes=sum(packet.size for packet in container.demux(stream))
    if not encoded_bytes: raise ValueError('No encoded video data')
    return round(encoded_bytes*8/duration)

def render(video, srt, output, *, font=None, fonts_dir=None, font_size=22, crf=None, lossless=False, preset='medium'):
    """Render an existing SRT without credentials, uploads, or ASR requests."""
    video,srt,output=Path(video).resolve(),Path(srt).resolve(),Path(output).resolve()
    if output.exists() or output==video or output==srt: raise FileExistsError(output)
    if output.suffix.lower()!='.mp4': raise ValueError('Output must be MP4')
    if not 8<=font_size<=96 or (crf is not None and not 0<=crf<=51):
        raise ValueError('Invalid rendering parameters')
    if lossless and crf is not None: raise ValueError('Choose lossless or CRF, not both')
    if preset not in {'ultrafast','superfast','veryfast','faster','fast','medium','slow'}:
        raise ValueError('Unsupported encoding preset')
    cues=parse_srt(srt.read_text(encoding='utf-8-sig'))
    metadata=probe(video)
    if not metadata['width']: raise ValueError('Input has no video stream')
    if metadata['duration_ms'] is not None and any(c['end_ms']>metadata['duration_ms']+50 for c in cues):
        raise ValueError('SRT extends beyond video duration')
    font_files=[]
    if fonts_dir is not None:
        fonts_dir=Path(fonts_dir).resolve()
        if not fonts_dir.is_dir(): raise ValueError('fonts_dir must be an existing directory')
        if not font: raise ValueError('Specify font (family name) when using fonts_dir')
        font_files=sorted(p for p in fonts_dir.iterdir() if p.is_file() and p.suffix.lower() in {'.ttf','.otf','.ttc','.otc'})
        if not font_files: raise ValueError('fonts_dir contains no supported font files')
    font=font or ('Microsoft YaHei' if platform.system()=='Windows' else 'PingFang SC' if platform.system()=='Darwin' else 'Noto Sans CJK SC')
    if not re_safe_font(font): raise ValueError('Font name contains unsupported filter characters')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='subtitle-render-') as directory:
        work=Path(directory)
        (work/'captions.srt').write_text(to_srt(cues),encoding='utf-8')
        if font_files:
            (work/'fonts').mkdir()
            for index,path in enumerate(font_files):
                shutil.copy2(path,work/'fonts'/f'{index}{path.suffix.lower()}')
        font_option=':fontsdir=fonts' if font_files else ''
        style=(f'FontName={font},FontSize={font_size},Bold=-1,PrimaryColour=&H00FFFFFF,'
               'OutlineColour=&H00000000,BorderStyle=1,Outline=2.2,Shadow=0,MarginV=18,Alignment=2')
        mode='lossless' if lossless or crf==0 else 'crf' if crf is not None else 'source-bitrate'
        target_bitrate=_source_video_bitrate(video,metadata) if mode=='source-bitrate' else None
        pixel_args=['-pix_fmt','+'+metadata['pixel_format']]
        base=[_ffmpeg(),'-nostdin','-hide_banner','-i',str(video),'-map','0:v:0',
              '-vf',f"subtitles=captions.srt{font_option}:force_style='{style}'",'-c:v','libx264',*pixel_args,'-preset',preset]
        if mode=='source-bitrate':
            # Both passes include the same subtitle overlay. Budget the video
            # stream alone; copied audio is not counted twice in the target.
            rate_args=['-b:v',str(target_bitrate),'-passlogfile',str(work/'x264-pass')]
            first=subprocess.run([*base,*rate_args,'-pass','1','-an','-f','null','-y',os.devnull],
                                 cwd=work,capture_output=True)
            first_log=output.with_suffix('.render-pass1.log')
            first_log.write_bytes(first.stderr)
            if first.returncode: raise RuntimeError(f'First encoding pass failed; inspect {first_log}')
            quality_args=[*rate_args,'-pass','2']
        elif mode=='lossless':
            # QP 0 is lossless across bit depths; CRF 0 is retained as an alias.
            quality_args=['-qp','0']
        else:
            quality_args=['-crf',str(crf)]
        process=subprocess.run([*base,*quality_args,'-map','0:a?','-c:a','copy',
                                '-movflags','+faststart','-n',str(output)],cwd=work,capture_output=True)
        log=output.with_suffix('.render.log')
        log.write_bytes(process.stderr)
        if process.returncode: raise RuntimeError(f'Render failed; inspect {log}')
    return dict(status='SUCCEEDED',video=str(output),cue_count=len(cues),probe=probe(output),
        encoding=dict(codec='libx264',mode=mode,target_video_bit_rate=target_bitrate,
                      passes=2 if mode=='source-bitrate' else 1,
                      crf=crf if mode=='crf' else None,qp=0 if mode=='lossless' else None,
                      lossless=mode=='lossless',preset=preset,audio='copy'),
        subtitle_style=dict(font=font,fonts_dir=str(fonts_dir) if fonts_dir is not None else None,
                            font_size=font_size,bold=True,color='white',outline_color='black',
                            outline=2.2,alignment='bottom-center',margin=18))

def re_safe_font(name):
    return bool(name) and not any(c in name for c in "',:;[]\\\n\r")

def _task_lock(output_dir):
    from filelock import FileLock
    output=Path(output_dir).resolve()
    output.mkdir(parents=True,exist_ok=True)
    return FileLock(str(output/'.task.lock'),timeout=0)

def transcribe(video, output_dir, **options):
    """Transcribe/resume one media file; serialize callers of the same task directory.

    options: provider, model, vocabulary, use_medical_vocabulary, clean_fillers,
    wait_seconds, progress. Distinct task directories may run concurrently.
    """
    with _task_lock(output_dir):
        return _transcribe(video,output_dir,**options)

def run(video, output_dir, *, burn=False, render_options=None, **transcribe_options):
    with _task_lock(output_dir):
        result=_transcribe(video,output_dir,**transcribe_options)
        if burn and result['status']=='SUCCEEDED':
            result['render']=render(video,result['srt'],Path(output_dir)/'subtitled.mp4',**(render_options or {}))
        return result
