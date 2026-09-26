"""Real tiny FFmpeg fixtures validate ingestion, not dish reconstruction quality."""
import hashlib
import contextlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worker import reconstruct
from worker.video import VideoError, validate_container, validate_probe, temporal_indices, extract_video


@contextlib.contextmanager
def tiny_fixture_headroom():
    """Simulate scheduling admission only; preserve real pressure checks during tiny fixture decoding.

    These tests concern CLI/manifest contracts. Host desktop activity should not
    determine their result. A separate test verifies the real admission refusal.
    """
    checks = reconstruct.doctor()
    actual = reconstruct.memory_available
    first = True
    def available():
        nonlocal first
        if first:
            first = False
            return 4096*1024*1024
        return actual()
    with patch.object(reconstruct,'doctor',return_value=checks), patch.object(reconstruct,'memory_available',side_effect=available):
        yield


class VideoContracts(unittest.TestCase):
    def document(self, codec='h264'):
        return {'format':{'format_name':'mov,mp4','duration':'1'},
                'streams':[{'codec_type':'video','codec_name':codec,'width':320,'height':240,'avg_frame_rate':'30/1'}],
                'frames':[{'best_effort_timestamp_time':str(v)} for v in [0,0.031,0.079,0.12]]}

    def test_codec_and_dimensions_rejected(self):
        with self.assertRaises(VideoError) as context:
            validate_probe(self.document('av1'))
        self.assertEqual(context.exception.code,'VIDEO_UNSUPPORTED_CODEC')
        doc=self.document(); doc['streams'][0]['width']=100000
        with self.assertRaises(VideoError): validate_probe(doc)

    def test_vfr_timestamps_are_not_synthesized_from_fps(self):
        self.assertEqual(validate_probe(self.document())['timestampsMs'],[0,31,79,120])
        self.assertEqual(temporal_indices([0,31,79,120],3),[0,1,3])

    def test_missing_camera_calibration_is_explicit(self):
        self.assertEqual(validate_probe(self.document())['intrinsicsStatus'],'UNAVAILABLE')

    def test_bad_timestamp_and_duration_fail(self):
        for value in ['nan','200']:
            doc=self.document();doc['format']['duration']=value
            with self.assertRaises(VideoError):validate_probe(doc)
        doc=self.document();doc['frames'][1]['best_effort_timestamp_time']='-1'
        with self.assertRaises(VideoError):validate_probe(doc)

    def test_temporal_budget_and_order(self):
        for count in [24,32,40]:
            indexes=temporal_indices(list(range(600)),count)
            self.assertEqual(len(indexes),count)
            self.assertEqual(indexes,sorted(set(indexes)))
            self.assertEqual((indexes[0],indexes[-1]),(0,599))


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg is required for real decode fixtures')
class RealVideoIngest(unittest.TestCase):
    def setUp(self):
        try:
            import PIL
        except ImportError:
            self.skipTest('Pillow is required for real decoded image validation')
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        self.source=self.root/'scan.bin' # extension is deliberately not video
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
                        'testsrc2=size=320x240:rate=10:duration=1','-c:v','libx264','-threads','1',
                        '-pix_fmt','yuv420p','-f','mp4',str(self.source)],check=True,timeout=15)
        self.settings={'max_images':3,'long_edge':320,'memory_mib':512,'disk_mib':256,'stage_seconds':30}

    def extract(self, source=None, name='out', execute=None):
        output=self.root/name;output.mkdir()
        return extract_video(source or self.source,output,self.settings,execute or reconstruct.execute_stage)

    def test_actual_decode_is_deterministic_and_preserves_original(self):
        original=self.source.read_bytes()
        _,frames,manifest=self.extract()
        _,second,_=self.extract(name='second')
        self.assertEqual(frames,second)
        self.assertEqual([f['frameIndex'] for f in frames],[0,4,9])
        self.assertEqual([f['timestampMs'] for f in frames],[0,400,900])
        self.assertTrue(all(f['width']==320 and f['height']==240 for f in frames))
        self.assertEqual(manifest['sourceVideo']['sha256'],hashlib.sha256(original).hexdigest())
        self.assertEqual(self.source.read_bytes(),original)
        self.assertEqual((self.root/'out/input/source.video').read_bytes(),original)
        self.assertIn('binarySha256',manifest['tools']['ffmpeg'])

    def test_invalid_and_truncated_mp4(self):
        bad=self.root/'bad.mp4';bad.write_bytes(b'not a video')
        with self.assertRaises(VideoError):validate_container(bad)
        bad.write_bytes(self.source.read_bytes()[:-50])
        with self.assertRaises(VideoError):validate_container(bad)
        with self.assertRaises(VideoError):validate_container(self.source,'0'*64)

    def test_orientation_metadata_applied_and_preserved(self):
        rotated=self.root/'rotated.mp4'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(self.source),'-c','copy',
                        '-metadata:s:v:0','rotate=90',str(rotated)],check=True,timeout=15)
        _,frames,_=self.extract(rotated)
        self.assertEqual((frames[0]['width'],frames[0]['height']),(240,320))
        metadata=json.loads((self.root/'out/input/video_metadata.json').read_text())
        self.assertTrue(metadata['orientation'])

    def test_decode_failure_has_specific_code(self):
        def execute(stage,*args):
            if stage['name']=='video_decode':raise ValueError('decoder rejected bitstream')
            return reconstruct.execute_stage(stage,*args)
        with self.assertRaises(VideoError) as context:self.extract(execute=execute)
        self.assertEqual(context.exception.code,'VIDEO_DECODE_FAILED')

    def test_timeout_terminates_stage_and_has_specific_code(self):
        import sys
        output=self.root/'timeout';output.mkdir()
        with self.assertRaisesRegex(ValueError,'timeout'):
            reconstruct.execute_stage({'name':'sleep','command':[sys.executable,'-c','import time; time.sleep(10)']},output,{**self.settings,'stage_seconds':1})

    def test_invalid_video_persists_a_machine_readable_failure(self):
        bad=self.root/'invalid.mp4';bad.write_bytes(b'not a container')
        output=self.root/'invalid-output'
        with tiny_fixture_headroom(), patch('sys.argv',['worker','--video',str(bad),'--output',str(output),
                               '--prepare-video','--memory-mib','512']):
            self.assertEqual(reconstruct.main(),2)
        manifest=json.loads((output/'manifest.json').read_text())
        self.assertEqual(manifest['state'],'failed')
        self.assertEqual(manifest['error_code'],'VIDEO_INVALID')

    def test_prepare_only_cli_does_not_require_geometry_engines(self):
        with tiny_fixture_headroom(), patch('sys.argv',['worker','--video',str(self.source),'--output',str(self.root/'prepared'),
                               '--prepare-video','--max-images','3','--long-edge','320','--memory-mib','512']):
            self.assertEqual(reconstruct.main(),0)
        manifest=json.loads((self.root/'prepared/manifest.json').read_text())
        self.assertEqual(manifest['state'],'prepared_only')
        self.assertEqual(manifest['engine_id'],'legacy-photogrammetry-v1')
        self.assertFalse((self.root/'prepared/model.glb').exists())


    def test_insufficient_headroom_refuses_before_creating_output(self):
        output=self.root/'no-memory'
        with patch.object(reconstruct,'memory_available',return_value=0), patch('sys.argv',[
            'worker','--video',str(self.source),'--output',str(output),'--prepare-video','--memory-mib','512']):
            self.assertEqual(reconstruct.main(),2)
        self.assertFalse(output.exists())
