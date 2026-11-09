import argparse
import json
import sys
from . import api

EXAMPLES = '''常用示例（在项目目录运行）：

1. 只识别并导出 SRT / JSON，交给第三方校对：
   python -m subtitle_tool transcribe "采访.mp4" --out "outputs/project-001" --env-file .private/provider-credentials.env

2. 只用校对后的 SRT 烧录 MP4，不调用识别接口：
   python -m subtitle_tool render "采访.mp4" --srt "校对后.srt" --out "带字幕.mp4"

3. 一次完成识别、导出字幕和烧录：
   python -m subtitle_tool run "采访.mp4" --out "outputs/project-002" --env-file .private/provider-credentials.env --burn

4. 使用项目医学热词：
   python -m subtitle_tool transcribe "采访.mp4" --out "outputs/project-003" --hotwords examples/medical-hotwords.json --env-file .private/provider-credentials.env

5. 切换阿里 FunASR：
   python -m subtitle_tool transcribe "采访.mp4" --out "outputs/project-004" --provider aliyun --hotwords examples/medical-hotwords.json --env-file .private/provider-credentials.env

6. 调大字号或指定中文字体：
   python -m subtitle_tool render "采访.mp4" --srt "校对后.srt" --out "带字幕-大字.mp4" --font-size 26 --font "Microsoft YaHei"

7. 测试不预先输入热词的通用能力，并烧录 MP4：
   python -m subtitle_tool run "采访.mp4" --out "outputs/no-hotwords" --no-medical-vocabulary --env-file .private/provider-credentials.env --burn
   此模式不要再传 --hotwords。

8. 客户端本地准备音频，交给 Gateway 提交识别：
   python -m subtitle_tool prepare "采访.mp4" --out "outputs/client-job"

9. 导入 Gateway 返回的腾讯结果，不调用云端、不清理文字：
   python -m subtitle_tool export --raw "腾讯结果.json" --metadata "outputs/client-job/prepare.json" --out "outputs/client-job/subtitles"

10. 使用包内字体烧录外部清理后的字幕：
   python -m subtitle_tool render "采访.mp4" --srt "清理后.srt" --out "成片.mp4" --font "Noto Sans CJK SC" --fonts-dir "assets/fonts"

说明：默认按原视频码率做高质量两遍编码，体积接近原片，音频原样复制。
白色粗体字、黑色描边、底部居中，字号 22；转写默认保守去除“呃、嗯”。
严格无损是可选模式：render 或 run --burn 添加 --lossless，文件通常明显变大。
同一任务目录可恢复查询，不会因等待超时自动重提。现有 MP4 不覆盖。
TXT 没有时间码，不能直接作为 --srt 的输入。
Python API 示例见 examples/api_examples.py。'''

def add_render_options(parser):
    parser.add_argument('--font',help='中文字体；Windows 默认微软雅黑，macOS 默认苹方')
    parser.add_argument('--fonts-dir',help='包内字体目录；使用时须同时通过 --font 指定字体家族名称')
    parser.add_argument('--font-size',type=int,default=22,help='相对画面缩放的字号，默认 22；26 更大')
    quality=parser.add_mutually_exclusive_group()
    quality.add_argument('--lossless',action='store_true',help='可选严格无损模式，体积通常较大；默认按源码率高质量编码')
    quality.add_argument('--crf',type=int,default=None,help='可选固定质量模式 1–51，0 为严格无损；不指定则按源码率两遍编码')
    parser.add_argument('--preset',default='medium',help='编码速度，默认 medium；可选 fast、slow 等')

