# Windows 客户端分发说明

交付版本为 0.2.0，已在独立 **CPython 3.12.10 Windows x64** 环境安装 wheel 并验证。工具源码要求 Python 3.11+；本次不以 3.10 为兼容目标。用户不需要自行安装 Python 或 FFmpeg，客户端构建时将运行时和依赖随应用分发。

## 构建端安装

固定的 Windows CPython 3.12 依赖及 wheel SHA-256 见 [requirements-win-py312.lock](../requirements-win-py312.lock)。锁文件包括直接及传递依赖，限 Windows x64，不能直接用于 macOS。

```powershell
py -3.12 -m pip download --require-hashes -r requirements-win-py312.lock -d wheelhouse
py -3.12 -m pip install --no-index --find-links wheelhouse --require-hashes -r requirements-win-py312.lock --target bundle/python/site-packages
py -3.12 -m pip install --no-deps --target bundle/python/site-packages dist/medical_subtitle_tool-0.2.0-py3-none-any.whl
```

也可使用 Python 官方嵌入式运行时，将 `python312._pth` 配置为包含 `site-packages`。这次验收实际使用官方 [Python 3.12.10 Windows 嵌入式包](https://www.python.org/downloads/release/python-31210/)，与系统 Python 隔离；最终安装包的 Python 维护版本与安全更新由客户端团队管理。

## 原生文件和 FFmpeg

- `av` wheel 包含本机原生扩展及 FFmpeg 共享库。完整保留其 `.pyd`、DLL、关联目录和许可证文件，不能只复制 Python 文件。[PyAV 安装说明](https://pyav.basswood.io/docs/stable/overview/installation.html)。
- `imageio-ffmpeg` Windows wheel 带独立 FFmpeg 可执行文件。本次为 `ffmpeg-win-x86_64-v7.1.exe`。可以保留在包内原位置，也可以放到应用资源目录，然后设置 `IMAGEIO_FFMPEG_EXE` 为该 EXE 的绝对路径；工具会拒绝不存在或相对路径的覆盖值。[imageio-ffmpeg 配置说明](https://github.com/imageio/imageio-ffmpeg#environment-variables)。
- 工具启动时不在线下载 FFmpeg。打包后的进程必须能启动 EXE、载入 PyAV DLL，并能写入任务目录和系统临时目录。
- 自行替换 FFmpeg 时，需要包含 `libmp3lame`、`libx264`、`subtitles`/libass 和中文字体加载支持；更换构建后重新跑准备、延迟及字体测试。
- 本次 FFmpeg 构建含 `--enable-gpl` / `libx264`。发行方需按所选二进制及依赖的实际许可证保留声明并处理源码分发等要求，不能把 imageio Python 包的许可证当成 FFmpeg 二进制的许可证。[FFmpeg 许可证说明](https://github.com/FFmpeg/FFmpeg/blob/master/LICENSE.md)。

## 中文字体

验证用字体为未安装到系统的 **Noto Sans CJK SC Regular**：

- [字体源文件](https://github.com/notofonts/noto-cjk/blob/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf)
- [SIL Open Font License 1.1](https://github.com/notofonts/noto-cjk/blob/main/Sans/LICENSE)

将字体和许可证放在 `assets/fonts`，调用 `render(..., font="Noto Sans CJK SC", fonts_dir=...)`。不需要向 Windows 安装字体。此字体允许按 OFL 条件随应用分发，保留版权和许可证；不要从本机复制微软雅黑或苹方作为默认分发素材。

## 客户端安装包验收

工具侧已提供无凭据、禁止网络的本地流程测试以及包内字体命中证据。客户端仍需在实际 EXE 中确认：能找到运行时与 DLL/EXE/字体、按 UTF-8 捕获 stdout/stderr、任务目录可写、真实 Gateway 返回结果能导入、用户确认后的 SRT 能烧录。Gateway、Agent 和桌面 UI 不在本工具的验收范围。
