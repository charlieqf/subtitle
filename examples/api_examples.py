"""Python API examples. Import and call a function explicitly; running this file
only prints this help and does not upload media or create a cloud task.

Set TENCENT_SECRET_ID / TENCENT_SECRET_KEY or DASHSCOPE_API_KEY in the caller's
environment before transcription. Rendering requires no credentials.
"""
from subtitle_tool import transcribe, render, run

def transcribe_only(video, output_directory):
    return transcribe(video, output_directory,
        provider='tencent', model='16k_zh_en_2.0',
        vocabulary={'围绝经期': 5, '子宫内膜异位症': 5},
        clean_fillers=True, progress=lambda event: print(event))

def transcribe_without_hotwords(video, output_directory):
    return transcribe(video, output_directory, provider='tencent',
        model='16k_zh_en_2.0', use_medical_vocabulary=False, vocabulary=None)

def render_corrected_srt(video, corrected_srt, output_mp4):
    return render(video, corrected_srt, output_mp4, font_size=22)

def transcribe_and_render(video, output_directory):
    return run(video, output_directory, burn=True,
        vocabulary={'内异症': 5}, clean_fillers=True,
        render_options={'font_size': 22, 'preset': 'medium'})

def render_strictly_lossless(video, corrected_srt, output_mp4):
    return render(video, corrected_srt, output_mp4, lossless=True)

if __name__ == '__main__':
    print(__doc__)
