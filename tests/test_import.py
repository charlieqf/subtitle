import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from subtitle_tool import export_transcript


class ImportTests(TestCase):
    def test_raw_envelopes_offset_once_and_no_mutation(self):
        raw={'Status':2,'ResultDetail':[{'StartMs':1000,'EndMs':2000,'FinalSentence':'嗯，药物。',
            'Words':[{'Word':'嗯，','OffsetStartMs':0,'OffsetEndMs':200},
                     {'Word':'药物。','OffsetStartMs':200,'OffsetEndMs':1000}]}]}
        metadata={'audio_offset_ms':2000,'asr_time_offset_ms':2000,'duration_ms':10000}
        before=copy.deepcopy((raw,metadata))
        with TemporaryDirectory() as directory:
            paths=[]
            for index,wrapped in enumerate([raw,{'Data':raw},{'Response':{'Data':raw}}]):
                result=export_transcript(wrapped,'tencent',Path(directory)/str(index),metadata=metadata)
                data=json.loads(Path(result['json']).read_text(encoding='utf-8'))
                self.assertEqual(data['provider_segments'][0]['start_ms'],1000)
                self.assertEqual(data['source_segments'][0]['start_ms'],3000)
                self.assertEqual(data['source_segments'][0]['words'][1]['start_ms'],3200)
                self.assertEqual(data['captions'][0]['text'],'嗯，药物。')
                self.assertEqual(result['removed_fillers'],0)
                paths.append(Path(result['raw_srt']).read_bytes())
            self.assertEqual(paths[0],paths[1])
            self.assertEqual(paths[0],paths[2])
            self.assertEqual((raw,metadata),before)
            with self.assertRaises(ValueError):
                export_transcript(data,'tencent',Path(directory)/'again',metadata=metadata)

    def test_pending_or_wrong_provider_rejected(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                export_transcript({'Status':1,'ResultDetail':[]},'tencent',directory)
            with self.assertRaises(ValueError):
                export_transcript({},'unknown',directory)
