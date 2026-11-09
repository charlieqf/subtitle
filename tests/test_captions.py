import unittest
from subtitle_tool.captions import normalize_tencent,build_captions,parse_srt,to_srt,validate

class TimingTests(unittest.TestCase):
    def test_tencent_offsets_are_relative_to_sentence(self):
        segments=normalize_tencent({'ResultDetail':[{'StartMs':10000,'EndMs':11000,'FinalSentence':'药物。',
            'Words':[{'Word':'药物','OffsetStartMs':200,'OffsetEndMs':900},
                     {'Word':'。','OffsetStartMs':200,'OffsetEndMs':900}]}]})
        cues,_=build_captions(segments)
        self.assertEqual(cues[0]['start_ms'],10200)
        self.assertEqual(cues[0]['end_ms'],10900)
        self.assertEqual(cues[0]['text'],'药物。')

    def test_remove_filler_does_not_shift_medical_statement(self):
        segment={'start_ms':1000,'end_ms':4000,'text':'嗯，不是雌激素。','words':[
            {'text':'嗯','start_ms':1000,'end_ms':1500},{'text':'，','start_ms':1000,'end_ms':1500},
            {'text':'不是','start_ms':2500,'end_ms':3000},{'text':'雌激素。','start_ms':3000,'end_ms':4000}]}
        cues,edits=build_captions([segment])
        self.assertEqual(cues[0]['text'],'不是雌激素。')
        self.assertEqual(cues[0]['start_ms'],2500)
        self.assertEqual(cues[0]['end_ms'],4000)
        self.assertEqual(len(edits),1)

    def test_long_pause_is_not_covered(self):
        segments=[{'start_ms':0,'end_ms':5000,'text':'前后','words':[
            {'text':'前','start_ms':0,'end_ms':1000},{'text':'后','start_ms':4000,'end_ms':5000}]}]
        cues,_=build_captions(segments)
        self.assertEqual(len(cues),2)
        self.assertEqual(cues[0]['end_ms'],1000)
        self.assertEqual(cues[1]['start_ms'],4000)

    def test_srt_bom_crlf_multiline_roundtrip(self):
        source='\ufeff1\r\n01:02:03,004 --> 01:02:05,006\r\n医学采访\r\n校对文字\r\n'
        cues=parse_srt(source)
        self.assertEqual(cues[0]['start_ms'],3723004)
        self.assertEqual(parse_srt(to_srt(cues)),cues)

    def test_invalid_or_overlapping_srt_rejected(self):
        for source in ['','1\n00:00:02,000 --> 00:00:01,000\n错误',
            '1\n00:00:00,000 --> 00:00:02,000\n一\n\n2\n00:00:01,000 --> 00:00:03,000\n二']:
            with self.assertRaises(ValueError): parse_srt(source)

if __name__=='__main__': unittest.main()
