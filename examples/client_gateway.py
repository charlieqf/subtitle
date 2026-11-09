"""Local boundaries for a desktop client's own Gateway/Agent orchestration.

No HTTP transport, credentials, Gateway service, or Agent prompt is implemented here.
"""
from subtitle_tool import prepare, export_transcript, render


def prepare_for_gateway(video, task_dir):
    return prepare(video, task_dir, bitrate_kbps=64)


def accept_gateway_result(raw_tencent_result, prepared, subtitle_dir):
    return export_transcript(raw_tencent_result, 'tencent', subtitle_dir,
                             metadata=prepared, clean_fillers=False)


def render_approved_srt(video, approved_srt, output_mp4, bundled_fonts_dir):
    return render(video, approved_srt, output_mp4,
                  font='Noto Sans CJK SC', fonts_dir=bundled_fonts_dir)


if __name__ == '__main__':
    print(__doc__)
