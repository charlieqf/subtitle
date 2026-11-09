# 医学采访字幕工具

当前版本 **0.2.0**。客户端接入契约见 [docs/client-handoff.zh-CN.md](docs/client-handoff.zh-CN.md)，分发与固定依赖见 [docs/distribution.zh-CN.md](docs/distribution.zh-CN.md)。

Python 3.11+。提供命令行与 Python API：中文转写、医学热词、保守去除“呃、嗯”，以及独立的 SRT 字幕烧录。外部校对后的 SRT 按原文字和时间码使用，不自动润色。

## 安装与帮助

```powershell
python -m pip install -e .
python -m subtitle_tool --help
python -m subtitle_tool --examples
python -m subtitle_tool render --help
```

安装后也可使用 `subtitle` 命令；若不在 PATH 中，使用上面的 `python -m subtitle_tool`。

## 三种用法

**只识别，导出字幕供第三方校对：**

```powershell
python -m subtitle_tool transcribe "采访.mp4" --out "outputs/project-001" --env-file .private/provider-credentials.env
```

**只用校对后的 SRT 烧录 MP4，不调用识别接口：**

```powershell
python -m subtitle_tool render "采访.mp4" --srt "校对后.srt" --out "带字幕.mp4"
```

**识别并烧录：**

```powershell
python -m subtitle_tool run "采访.mp4" --out "outputs/project-002" --env-file .private/provider-credentials.env --burn
```

字幕默认白色粗体、全不透明黑色描边、底部居中，字号 22，留有底部边距。`render` 和 `run --burn` 可用 `--font-size 26` 调大字号，或用 `--font` 指定中文字体。现有文件不会被覆盖。

**默认目标：不明显降低画质，体积接近原片。** 使用 H.264 两遍编码，以原视频流的平均码率为目标，保持原像素格式、分辨率和帧率，音频原样复制。第一遍分析画面复杂度，第二遍分配码率并生成 MP4；两遍都读取原视频，不会重复压缩第一遍的成片。它比单遍耗时更长，但更适合控制总大小。相同码率不保证逐像素相同，也不保证所有素材都无明显损失；本仓库样本的画质与体积验证见实测报告。

可选 `--lossless` 使用严格无损的 QP 0 模式，文件通常明显增大；`--crf 0` 保留为其兼容写法。可选 `--crf 18` 等非零值按质量编码，不再以接近原片大小为目标。`--lossless` 与 `--crf` 不能同时使用。

## 常用选项与输出

- 默认腾讯文件大模型 `16k_zh_en_2.0`；`--provider aliyun` 切换至阿里 `fun-asr`。
- **测试无热词通用能力**：加 `--no-medical-vocabulary`，并且不要传 `--hotwords`。例如 `python -m subtitle_tool run "采访.mp4" --out "outputs/no-hotwords" --no-medical-vocabulary --env-file .private/provider-credentials.env --burn`。
- `--hotwords examples/medical-hotwords.json`：补充专科词、人名、药名。JSON 格式为 `{"内异症": 5}`，权重 1–10。与内置初始医学词表合并。
- `--keep-fillers`：保留犹豫音。默认只保守去除“呃、嗯”，不删改医学结论、否定词或重复表达。
- 任务目录输出 `captions.srt`、`raw.srt`、`transcript.json`、`transcript.txt`；`run --burn` 另输出 `subtitled.mp4`。
- 原命令使用同一任务目录可以恢复查询；提交状态不明时不会自动重提。同一目录由文件锁保护，不同时提交多个任务。

转写凭据可由调用方注入环境变量：腾讯需要 `TENCENT_SECRET_ID`、`TENCENT_SECRET_KEY`，阿里需要 `DASHSCOPE_API_KEY`。`--env-file` 为可选加载方式，已有环境变量优先。只烧录无需任何云端凭据。

Python API 与热词示例见 [examples/api_examples.py](examples/api_examples.py) 和 [examples/medical-hotwords.json](examples/medical-hotwords.json)。命令行最终结果为 stdout 中的一条 JSON，进度与错误写入 stderr；退出码 0 表示成功，2 表示任务尚未完成或命令参数错误，1 表示执行错误。

## 外部客户端接入

使用 Gateway 的客户端编排 `prepare → Gateway 识别 → export → 外部 Agent 清理与用户审核 → 可选 render`。`prepare`、`export`、`render` 都是本地操作，不需要云端凭据。Agent 的调用、prompt 和清理逻辑由客户端负责；`run --burn` 是另行保留的直接云端识别并烧录入口。

```powershell
python -m subtitle_tool prepare "采访.mp4" --out "outputs/client-job"
python -m subtitle_tool export --raw "腾讯结果.json" --metadata "outputs/client-job/prepare.json" --out "outputs/client-job/subtitles"
```

`prepare` 默认抽取 16 kHz、单声道、64 kbps MP3，10 分钟约 4.8 MB，并核对实际大小。`export` 默认保留原文；客户端可取 `raw.srt` 和包含原始词时间戳的 `transcript.json`。详细 Python 示例见 [examples/client_gateway.py](examples/client_gateway.py)。

交给外部清理时，可使用 `raw.srt`；如需 `captions.srt` 也保留犹豫音，转写时添加 `--keep-fillers`，Python API 对应 `clean_fillers=False`。`transcript.json` 保留原始词时间戳，供客户端按需使用。`raw.srt` 也经过字幕排版，并非云厂商的原始响应。

外部返回的 SRT 可直接传给 `render`。本工具检查格式与时间轴合法性，按其文字和时间码烧录。口语清理、绝对化表述处理、语义断句、每条不超过 25 字、缩写展开及剂量单位规范由外部清理环节负责。

## 当前验证范围

本仓库样本已在 Windows 完成真实转写、SRT 导出、第三方修改格式往返和完整视频烧录。macOS 使用跨平台依赖与苹方字体配置，尚待目标机器验证。

已验证 Python 3.12 Windows x64 安装 wheel 后，无凭据完成本地准备、导入和包内字体烧录。默认选第一音轨并转单声道；音频达到 5,000,000 字节会明确报错。阿里直接转写入口仍使用测试用临时上传。更长素材的托管、多音轨选择和完整医学词库仍需补齐。内置词表目前只有 12 条初始词。

无时间码的 TXT 可用于文字校对和质量评测，不能直接传给 `--srt`。建议第三方保留并返回 SRT 时间码；仅有 TXT 时需另外恢复并复核时间轴。

本次实测结果见 [0.2.0 验收报告](docs/validation-0.2.0.zh-CN.md)。
