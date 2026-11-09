"""Verify every frame of the current lossless render, including the subtitle burn."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import av
import imageio_ffmpeg

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'outputs/research-20261109/lossless-verification'
WORK.mkdir(parents=True,exist_ok=True)
SOURCE=ROOT/'字幕模拟视频1.mp4'
OUTPUT=ROOT/'outputs/research-20261109/tencent-large-no-hotwords-lossless.mp4'
SRT=ROOT/'outputs/research-20261109/tencent-large-baseline/captions.srt'
FFMPEG=imageio_ffmpeg.get_ffmpeg_exe()

def inspect(path):
    with av.open(str(path)) as container:
        video=container.streams.video[0]
        audio=container.streams.audio[0]
        digest=hashlib.sha256()
        for packet in container.demux(audio):
            if packet.size:digest.update(bytes(packet))
        return dict(bytes=path.stat().st_size,duration_seconds=container.duration/1e6,
            video_frames=video.frames,frame_rate=str(video.average_rate),
            width=video.codec_context.width,height=video.codec_context.height,
            pixel_format=video.codec_context.format.name,profile=video.codec_context.profile,
            video_bit_rate=video.bit_rate,video_start=float(video.start_time*video.time_base),
            audio_start=float(audio.start_time*audio.time_base),audio_packet_sha256=digest.hexdigest())

original=inspect(SOURCE)
rendered=inspect(OUTPUT)
for key in ['duration_seconds','video_frames','frame_rate','width','height','pixel_format',
            'video_start','audio_start','audio_packet_sha256']:
    assert original[key]==rendered[key], (key,original[key],rendered[key])

from subtitle_tool.captions import parse_srt,to_srt
normalized=to_srt(parse_srt(SRT.read_text(encoding='utf-8-sig')))
(WORK/'captions.srt').write_text(normalized,encoding='utf-8')
style=('FontName=Microsoft YaHei,FontSize=22,Bold=-1,PrimaryColour=&H00FFFFFF,'
       'OutlineColour=&H00000000,BorderStyle=1,Outline=2.2,Shadow=0,MarginV=18,Alignment=2')
filters=(
    '[0:v]split=2[original0][original1];'
    '[1:v]split=2[encoded0][encoded1raw];'
    '[original0]crop=1920:840:0:0,settb=AVTB,setpts=PTS-STARTPTS[originalcrop];'
    '[encoded0]crop=1920:840:0:0,settb=AVTB,setpts=PTS-STARTPTS[encodedcrop];'
    # Keep the original time base until AFTER subtitle rendering. Converting it
    # beforehand changes rounding at exact cue boundaries (e.g. 33.200 seconds).
    f"[original1]subtitles=captions.srt:force_style='{style}',settb=AVTB,setpts=PTS-STARTPTS[expected];"
    '[encoded1raw]settb=AVTB,setpts=PTS-STARTPTS[encoded1];'
    '[encodedcrop][originalcrop]psnr=stats_file=outside-subtitle-band.txt[outside];'
    '[encoded1][expected]psnr=stats_file=full-frame-after-burn.txt[full]')
command=[FFMPEG,'-hide_banner','-nostdin','-threads','2','-i',str(SOURCE),'-threads','2','-i',str(OUTPUT),
    '-filter_complex_threads','2','-filter_complex',filters,'-map','[outside]','-map','[full]','-an','-f','null','-']
result=subprocess.run(command,cwd=WORK,capture_output=True)
(WORK/'verification.log').write_bytes(result.stderr)
if result.returncode: raise RuntimeError('Pixel comparison failed; inspect verification.log')
comparisons={}
for filename in ['outside-subtitle-band.txt','full-frame-after-burn.txt']:
    text=(WORK/filename).read_text()
    values=re.findall(r'psnr_avg:([^\s]+)',text)
    assert len(values)==original['video_frames'], (filename,len(values))
    nonidentical=[index for index,value in enumerate(values) if value!='inf']
    assert not nonidentical, (filename,'Nonidentical frame indexes',nonidentical[:10])
    comparisons[filename]=dict(frames=len(values),different_frames=0,psnr='infinity',pixel_identical=True)
evidence=dict(status='passed',source=original,rendered=rendered,
    comparisons=comparisons,subtitle_band_exclusion='Bottom 240 pixels excluded for source comparison.',
    full_frame_comparison='All decoded output pixels match the source with the same subtitle overlay, before encoding.',
    srt_sha256=hashlib.sha256(SRT.read_bytes()).hexdigest(),
    source_srt=str(SRT.relative_to(ROOT)),output=str(OUTPUT.relative_to(ROOT)))
(ROOT/'evidence/video-test-20261109/lossless-verification.json').write_text(
    json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(evidence,ensure_ascii=False,indent=2))
