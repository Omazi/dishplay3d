import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from worker.frame_selection.models import SelectionConfig, SelectionError
from worker.preprocess import process
from worker.tests.test_selection import texture


class FallbackTests(unittest.TestCase):
    def run_case(self, root, fallback, experiment="POSE_FULL__OBJECT_MASKED"):
        source=root/"rgb";source.mkdir()
        output=root/"result";output.mkdir();(output/"input").mkdir()
        frames=[]
        for i in range(8):
            name=f"{i:06d}.png";Image.fromarray(texture()).save(source/name)
            frames.append({"name":name,"frameIndex":i,"timestampMs":i*100,"width":320,"height":240})
        manifest={"sourceVideo":{"sha256":"test-source"},"sourceFrameCount":8,"durationMs":800,"timings":{}}
        config=SelectionConfig(method="TEMPORAL_BASELINE",final_count=8,minimum_count=4,
            segmentation="sam2.1",segmentation_fallback=fallback,experiment=experiment)
        with patch("worker.video.extract_video",return_value=(source,frames,manifest)),patch(
            "worker.segmentation.sam2.SAM21Segmenter.segment_video",side_effect=SelectionError("SEGMENTATION_LOW_CONFIDENCE","Ambiguous plate")):
            return process(root/"unused.mp4",output,{"disk_mib":256},config)

    def test_low_confidence_stops_and_retains_rgb_and_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with self.assertRaises(SelectionError): self.run_case(root,"fail")
            report=json.loads((root/"result"/"capture_report.json").read_text())
            self.assertEqual(report["failure"]["code"],"SEGMENTATION_LOW_CONFIDENCE")
            self.assertEqual(len(list((root/"rgb").glob("*.png"))),8)

    def test_only_explicit_fallback_continues_without_masks(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.run_case(root,"no-mask")
            report=json.loads((root/"result"/"capture_report.json").read_text())
            self.assertEqual(report["segmentation"]["fallback"],"EXPLICIT_NO_MASK_BASELINE")
            self.assertFalse(report["segmentation"]["enabled"])
            self.assertFalse(report["maskApplication"]["denseMasksApplied"])

    def test_masked_pose_experiment_never_silently_runs_without_masks(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with self.assertRaises(SelectionError): self.run_case(root,"no-mask","POSE_MASKED__OBJECT_MASKED")
            report=json.loads((root/"result"/"capture_report.json").read_text())
            self.assertEqual(report["failure"]["code"],"SEGMENTATION_FAILED")
