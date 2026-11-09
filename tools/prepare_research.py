"""Local, non-destructive media preparation for the ASR research."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tmp' / 'python-deps'))
import av
import imageio_ffmpeg
import numpy as np

OUT = ROOT / 'outputs' / 'research-20261109'
OUT.mkdir(parents=True, exist_ok=True)
EVIDENCE = ROOT / 'evidence' / 'video-test-20261109'
EVIDENCE.mkdir(parents=True, exist_ok=True)
source = ROOT / '字幕模拟视频1.mp4'
ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

def run(args, name):
    result = subprocess.run([ffmpeg, '-hide_banner', '-nostdin', *args], capture_output=True)
    (OUT / (name + '.log')).write_bytes(result.stderr)
    if result.returncode:
        raise RuntimeError(f'{name} failed; see local log')
    return result

with av.open(str(source)) as media:
    streams = []
    for s in media.streams:
        item = dict(index=s.index, type=s.type, codec=s.codec_context.name,
                    time_base=str(s.time_base), start_pts=s.start_time,
                    start_seconds=float(s.start_time * s.time_base) if s.start_time is not None else None,
                    duration_seconds=float(s.duration * s.time_base) if s.duration is not None else None)
        if s.type == 'audio':
            item.update(channels=s.codec_context.channels, sample_rate=s.codec_context.sample_rate,
                        layout=s.codec_context.layout.name)
        elif s.type == 'video':
            item.update(width=s.codec_context.width, height=s.codec_context.height,
                        frame_rate=str(s.average_rate))
        streams.append(item)
    probe = dict(source=source.name, bytes=source.stat().st_size,
                 sha256=hashlib.file_digest(source.open('rb'), 'sha256').hexdigest(),
                 duration_seconds=media.duration / 1000000, start_seconds=media.start_time / 1000000,
                 streams=streams, ffmpeg_version=imageio_ffmpeg.get_ffmpeg_version(),
                 pyav_version=av.__version__)

with av.open(str(source)) as media:
    audio = next(s for s in media.streams if s.type == 'audio')
    resampler = av.AudioResampler(format='fltp', layout='stereo', rate=16000)
    chunks = []
    first_pts = None
    for frame in media.decode(audio):
        if first_pts is None:
            first_pts = float(frame.pts * frame.time_base)
        for resampled in resampler.resample(frame):
            chunks.append(resampled.to_ndarray())
    for resampled in resampler.resample(None):
        chunks.append(resampled.to_ndarray())
    samples = np.concatenate(chunks, axis=1)
    probe['audio_analysis'] = dict(first_decoded_frame_seconds=first_pts,
        decoded_duration_seconds=samples.shape[1] / 16000,
        channel_rms=[float(v) for v in np.sqrt(np.mean(samples ** 2, axis=1))],
        channel_peak=[float(v) for v in np.max(np.abs(samples), axis=1)],
        channel_correlation=float(np.corrcoef(samples)[0, 1]),
        relative_channel_difference_rms=float(np.sqrt(np.mean((samples[0]-samples[1])**2)) /
                                              np.sqrt(np.mean(samples**2))))

for name, codec in [('audio.wav', 'pcm_s16le'), ('audio.flac', 'flac')]:
    if not (OUT / name).exists():
        run(['-n', '-i', str(source), '-map', '0:a:0', '-vn', '-ac', '1', '-ar', '16000',
             '-c:a', codec, str(OUT / name)], name)
    probe[name] = dict(bytes=(OUT / name).stat().st_size,
                      sha256=hashlib.file_digest((OUT / name).open('rb'), 'sha256').hexdigest())
if not (OUT / 'frames.jpg').exists():
    run(['-n', '-i', str(source), '-vf', 'fps=1/30,scale=480:-1,tile=4x2',
         '-frames:v', '1', '-q:v', '3', str(OUT / 'frames.jpg')], 'frames')
run(['-i', str(OUT / 'audio.wav'), '-af', 'silencedetect=noise=-35dB:d=0.4',
     '-f', 'null', '-'], 'silence')
(EVIDENCE / 'media.json').write_text(json.dumps(probe, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(probe, ensure_ascii=False, indent=2))
