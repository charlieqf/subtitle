"""Real FFmpeg integration tests; no cloud credentials or cloud calls."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
import json
import os
import subprocess
from subtitle_tool import prepare, export_transcript, render, transcribe, probe
from subtitle_tool.media import _ffmpeg, _sha256


class LocalMediaTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=TemporaryDirectory(prefix='subtitle-test-')
        cls.root=Path(cls.directory.name)
        cls.source=cls.root/'中文 采访.mp4'
        cls.binary=Path(_ffmpeg())
        result=subprocess.run([str(cls.binary),'-nostdin','-hide_banner','-n',
            '-f','lavfi','-i','testsrc2=s=320x180:r=25:d=4',
            '-itsoffset','1','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=3',
            '-c:v','libx264','-preset','ultrafast','-c:a','aac',str(cls.source)],capture_output=True)
        if result.returncode: raise RuntimeError(result.stderr.decode(errors='replace'))

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_prepare_reuse_source_change_and_cache_corruption(self):
        out=self.root/'reuse'
        first=prepare(self.source,out)
        audio=Path(first['audio']['path'])
        modified=audio.stat().st_mtime_ns
        self.assertFalse(first['reused'])
        self.assertGreater(first['metadata']['audio_offset_ms'],900)
        self.assertLess(first['metadata']['audio_offset_ms'],1100)
        self.assertLess(first['audio']['bytes'],5_000_000)
        self.assertTrue(prepare(self.source,out)['reused'])
        self.assertEqual(modified,audio.stat().st_mtime_ns)
        with self.assertRaisesRegex(ValueError,'parameters changed'):
            prepare(self.source,out,bitrate_kbps=32)
        changed=self.root/'changed.mp4'
        changed.write_bytes(self.source.read_bytes()+b'changed-source-identity')
        with self.assertRaisesRegex(ValueError,'another source'):
            prepare(changed,out)
        audio.write_bytes(b'incomplete')
        with self.assertRaisesRegex(ValueError,'cache'):
            prepare(self.source,out)

    def test_incomplete_audio_without_manifest_is_never_reused(self):
        out=self.root/'incomplete'
        out.mkdir()
        (out/'audio.mp3').write_bytes(b'interrupted extraction')
        result=prepare(self.source,out)
        self.assertFalse(result['reused'])
        self.assertGreater(result['audio']['decoded_samples'],30000)
        self.assertEqual(list(out.glob('*.part.mp3')),[])

    def test_no_audio_and_undecodable_input(self):
        silent=self.root/'无音轨.mp4'
        subprocess.run([str(self.binary),'-nostdin','-hide_banner','-n','-i',str(self.source),
                        '-map','0:v:0','-c','copy',str(silent)],capture_output=True,check=True)
        with self.assertRaisesRegex(ValueError,'no audio track'):
            prepare(silent,self.root/'silent')
        invalid=self.root/'broken.mp4'
        invalid.write_bytes(b'not a media file')
        with self.assertRaises(Exception): prepare(invalid,self.root/'broken')
        self.assertFalse((self.root/'broken/prepare.json').exists())

    def test_offline_import_render_and_packaged_ffmpeg_path(self):
        # socket.connect is denied so accidental networking cannot pass this test.
        with mock.patch.dict(os.environ,{'IMAGEIO_FFMPEG_EXE':str(self.binary)},clear=True), \
             mock.patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):
            prepared=prepare(self.source,self.root/'offline prepare')
            raw={'ResultDetail':[{'StartMs':0,'EndMs':1000,'FinalSentence':'医学采访。',
                'Words':[{'Word':'医学采访。','OffsetStartMs':0,'OffsetEndMs':1000}]}]}
            result=export_transcript(raw,'tencent',self.root/'offline export',metadata=prepared)
            srt=Path(result['raw_srt'])
            text=srt.read_text(encoding='utf-8').replace('医学采访','校对文字')
            srt.write_bytes(('\ufeff'+text.replace('\n','\r\n')).encode('utf-8'))
            before=srt.read_bytes()
            output=self.root/'中文 成片.mp4'
            try:
                rendered=render(self.source,srt,output,preset='fast')
            except RuntimeError:
                print(output.with_suffix('.render.log').read_text(encoding='utf-8',errors='replace')[-5000:])
                raise
            self.assertEqual(rendered['encoding']['mode'],'source-bitrate')
            self.assertEqual(rendered['encoding']['passes'],2)
            self.assertEqual(srt.read_bytes(),before)
            self.assertEqual(rendered['probe']['width'],320)
            with self.assertRaises(FileExistsError): render(self.source,srt,output)
            with self.assertRaises(FileExistsError): render(self.source,srt,self.source)
        with mock.patch.dict(os.environ,{'IMAGEIO_FFMPEG_EXE':'missing-relative.exe'}):
            with self.assertRaises(ValueError): prepare(self.source,self.root/'invalid ffmpeg')
        self.assertFalse((self.root/'invalid ffmpeg/prepare.json').exists())

    def test_completed_legacy_flac_task_resumes_without_network(self):
        out=self.root/'legacy';(out/'provider').mkdir(parents=True)
        audio=out/'audio.flac'
        subprocess.run([str(self.binary),'-nostdin','-hide_banner','-n','-i',str(self.source),
            '-map','0:a:0','-ac','1','-ar','16000','-af','asetpts=PTS-STARTPTS',str(audio)],
            capture_output=True,check=True)
        metadata=probe(self.source)
        metadata['source_sha256']=_sha256(self.source)
        (out/'media.json').write_text(json.dumps(metadata),encoding='utf-8')
        state=dict(status='SUCCEEDED',task_id=123,identity=dict(provider='tencent',model='16k_zh_en_2.0',
            audio_sha256=_sha256(audio),vocabulary=None,filter_modal=0))
        (out/'provider/job.json').write_text(json.dumps(state),encoding='utf-8')
        raw={'ResultDetail':[{'StartMs':0,'EndMs':1000,'FinalSentence':'医学采访。',
            'Words':[{'Word':'医学采访。','OffsetStartMs':0,'OffsetEndMs':1000}]}]}
        (out/'provider/transcription-0.json').write_text(json.dumps(raw),encoding='utf-8')
        with mock.patch.dict(os.environ,{},clear=True),mock.patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):
            result=transcribe(self.source,out,use_medical_vocabulary=False)
        self.assertEqual(result['status'],'SUCCEEDED')
        self.assertFalse((out/'audio.mp3').exists())
        self.assertEqual(json.loads((out/'provider/job.json').read_text()),state)
