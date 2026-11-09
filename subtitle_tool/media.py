"""Local media preparation. This module never imports cloud clients or credentials."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import uuid


def _write_json(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def _sha256(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def _ffmpeg():
    import imageio_ffmpeg
    configured = os.environ.get('IMAGEIO_FFMPEG_EXE')
    if configured and (not Path(configured).is_absolute() or not Path(configured).is_file()):
        raise ValueError('IMAGEIO_FFMPEG_EXE must be an existing absolute executable path')
    return imageio_ffmpeg.get_ffmpeg_exe()


def probe(video):
    import av
    video = Path(video).resolve()
    with av.open(str(video)) as media:
        videos = list(media.streams.video)
        audios = list(media.streams.audio)
        origin = (media.start_time or 0) / 1e6
        data = dict(source=str(video), duration_ms=round(media.duration / 1000) if media.duration else None,
            media_origin_seconds=origin, audio_tracks=len(audios),
            width=videos[0].codec_context.width if videos else None,
            height=videos[0].codec_context.height if videos else None,
            pixel_format=videos[0].codec_context.format.name if videos else None,
            video_bit_rate=videos[0].bit_rate if videos else None)
        if audios:
            first = next(media.decode(audios[0]), None)
            if first is None or first.pts is None:
                raise ValueError('Audio track has no decodable timestamped samples')
            data['audio_offset_ms'] = round((float(first.pts * first.time_base) - origin) * 1000)
            data['audio_first_sample_seconds'] = float(first.pts * first.time_base)
            data['audio_duration_ms'] = (round(float(audios[0].duration * audios[0].time_base) * 1000)
                                         if audios[0].duration else None)
        return data


def _inspect_audio(path):
    import av
    with av.open(str(path)) as media:
        if len(media.streams.audio) != 1:
            raise ValueError('Prepared audio must have exactly one audio stream')
        stream = media.streams.audio[0]
        samples = 0
        first_pts = None
        for frame in media.decode(stream):
            if frame.sample_rate != 16000 or len(frame.layout.channels) != 1:
                raise ValueError('Prepared audio must be 16 kHz mono')
            if first_pts is None:
                first_pts = float(frame.pts * frame.time_base) * 1000 if frame.pts is not None else 0
            samples += frame.samples
        if not samples:
            raise ValueError('Prepared audio has no decodable samples')
        return dict(sample_rate=16000, channels=1, decoded_samples=samples,
            decoded_duration_ms=samples / 16, first_decoded_pts_ms=first_pts,
            stream_start_ms=float(stream.start_time * stream.time_base) * 1000 if stream.start_time is not None else None,
            container_duration_ms=media.duration / 1000 if media.duration else None)


def _prepare(video, output_dir, *, bitrate_kbps=64, progress=None):
    """Implementation shared with transcribe; caller owns the task-directory lock."""
    if bitrate_kbps not in (32, 40, 48, 56, 64):
        raise ValueError('MP3 bitrate_kbps must be one of 32, 40, 48, 56, 64')
    emit = progress or (lambda event: None)
    video, output = Path(video).resolve(), Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    emit(dict(stage='probe', status='RUNNING'))
    metadata = probe(video)
    if not metadata['width']:
        raise ValueError('Input has no video stream')
    if not metadata['audio_tracks']:
        raise ValueError('Input has no audio track')
    if metadata['audio_offset_ms'] < 0:
        raise ValueError('Audio precedes the media origin; explicit alignment is required')
    metadata['source_sha256'] = _sha256(video)
    source_manifest = output / 'media.json'
    if source_manifest.exists():
        old = json.loads(source_manifest.read_text(encoding='utf-8'))
        if old.get('source_sha256') != metadata['source_sha256']:
            raise ValueError('Output directory belongs to another source; choose a new directory')
    parameters = dict(schema_version=1, codec='libmp3lame', format='mp3',
                      sample_rate=16000, channels=1, bitrate_kbps=bitrate_kbps,
                      timeline_filter='asetpts=PTS-STARTPTS,aresample=16000:async=1:first_pts=0')
    manifest = output / 'prepare.json'
    audio = output / 'audio.mp3'
    if manifest.exists():
        cached = json.loads(manifest.read_text(encoding='utf-8'))
        if cached.get('status') != 'SUCCEEDED' or cached.get('parameters') != parameters:
            raise ValueError('Preparation parameters changed; choose a new output directory')
        if cached['metadata']['source_sha256'] != metadata['source_sha256']:
            raise ValueError('Prepared audio belongs to another source')
        if (not audio.is_file() or audio.stat().st_size != cached['audio']['bytes'] or
                _sha256(audio) != cached['audio']['sha256']):
            raise ValueError('Prepared audio cache is missing or changed; choose a new output directory')
        cached['audio']['path'] = str(audio)
        cached['metadata']['source'] = str(video)
        cached['reused'] = True
        emit(dict(stage='prepare', status='REUSED', bytes=cached['audio']['bytes']))
        return cached
    _write_json(source_manifest, metadata)
    temporary = output / ('audio-' + uuid.uuid4().hex + '.part.mp3')
    emit(dict(stage='extract', status='RUNNING'))
    command = [_ffmpeg(), '-nostdin', '-hide_banner', '-xerror', '-n', '-i', str(video),
        '-map', '0:a:0', '-vn', '-af', parameters['timeline_filter'], '-ac', '1', '-ar', '16000',
        '-c:a', 'libmp3lame', '-b:a', str(bitrate_kbps) + 'k', '-write_xing', '1', str(temporary)]
    try:
        process = subprocess.run(command, capture_output=True)
        (output / 'prepare.log').write_bytes(process.stderr)
        if process.returncode:
            raise RuntimeError('Audio extraction failed; inspect prepare.log')
        info = _inspect_audio(temporary)
        size = temporary.stat().st_size
        if size >= 5_000_000:
            raise ValueError('Prepared audio must be smaller than 5,000,000 bytes; reduce duration or bitrate')
        if metadata.get('audio_duration_ms') and abs(info['decoded_duration_ms'] - metadata['audio_duration_ms']) > 150:
            raise ValueError('Decoded prepared audio duration differs from the source audio; inspect prepare.log')
        if _sha256(video) != metadata['source_sha256']:
            raise ValueError('Source video changed during preparation; choose a new task directory')
        metadata.update(asr_time_offset_ms=metadata['audio_offset_ms'],
                        asr_time_basis='decoded_audio_start',
                        preparation_schema_version=1)
        result = dict(status='SUCCEEDED', schema_version=1, reused=False, parameters=parameters,
            audio=dict(path=str(audio), format='mp3', codec='mp3', bytes=size,
                       sha256=_sha256(temporary), bitrate_kbps=bitrate_kbps, **info),
            metadata=metadata)
        temporary.replace(audio)
        _write_json(source_manifest, metadata)
        _write_json(manifest, result)
        emit(dict(stage='prepare', status='SUCCEEDED', bytes=size))
        return result
    finally:
        # This UUID-named, non-recursive temporary file belongs only to this invocation.
        temporary.unlink(missing_ok=True)


def prepare(video, output_dir, *, bitrate_kbps=64, progress=None):
    """Create/reuse checked 16 kHz mono MP3; no credentials or network operations."""
    from filelock import FileLock
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with FileLock(str(output / '.task.lock'), timeout=0):
        return _prepare(video, output, bitrate_kbps=bitrate_kbps, progress=progress)