def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(prog='subtitle',description='中文医学采访转写与 SRT 字幕烧录',
        epilog='示例：python -m subtitle_tool --examples\n详细参数：python -m subtitle_tool render --help',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--examples',action='store_true',help='显示常用命令与说明，不执行任务')
    sub=parser.add_subparsers(dest='command',metavar='{prepare,export,transcribe,render,run}')
    p=sub.add_parser('prepare',help='仅本地抽取 16 kHz 单声道 MP3，不读取凭据或上传')
    p.add_argument('video',help='输入视频路径')
    p.add_argument('--out',required=True,help='独立任务目录；完成后保存 prepare.json')
    p.add_argument('--bitrate-kbps',type=int,choices=[32,40,48,56,64],default=64,help='MP3 码率，默认 64 kbps；10 分钟约 4.8 MB')
    p=sub.add_parser('export',help='仅本地导入云端原始结果，导出原文 SRT 和词时间戳')
    p.add_argument('--raw',required=True,help='腾讯原始结果 JSON，支持 ResultDetail、Data、Response/Data 包装')
    p.add_argument('--metadata',required=True,help='prepare.json 或其 metadata 对象保存的 JSON')
    p.add_argument('--out',required=True,help='字幕输出目录')
    p.add_argument('--provider',choices=['tencent','aliyun'],default='tencent')
    p.add_argument('--clean-fillers',action='store_true',help='显式启用原有的“呃、嗯”清理；默认保留原文')
    for name in ['transcribe','run']:
        description='只转写并导出字幕' if name=='transcribe' else '转写、导出字幕，可同时烧录 MP4'
        suffix=' --burn' if name=='run' else ''
        p=sub.add_parser(name,help=description,description=description,
            epilog=f'示例：python -m subtitle_tool {name} "采访.mp4" --out "outputs/project-001" --env-file .private/provider-credentials.env{suffix}',
            formatter_class=argparse.RawDescriptionHelpFormatter)
        p.add_argument('video',help='输入视频路径')
        p.add_argument('--out',required=True,help='独立任务目录；同一视频和参数可恢复查询')
        p.add_argument('--provider',choices=['tencent','aliyun'],default='tencent',help='识别服务；默认 tencent')
        p.add_argument('--model',help='模型；腾讯默认 16k_zh_en_2.0，阿里默认 fun-asr')
        p.add_argument('--hotwords',help='项目热词 JSON 文件，与内置医学词表合并')
        p.add_argument('--no-medical-vocabulary',action='store_true',help='不使用内置医学词表')
        p.add_argument('--keep-fillers',action='store_true',help='保留“呃、嗯”等犹豫音')
        p.add_argument('--env-file',help='可选凭据文件；已有环境变量优先，值不输出')
        p.add_argument('--wait-seconds',type=int,default=600,help='本轮任务查询时间预算，默认 600 秒')
        if name=='run':
            p.add_argument('--burn',action='store_true',help='同时生成带字幕的 subtitled.mp4')
            add_render_options(p)
    p=sub.add_parser('render',help='仅将已有 SRT 烧录到 MP4',description='仅烧录 SRT，不需要云端凭据或识别调用',
        epilog='示例：python -m subtitle_tool render "采访.mp4" --srt "校对后.srt" --out "带字幕.mp4"',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('video',help='输入视频路径')
    p.add_argument('--srt',required=True,help='UTF-8 SRT；保留校对后的文字和时间码')
    p.add_argument('--out',required=True,help='新 MP4 文件路径，不覆盖现有文件')
    add_render_options(p)
    a=parser.parse_args(argv)
    if a.examples:
        print(EXAMPLES)
        return 0
    if not a.command:
        parser.print_help()
        return 2
    try:
        if a.command=='prepare':
            result=api.prepare(a.video,a.out,bitrate_kbps=a.bitrate_kbps,
                progress=lambda event: print(json.dumps(event,ensure_ascii=False),file=sys.stderr,flush=True))
        elif a.command=='export':
            from pathlib import Path
            raw=json.loads(Path(a.raw).read_text(encoding='utf-8-sig'))
            metadata=json.loads(Path(a.metadata).read_text(encoding='utf-8-sig'))
            result=api.export_transcript(raw,a.provider,a.out,metadata=metadata,clean_fillers=a.clean_fillers)
        elif a.command=='render':
            result=api.render(a.video,a.srt,a.out,font=a.font,fonts_dir=a.fonts_dir,font_size=a.font_size,crf=a.crf,lossless=a.lossless,preset=a.preset)
        else:
            if a.env_file:
                from .providers import load_credentials
                load_credentials(a.env_file)
            options=dict(provider=a.provider,model=a.model,vocabulary=a.hotwords,
                use_medical_vocabulary=not a.no_medical_vocabulary,clean_fillers=not a.keep_fillers,
                wait_seconds=a.wait_seconds,
                progress=lambda event: print(json.dumps(event,ensure_ascii=False),file=sys.stderr,flush=True))
            result=(api.run(a.video,a.out,burn=a.burn,
                    render_options=dict(font=a.font,fonts_dir=a.fonts_dir,font_size=a.font_size,crf=a.crf,lossless=a.lossless,preset=a.preset),
                    **options) if a.command=='run' else
                    api.transcribe(a.video,a.out,**options))
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['status']=='SUCCEEDED' else 2
    except Exception as exc:
        from .providers import clean
        print(json.dumps({'status':'ERROR','type':type(exc).__name__,'message':clean(str(exc))},ensure_ascii=False),file=sys.stderr)
        return 1

if __name__=='__main__':
    sys.exit(main())
