"""Compare decoded video samples, excluding the deliberately changed subtitle area."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import re
import statistics
import subprocess
import av
import imageio_ffmpeg

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--rendered',default='outputs/research-20261109/tencent-large-subtitled.mp4')
parser.add_argument('--output-dir',default='outputs/research-20261109/quality-check')
parser.add_argument('--evidence',default='evidence/video-test-20261109/video-quality.json')
parser.add_argument('--render-result',help='JSON emitted by the render command')
parser.add_argument('--verify-source-size',action='store_true',help='Require file size within 5 percent of the source')
args=parser.parse_args()
OUT=ROOT/args.output_dir
OUT.mkdir(parents=True,exist_ok=True)
SOURCE=ROOT/'字幕模拟视频1.mp4'
RENDERED=ROOT/args.rendered
FFMPEG=imageio_ffmpeg.get_ffmpeg_exe()

def metadata(path):
    with av.open(str(path)) as container:
        streams=[]
        for stream in container.streams:
            ctx=stream.codec_context
            item=dict(type=stream.type,codec=ctx.name,bit_rate=stream.bit_rate,
                start_seconds=float(stream.start_time*stream.time_base) if stream.start_time is not None else None)
            if stream.type=='video':
                item.update(width=ctx.width,height=ctx.height,frame_rate=str(stream.average_rate),
                    frames=stream.frames,pixel_format=ctx.format.name,profile=ctx.profile,
                    color_range=ctx.color_range,colorspace=ctx.colorspace,
                    color_primaries=ctx.color_primaries,color_trc=ctx.color_trc)
            streams.append(item)
        audio_digest=hashlib.sha256()
        for packet in container.demux(*container.streams.audio):
            if packet.size: audio_digest.update(bytes(packet))
        return dict(file=str(path.relative_to(ROOT)),bytes=path.stat().st_size,
                    audio_packet_sha256=audio_digest.hexdigest(),
                    duration_seconds=container.duration/1e6,bit_rate=container.bit_rate,streams=streams)

encoding=dict(codec='libx264',crf=20,preset='fast',audio='copy')
if args.render_result:
    raw=(ROOT/args.render_result).read_bytes()
    encoding=json.loads(raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig'))['encoding']
data=dict(source=metadata(SOURCE),rendered=metadata(RENDERED),
          encoding=encoding,
          sampling='One original frame every 30 frames, paired by identical frame index.',
          regions=dict(main=[0,0,1920,900],face_and_upper_body=[620,380,640,480]),
          interpretation='SSIM and PSNR are similarity diagnostics, not a percentage of preserved quality. '
          'The bottom 180 pixels containing burned subtitles are excluded from the main region.')
source_video=next(s for s in data['source']['streams'] if s['type']=='video')
rendered_video=next(s for s in data['rendered']['streams'] if s['type']=='video')
checks={key:source_video[key]==rendered_video[key] for key in
    ['width','height','frame_rate','frames','pixel_format','start_seconds','color_range','colorspace','color_primaries','color_trc']}
checks.update(duration=data['source']['duration_seconds']==data['rendered']['duration_seconds'],
    audio_packets_identical=data['source']['audio_packet_sha256']==data['rendered']['audio_packet_sha256'])
source_audio=next(s for s in data['source']['streams'] if s['type']=='audio')
rendered_audio=next(s for s in data['rendered']['streams'] if s['type']=='audio')
checks['audio_start']=source_audio['start_seconds']==rendered_audio['start_seconds']
data['file_size_change_percent']=100*(data['rendered']['bytes']/data['source']['bytes']-1)
if args.verify_source_size:
    checks['file_size_within_5_percent']=abs(data['file_size_change_percent'])<=5
data['checks']=checks
assert all(checks.values()), checks
print(json.dumps(data,ensure_ascii=False),flush=True)
filters=[]
for index,prefix in [(0,'r'),(1,'d')]:
    filters.append(f'[{index}:v]select=not(mod(n\\,30)),setpts=N/TB,split=2[{prefix}a][{prefix}b]')
    filters.append(f'[{prefix}a]crop=1920:900:0:0,split=2[{prefix}ms][{prefix}mp]')
    filters.append(f'[{prefix}b]crop=640:480:620:380,split=2[{prefix}fs][{prefix}fp]')
for region,tag in [('main','m'),('face','f')]:
    filters.append(f'[d{tag}s][r{tag}s]ssim=stats_file=ssim-{region}.txt[s{tag}]')
    filters.append(f'[d{tag}p][r{tag}p]psnr=stats_file=psnr-{region}.txt[p{tag}]')
command=[FFMPEG,'-hide_banner','-nostdin','-threads','2','-i',str(SOURCE),'-threads','2','-i',str(RENDERED),
      '-filter_complex_threads','2','-filter_complex',';'.join(filters),
      '-map','[sm]','-map','[pm]','-map','[sf]','-map','[pf]','-an','-f','null','-']
result=subprocess.run(command,cwd=OUT,capture_output=True)
(OUT/'metrics.log').write_bytes(result.stderr)
if result.returncode:
    raise RuntimeError('FFmpeg comparison failed; see quality-check/metrics.log')
data['metrics']={}
for region in ['main','face']:
    ssim=[float(x) for x in re.findall(r'All:([0-9.]+)',(OUT/f'ssim-{region}.txt').read_text())]
    mse=[float(x) for x in re.findall(r'mse_avg:([0-9.]+)',(OUT/f'psnr-{region}.txt').read_text())]
    data['metrics'][region]=dict(sample_frames=len(ssim),mean_ssim=statistics.mean(ssim),
        minimum_ssim=min(ssim),minimum_ssim_time_seconds=ssim.index(min(ssim)),
        aggregate_psnr_db=10*math.log10(255**2/statistics.mean(mse)))

data['visual_samples']=[]
selected={seconds*30:seconds for seconds in [3,111,169]}
for label,source in [('source',SOURCE),('rendered',RENDERED)]:
    with av.open(str(source)) as container:
        for index,frame in enumerate(container.decode(video=0)):
            if index in selected:
                seconds=selected[index]
                full=frame.to_image()
                full.save(OUT/f'{label}-{seconds}-full.png')
                full.crop((620,380,1260,860)).save(OUT/f'{label}-{seconds}.png')
                data['visual_samples'].append(dict(file=f'{label}-{seconds}-full.png',
                    frame_index=index,time_seconds=float(frame.pts*frame.time_base)))
            if index>=max(selected): break

(ROOT/args.evidence).write_text(
    json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(data['metrics'],ensure_ascii=False,indent=2),flush=True)
