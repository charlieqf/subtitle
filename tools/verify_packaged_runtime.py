"""Run with the installed wheel in an isolated Python 3.12 runtime; no cloud use."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import winreg

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/client-handoff-20261109'


def main():
    import subtitle_tool
    from subtitle_tool import prepare,export_transcript,render
    assert sys.version_info[:2]==(3,12)
    assert 'site-packages' in subtitle_tool.__file__
    for name in list(os.environ):
        if name.startswith(('TENCENT_','DASHSCOPE_','ALIYUN_')): os.environ.pop(name)
    def forbidden(*args,**kwargs):
        raise AssertionError('Local flow attempted a network connection')
    socket.socket.connect=forbidden
    socket.create_connection=forbidden
    runtime=Path(sys.executable).parent
    packaged_binary=runtime/'site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe'
    binary_dir=OUT/'中文 包内依赖';binary_dir.mkdir(exist_ok=True)
    binary=binary_dir/'ffmpeg 程序.exe'
    if not binary.exists(): shutil.copy2(packaged_binary,binary)
    os.environ['IMAGEIO_FFMPEG_EXE']=str(binary.resolve())
    prepared=prepare(ROOT/'字幕模拟视频1.mp4',OUT/'python312 prepare')
    raw=json.loads((ROOT/'outputs/research-20261109/tencent-large-mp3-64k/transcription-0.json').read_text(encoding='utf-8'))
    assert hashlib.sha256(Path(prepared['audio']['path']).read_bytes()).hexdigest()==json.loads(
        (OUT/'interview-mp3-64k/prepare.json').read_text(encoding='utf-8'))['audio']['sha256']
    exported=export_transcript(raw,'tencent',OUT/'python312 export',metadata=prepared)
    installed=[]
    for hive in [winreg.HKEY_LOCAL_MACHINE,winreg.HKEY_CURRENT_USER]:
        try:
            with winreg.OpenKey(hive,r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts') as key:
                index=0
                while True:
                    try: name,value,_=winreg.EnumValue(key,index)
                    except OSError: break
                    if 'noto' in name.lower() and 'cjk' in name.lower(): installed.append(name)
                    index+=1
        except FileNotFoundError: pass
    assert not installed,installed
    fonts=binary_dir/'中文 字体';fonts.mkdir(exist_ok=True)
    for name in ['NotoSansCJKsc-Regular.otf','LICENSE.txt']:
        shutil.copy2(ROOT/'tmp/client-handoff/bundled fonts'/name,fonts/name)
    rendered=render(OUT/'font-input-8s.mp4',OUT/'font-corrected.srt',OUT/'python312-font-preview.mp4',
                    font='Noto Sans CJK SC',fonts_dir=fonts)
    log=Path(rendered['video']).with_suffix('.render.log').read_text(encoding='utf-8',errors='replace')
    selections=[line.split('] ',1)[-1] for line in log.splitlines() if 'fontselect:' in line or 'Loading font' in line]
    assert any('-> NotoSansCJKsc-Regular' in line for line in selections)
    cli={}
    for args in [['--help'],['--examples'],['prepare','--help'],['export','--help'],['render','--help']]:
        result=subprocess.run([sys.executable,'-m','subtitle_tool',*args],capture_output=True,check=True)
        result.stdout.decode('utf-8',errors='strict')
        cli[' '.join(args)]=True
    # Real CLI stdout is UTF-8 JSON; the progress channel remains stderr.
    result=subprocess.run([sys.executable,'-m','subtitle_tool','prepare',prepared['metadata']['source'],
        '--out',str(OUT/'python312 prepare')],capture_output=True,check=True)
    assert json.loads(result.stdout.decode('utf-8'))['reused']
    assert json.loads(result.stderr.decode('utf-8').splitlines()[0])['stage']=='probe'
    evidence=dict(python=sys.version,tool_version=subtitle_tool.__version__,
        installed_wheel_import=True,credentials_present=False,network_blocked=True,
        audio_bytes=prepared['audio']['bytes'],same_audio_as_314=True,
        export_cues=exported['cue_count'],export_removed_fillers=exported['removed_fillers'],
        rendered=dict(width=rendered['probe']['width'],height=rendered['probe']['height'],
                      encoding=rendered['encoding']),font_family_installed=False,font_log=selections,
        unicode_space_paths=True,explicit_ffmpeg_path=True,utf8_cli_json=True,cli=cli,
        ffmpeg_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        font_sha256=hashlib.sha256((fonts/'NotoSansCJKsc-Regular.otf').read_bytes()).hexdigest())
    (ROOT/'evidence/client-handoff-20261109/packaged-runtime-verification.json').write_text(
        json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
