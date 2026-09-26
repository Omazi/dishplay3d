"""Synthetic tests prove contracts, not food reconstruction fidelity."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import cv2
import numpy as np
from PIL import Image
from worker.frame_selection.models import SelectionConfig, SelectionError, sample_indices
from worker.frame_selection import quality, similarity, overlap, coverage
from worker.frame_selection.selector import select
from worker.segmentation.masks import measure, rank_automatic
from worker.segmentation.sam2 import mapped_masks
from worker.preprocess import associate_metadata, process


def texture():
    random = np.random.default_rng(5)
    image = random.integers(30,220,(240,320,3),dtype=np.uint8)
    image = cv2.GaussianBlur(image,(3,3),0)
    for i in range(40):
        cv2.circle(image,(int(random.integers(15,305)),int(random.integers(15,225))),int(random.integers(3,9)),(40,120,210),-1)
    return image


def fixture_video(root):
    base = texture()
    for i in range(40):
        # A translated planar texture, deliberately NOT a real dish or a 3D benchmark.
        rgb = cv2.warpAffine(base,np.float32([[1,0,i*.65],[0,1,i*.2]]),(320,240),borderMode=cv2.BORDER_REFLECT)
        Image.fromarray(rgb).save(root/f"{i:04d}.png")
    path=root/"synthetic.mp4"
    subprocess.run(["ffmpeg","-v","error","-threads","1","-framerate","10","-i",str(root/"%04d.png"),
                    "-c:v","libx264","-threads","1","-pix_fmt","yuv420p",str(path)],check=True)
    return path


class QualityTests(unittest.TestCase):
    def setUp(self): self.config=SelectionConfig()

    def test_blur_rejected_by_complementary_metrics(self):
        clear=texture()
        blurred=cv2.GaussianBlur(clear,(71,71),25)
        _,a,ra=quality.analyze(clear,self.config,0)
        _,b,rb=quality.analyze(blurred,self.config,0)
        self.assertNotIn("BLURRED_FRAME",ra)
        self.assertIn("BLURRED_FRAME",rb)
        self.assertGreater(a["highFrequencyRatio"],b["highFrequencyRatio"])

    def test_catastrophic_exposure_but_not_small_highlights(self):
        rgb=texture();rgb[20:30,20:30]=255
        self.assertNotIn("CATASTROPHIC_EXPOSURE",quality.analyze(rgb,self.config,0)[2])
        self.assertIn("CATASTROPHIC_EXPOSURE",quality.analyze(np.full_like(rgb,255),self.config,0)[2])

    def test_similarity_detects_near_duplicate(self):
        gray=cv2.cvtColor(texture(),cv2.COLOR_RGB2GRAY)
        modified=np.clip(gray.astype(int)+2,0,255).astype(np.uint8)
        metrics=similarity.compare(similarity.fingerprint(gray),similarity.fingerprint(modified))
        self.assertFalse(metrics["exactPixels"])
        self.assertLessEqual(metrics["phashDistance"],2)

    def test_geometric_overlap_and_disjoint_images(self):
        gray=cv2.cvtColor(texture(),cv2.COLOR_RGB2GRAY)
        moved=cv2.warpAffine(gray,np.float32([[1,0,8],[0,1,3]]),(320,240))
        a,b=overlap.features(gray,self.config),overlap.features(moved,self.config)
        result=overlap.estimate(a,b,self.config)
        self.assertTrue(result["sufficient"])
        self.assertGreater(result["medianDisplacement"],.01)
        self.assertEqual(result,overlap.estimate(a,b,self.config))
        empty=overlap.features(np.zeros_like(gray),self.config)
        self.assertFalse(overlap.estimate(a,empty,self.config)["sufficient"])

    def test_all_config_budgets(self):
        for values in [{"final_count":81},{"candidate_count":201},{"sam_window":1},{"min_inliers":float("nan")},{"final_count":3.1}]:
            with self.assertRaises(ValueError): SelectionConfig(**values)
        for count in [24,32,48,64]:
            values=sample_indices(600,count)
            self.assertEqual(len(values),count)
            self.assertEqual(values,sorted(set(values)))


class MaskTests(unittest.TestCase):
    def test_border_and_dimensions(self):
        mask=np.zeros((100,120),bool);mask[:60,20:90]=True
        metrics=measure(mask)
        self.assertTrue(metrics["touchesImageBorder"])
        self.assertEqual(metrics["objectBoundingBox"],[20,0,90,60])
        self.assertEqual(measure(mask,mask)["temporalMaskConsistency"],1)

    def test_mapping_uses_source_indices_not_positions(self):
        outputs=[(i,[1],np.ones((1,1,10,12))) for i in range(3)]
        result=list(mapped_masks(outputs,[0,42,95],[(10,12)]*3))
        self.assertEqual([r[1] for r in result],[0,42,95])
        self.assertEqual(result[0][2].shape,(10,12))

    def test_wrong_mask_shape_or_omitted_frame_fails(self):
        for outputs in [[(0,[1],np.ones((1,1,5,5)))],[]]:
            with self.assertRaises(SelectionError): list(mapped_masks(outputs,[42],[(10,12)]))

    def test_auto_does_not_choose_largest_table(self):
        table=np.ones((100,100),bool)
        plate=np.zeros((100,100),bool);plate[25:80,25:75]=True
        candidates=[{"segmentation":m,"predicted_iou":.98,"stability_score":.98} for m in [table,plate]]
        ranked=rank_automatic(candidates,SelectionConfig())
        self.assertEqual(len(ranked),1)
        np.testing.assert_array_equal(ranked[0][1]["segmentation"],plate)


class SelectorTests(unittest.TestCase):
    def records(self):
        return [{"frameIndex":i*20,"timestampMs":i*600,"pixelSha256":str(i),"metrics":{
            "qualityScore":.8,"highFrequencyRatio":.1,"objectCrop":None},"reasons":[]} for i in range(14)]

    def pair(self,a,b):
        gap=b-a
        return {"sufficient":gap<=3,"medianDisplacement":gap*.015,"phashDistance":15,"overlap":.4}

    def test_deterministic_order_and_continuity(self):
        config=SelectionConfig(final_count=8,minimum_count=5)
        a,_=select(self.records(),self.pair,config)
        b,_=select(self.records(),self.pair,config)
        self.assertEqual(a,b)
        self.assertEqual(a,sorted(set(a)))
        self.assertTrue(all(self.pair(x,y)["sufficient"] for x,y in zip(a,a[1:])))
        self.assertEqual(len(a),8)

    def test_exact_duplicates_rejected(self):
        records=self.records();records[5]["pixelSha256"]=records[4]["pixelSha256"]
        selected,_=select(records,self.pair,SelectionConfig(final_count=8,minimum_count=5))
        self.assertNotIn(5,selected)
        self.assertIn("EXACT_DUPLICATE",records[5]["reasons"])

    def test_similarity_alone_does_not_discard_parallax(self):
        def close(a,b): return {**self.pair(a,b),"phashDistance":1}
        selected,_=select(self.records(),close,SelectionConfig(final_count=8,minimum_count=5))
        self.assertEqual(len(selected),8)

    def test_disconnected_frames_do_not_form_false_chain(self):
        def disconnected(a,b): return {**self.pair(a,b),"sufficient":False}
        selected,decision=select(self.records(),disconnected,SelectionConfig())
        self.assertEqual(selected,[])
        self.assertEqual(decision["failure"],"INSUFFICIENT_OVERLAP")

    def test_baseline_keeps_exact_quantiles_even_if_bad(self):
        records=self.records()
        for i,r in enumerate(records):
            r["temporalBaseline"]=i in [0,6,13];r["reasons"]=["BLURRED_FRAME"]
        selected,_=select(records,self.pair,SelectionConfig(method="TEMPORAL_BASELINE"))
        self.assertEqual(selected,[0,6,13])

    def test_late_loop_not_discarded_as_duplicate(self):
        records=self.records();records[-1]["pixelSha256"]=records[0]["pixelSha256"]
        def pair(a,b): return {**self.pair(a,b),"sufficient":b-a<=3 or (a==0 and b==13),"phashDistance":0 if a==0 and b==13 else 20}
        selected,decision=select(records,pair,SelectionConfig(final_count=8,minimum_count=5))
        self.assertIn(13,selected)
        self.assertNotIn("EXACT_DUPLICATE",records[-1]["reasons"])

    def test_metadata_matching_does_not_mutate_capture(self):
        capture={"captureMetadata":{"videoFrames":[{"frameIndex":20,"timestampMs":600,"metadata":{"trackingState":"normal"}}]}}
        before=copy.deepcopy(capture);frames=self.records()
        associate_metadata(frames,capture,SelectionConfig())
        self.assertEqual(capture,before)
        self.assertEqual(frames[1]["metadata"]["trackingState"],"normal")
        self.assertIsNone(coverage.direction(frames[1]["metadata"],SelectionConfig()))

    def test_trusted_pose_vs_unknown_coverage(self):
        pose=np.eye(4);pose[:3,3]=[1,1,0]
        meta={"trackingState":"normal","poseReference":"test-session","poseConvention":"camera-to-world-row-major","worldUp":"+Y",
              "cameraTransform":pose.tolist(),"objectCenterWorld":[0,0,0]}
        self.assertEqual(coverage.direction(meta,SelectionConfig())["azimuthBin"],2)
        meta["trackingState"]="limited"
        self.assertIsNone(coverage.direction(meta,SelectionConfig()))
        report=coverage.report(self.records(),[self.pair(0,1)],SelectionConfig())
        self.assertEqual(report["confidence"],"low")
        self.assertIsNone(report["azimuthCoverage"])
        self.assertFalse(report["captureSufficient"])


    def test_pose_reference_change_disables_coverage_without_mutating_manifest(self):
        capture={"captureMetadata":{"videoFrames":[{"frameIndex":i*20,"timestampMs":i*600,
            "metadata":{"poseReference":str(i),"trackingState":"normal"}} for i in range(2)]}}
        before=copy.deepcopy(capture);frames=self.records()
        associate_metadata(frames,capture,SelectionConfig())
        self.assertEqual(capture,before)
        self.assertEqual(frames[0]["metadata"]["poseSelectionRejectedCode"],"POSE_REFERENCE_CHANGED")


@unittest.skipUnless(shutil.which("ffmpeg"),"FFmpeg fixture requires local executable")
class VideoIntegration(unittest.TestCase):
    def test_tiny_actual_mp4_both_paths_with_reports_and_immutable_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);video=fixture_video(root)
            original=hashlib.sha256(video.read_bytes()).hexdigest()
            capture={"manifest":{"schema":2,"sourceType":"video","video":{"sha256":original}},"captureMetadata":{}}
            capture_before=json.dumps(capture,sort_keys=True)
            settings={"max_images":8,"long_edge":320,"memory_mib":512,"stage_seconds":60,"disk_mib":256}
            for method in ["TEMPORAL_BASELINE","SMART_SELECTION_V1"]:
                output=root/method;output.mkdir()
                config=SelectionConfig(method=method,candidate_count=18,final_count=8,minimum_count=4)
                frames,manifest=process(video,output,settings,config,capture=capture,expected_sha=original)
                self.assertEqual(json.dumps(capture,sort_keys=True),capture_before)
                report=json.loads((output/"capture_report.json").read_text())
                indexes=[f["frameIndex"] for f in frames]
                self.assertEqual(indexes,sorted(set(indexes)))
                self.assertEqual(len(indexes),8)
                if method=="TEMPORAL_BASELINE": self.assertEqual(indexes,sample_indices(40,8))
                self.assertEqual(hashlib.sha256(video.read_bytes()).hexdigest(),original)
                self.assertGreater(report["source"]["candidateFrameCount"],8)
                self.assertTrue((output/"contact_sheet_selected.jpg").exists())
                self.assertTrue((output/"input"/"source.video").exists())
                self.assertFalse(report["qualityImprovementProven"])


if __name__=="__main__": unittest.main()
