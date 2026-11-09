"""Verify actual media, independent edited-SRT rendering, and safe output behavior."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import av
import imageio_ffmpeg

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from subtitle_tool import render
from subtitle_tool.captions import parse_srt,to_srt

OUT=ROOT/'outputs/research-20261109'
source=ROOT/'字幕模拟视频1.mp4'
evidence={}

def inspect(path):
    digest=hashlib.sha256()
    with av.open(str(path)) as container:
        video=container.streams.video[0]
        audio=container.streams.audio[0]
        data=dict(duration_seconds=container.duration/1e6,video_frames=video.frames,
                  video_start=float(video.start_time*video.time_base),
                  video_duration=float(video.duration*video.time_base),
                  audio_start=float(audio.start_time*audio.time_base),
                  audio_duration=float(audio.duration*audio.time_base),
                  width=video.codec_context.width,height=video.codec_context.height)
        for packet in container.demux(audio):
            if packet.size: digest.update(bytes(packet))
        data['aac_packet_sha256']=digest.hexdigest()
        return data

evidence['source']=inspect(source)
for filename in [OUT/'tencent-large-subtitled.mp4',ROOT/'outputs/python-api-demo/subtitled.mp4']:
    if filename.exists():
        data=inspect(filename)
        assert data['aac_packet_sha256']==evidence['source']['aac_packet_sha256']
        assert data['video_frames']==evidence['source']['video_frames']
        assert data['video_start']==evidence['source']['video_start']
        assert data['audio_start']==evidence['source']['audio_start']
        assert abs(data['video_duration']-evidence['source']['video_duration'])<.001
        evidence[str(filename.relative_to(ROOT))]=data

clip=OUT/'roundtrip-source-8s.mp4'
if not clip.exists():
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-nostdin','-n','-i',str(source),
        '-t','8','-map','0:v:0','-map','0:a:0','-c','copy',str(clip)],capture_output=True,check=True)
cues=parse_srt((OUT/'tencent-large-baseline/captions.srt').read_text(encoding='utf-8'))[:2]
original_times=[(x['start_ms'],x['end_ms']) for x in cues]
cues[0]['text']='【校对测试】'+cues[0]['text']
edited=OUT/'roundtrip-corrected.srt'
edited.write_text(to_srt(cues),encoding='utf-8-sig',newline='\r\n')
parsed=parse_srt(edited.read_text(encoding='utf-8-sig'))
assert [(x['start_ms'],x['end_ms']) for x in parsed]==original_times
output=OUT/'roundtrip-corrected.mp4'
if not output.exists(): render(clip,edited,output,preset='veryfast')
evidence['corrected_srt_roundtrip']=dict(status='passed',cue_count=len(parsed),
    timestamps_preserved=True,utf8_bom_crlf_supported=True,
    test_edit='First cue prefixed with 【校对测试】 solely to verify rendered imported text.',
    render=inspect(output))
try:
    render(clip,edited,clip)
except FileExistsError:
    evidence['source_overwrite_guard']='passed'
else: raise AssertionError('Source overwrite guard failed')

(ROOT/'evidence/video-test-20261109/pipeline-verification.json').write_text(
    json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(evidence,ensure_ascii=False,indent=2))
