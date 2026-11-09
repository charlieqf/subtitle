from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest import TestCase,mock
import hashlib
import json
from subtitle_tool import api,providers

class JobSafetyTests(TestCase):
    def args(self,directory):
        audio=Path(directory)/'audio.flac'
        audio.write_bytes(b'test-fixture-no-network')
        return SimpleNamespace(output=Path(directory)/'job',name='test',audio=audio,provider='tencent',
            model='16k_zh_en_2.0',vocabulary=None,filter_modal=0,wait_seconds=0,progress=None)

    def test_tencent_does_not_require_aliyun_credentials(self):
        with TemporaryDirectory() as directory:
            args=self.args(directory)
            with mock.patch.dict('os.environ',{},clear=True),mock.patch.object(providers,'tencent_client'), \
                 mock.patch.object(providers,'tencent_call',return_value={'Data':{'TaskId':123}}) as call:
                providers.run(args)
                self.assertEqual(call.call_count,1)
                state=json.loads((args.output/'job.json').read_text())
                self.assertEqual(state['task_id'],123)

    def test_unknown_submission_never_resubmits(self):
        with TemporaryDirectory() as directory:
            args=self.args(directory)
            args.output.mkdir()
            state=dict(status='SUBMITTING',identity=dict(provider=args.provider,model=args.model,
                audio_sha256=hashlib.sha256(args.audio.read_bytes()).hexdigest(),vocabulary=None,filter_modal=0))
            (args.output/'job.json').write_text(json.dumps(state))
            with mock.patch.object(providers,'tencent_client') as client:
                with self.assertRaises(RuntimeError): providers.run(args)
                client.assert_not_called()

    def test_same_directory_is_locked_before_transcription(self):
        from filelock import Timeout
        with TemporaryDirectory() as directory:
            with api._task_lock(directory),mock.patch.object(api,'_transcribe') as transcribe:
                with self.assertRaises(Timeout): api.transcribe('unused.mp4',directory)
                transcribe.assert_not_called()

    def test_secret_redaction_with_environment_only(self):
        with mock.patch.dict('os.environ',{'DASHSCOPE_API_KEY':'fake-test-key-123'}):
            self.assertNotIn('fake-test-key-123',providers.clean('error fake-test-key-123'))
