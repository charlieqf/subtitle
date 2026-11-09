# 客户端接入契约（0.2.0）

评审结论：客户端要求合理，已实现本地准备、结果导入和包内字体支持。默认音频改用实测更合适的 **16 kHz、单声道、64 kbps MP3**。Gateway、登录鉴权、密钥管理、Agent/prompt、清理审核及客户端 EXE 构建验收由客户端负责。

## 调用流程

```text
prepare → 客户端上传 audio.path 给 Gateway → Gateway 返回腾讯原始结果
        → export_transcript → 客户端 Agent 清理和用户审核 → 可选 render
```

三个本地操作不读取凭据、不上传、不创建云端任务。可在禁止网络连接的进程中运行。旧的 `transcribe` / `run --burn` 是另行保留的直接云端调用入口，不是桌面客户端的 Gateway 接入路径。

```python
from subtitle_tool import prepare, export_transcript, render

prepared = prepare(video, task_dir)  # 默认 bitrate_kbps=64
# 客户端把 prepared["audio"]["path"] 的文件交给 Gateway。
# raw 是 Gateway 返回的腾讯原始 JSON 对象。
exported = export_transcript(raw, "tencent", subtitle_dir,
                             metadata=prepared, clean_fillers=False)
# 客户端清理与审核后，将最终 SRT 路径传回来。
render(video, approved_srt, output_mp4,
       font="Noto Sans CJK SC", fonts_dir=bundled_fonts_dir)
```

CLI 等价用法：

```powershell
python -m subtitle_tool prepare "中文 采访.mp4" --out "任务 001"
python -m subtitle_tool export --raw "腾讯结果.json" --metadata "任务 001/prepare.json" --out "任务 001/字幕"
python -m subtitle_tool render "中文 采访.mp4" --srt "审核后.srt" --out "成片.mp4" --font "Noto Sans CJK SC" --fonts-dir "assets/fonts"
```

各命令均支持 `--help`；全局 `--examples` 输出示例。stdout 是 UTF-8 JSON；进度/错误走 stderr。退出码：0 成功，1 执行错误，2 参数错误或直接云端任务尚未完成。PowerShell 5.1 的 `>` 会另行转码；客户端应直接按 UTF-8 解码子进程字节流。

## prepare

签名：`prepare(video, output_dir, *, bitrate_kbps=64, progress=None) -> dict`。

选择第一音轨，计算源文件 SHA-256，抽取并完整解码检查 MP3；无音轨、无法解码、无样本或结果达到 5,000,000 字节时明确失败。客户端预检视频不超过 10 分钟和 2 GB；工具的字节数检查使用最终真实文件大小。`bitrate_kbps` 可为 32、40、48、56、64。

主要返回字段（完整结果同时保存为 `prepare.json`）：

| 字段 | 含义 |
| --- | --- |
| `status`, `schema_version`, `reused` | 成功状态、准备协议版本 1、是否复用 |
| `audio.path`, `audio.bytes`, `audio.sha256` | MP3 绝对路径、实际字节数、SHA-256 |
| `audio.format`, `audio.codec`, `audio.bitrate_kbps` | `mp3`、`mp3`、默认 64 |
| `audio.sample_rate`, `audio.channels` | 16000、1 |
| `audio.decoded_samples`, `audio.decoded_duration_ms` | 完整解码后的样本数和有效内容时长 |
| `audio.first_decoded_pts_ms`, `audio.stream_start_ms` | 编码文件的诊断时间戳，不是应加到字幕上的偏移 |
| `metadata.source`, `metadata.source_sha256` | 源视频绝对路径和身份 |
| `metadata.duration_ms`, `width`, `height`, `pixel_format`, `video_bit_rate` | 视频探测信息 |
| `metadata.media_origin_seconds`, `audio_first_sample_seconds`, `audio_offset_ms` | 容器起点、首个有效音频样本时间、二者之差 |
| `metadata.asr_time_offset_ms`, `asr_time_basis` | 导入时应用的偏移；当前基准为 `decoded_audio_start` |
| `parameters` | 编码和时间轴参数，用于重复准备时核对 |

同目录由文件锁串行保护。每次核对源 SHA-256，已完成且参数、音频 SHA-256 和大小一致时复用。不同源、不同参数或损坏的已完成缓存明确报错，应使用新任务目录。编码中间文件不作为完成结果复用，只有成功验证后才提交 `prepare.json`。源视频在准备过程中变化也会失败。

## export_transcript

签名：`export_transcript(raw, provider, output_dir, *, metadata=None, clean_fillers=False) -> dict`。

客户端应传入完整 `prepare` 结果或其 `metadata`，不要省略。腾讯输入支持三种形状：直接含 `ResultDetail` 的对象、`{"Data": ...}`、`{"Response": {"Data": ...}}`；需要成功任务的详细词时间戳结果。推荐 Gateway 请求 `EngineModelType=16k_zh_en_2.0`、`ChannelNum=1`、`ResTextFormat=3`、`FilterModal=0`，保留原文，避免在云端启用口语改写。

返回 `status`、`srt`（`captions.srt`）、`raw_srt`（`raw.srt`）、`json`（`transcript.json`）、`cue_count` 和 `removed_fillers`。路径均为绝对路径。默认不删词、不做医学清理；两个 SRT 都经过字幕排版，不等于厂商原始 JSON。可直接把 `raw.srt` 交给客户端清理。

`transcript.json` 的 `schema_version=2`：`provider_segments` 保存厂商音频坐标下的语句/词时间戳，`source_segments` 和 `captions` 使用视频坐标，`timeline.applied_offset_ms` 记录本次偏移。原始输入和 metadata 不被原地修改；重复导入同一原始对象不会累加偏移。拒绝把已经归一化的 transcript 再当作腾讯原始结果导入。

偏移公式为：厂商词偏移 + 厂商句起点 + `asr_time_offset_ms`。不要在 Gateway 或客户端再加一遍。若是旧 metadata，则兼容使用 `audio_offset_ms`。

实测 MP3 文件首个解码 PTS 为 69.0625 ms，这是 gapless 编码时间信息；解码波形与源音频对齐，腾讯结果也未出现该数值的固定延迟，因此**不要把这个 PTS 加进字幕**。详见[验收报告](validation-0.2.0.zh-CN.md)。

## render

签名：`render(video, srt, output, *, font=None, fonts_dir=None, font_size=22, crf=None, lossless=False, preset="medium") -> dict`。

接受 UTF-8 / UTF-8 BOM、LF / CRLF SRT。按传入文字和时间码烧录，不重识别、不清理；检查负时间、倒序、重叠、空文本和超过视频时长。输出文件必须是新 MP4，不覆盖原片或已有成片。

默认源码率两遍 H.264、音频复制；白色粗体、黑色描边、底部居中。`fonts_dir` 支持中文和空格路径，读取其中的 TTF/OTF/TTC/OTC，暂存到本次渲染目录供 libass 加载；必须同时通过 `font` 指定**字体家族名称**。渲染日志保留实际 `fontselect` 记录。包内 FFmpeg 通过绝对路径环境变量 `IMAGEIO_FFMPEG_EXE` 指定，不另设同义参数。

兼容性：新转写任务改用 MP3；已有 0.1.x FLAC 云端任务仍按原音频身份恢复。`export_transcript` 的公开默认值是保留原文，原有 `transcribe` 的保守犹豫音清理默认行为保持不变。

分发和固定依赖见[分发说明](distribution.zh-CN.md)。
