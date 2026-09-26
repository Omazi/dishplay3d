import contextlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
from worker.segmentation.undistort import warp
from worker.segmentation.sam2 import SAM21Segmenter
from worker.frame_selection.models import SelectionConfig
from worker.colmap_artifacts import sparse_metrics


class GeometryTests(unittest.TestCase):
    def test_identity_and_scaled_mask_use_pixel_centers(self):
        mask=np.zeros((100,120),np.uint8);mask[20:80,30:90]=255
        source={"model":2,"width":120,"height":100,"params":[100,60,50,0]}
        target={"model":1,"width":120,"height":100,"params":[100,100,60,50]}
        np.testing.assert_array_equal(warp(mask,source,target),mask)
        scaled={"model":1,"width":60,"height":50,"params":[50,50,30,25]}
        result=warp(mask,source,scaled)
        self.assertEqual(result.shape,(50,60))
        self.assertTrue((result[10:40,15:45]==255).all())
        self.assertEqual(int((result>0).sum()),900)

    def test_unsupported_model_fails_instead_of_misaligning(self):
        with self.assertRaises(ValueError): warp(np.zeros((2,2)),{"model":7},{"model":1})

    def test_sparse_metrics_from_binary_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/"images.bin").write_bytes(struct.pack("<Q",1)+struct.pack("<i7di",1,1,0,0,0,0,0,0,1)+b"0000.jpg\x00"+struct.pack("<Q",0))
            (root/"points3D.bin").write_bytes(struct.pack("<Q",1)+struct.pack("<QdddBBBdQ",12,0,0,0,255,0,0,.75,0))
            self.assertEqual(sparse_metrics(root),{"registeredImages":1,"sparsePoints":1,"meanReprojectionErrorPixels":.75})

    def test_adapter_propagates_overlapping_windows_and_preserves_mapping(self):
        class Predictor:
            prompts=0
            def init_state(self,video_path,**kwargs): return len(list(Path(video_path).glob("*.jpg")))
            def add_new_points_or_box(self,*args,**kwargs): self.prompts+=1
            def add_new_mask(self,*args,**kwargs): self.prompts+=1
            def propagate_in_video(self,count):
                for i in range(count):
                    logits=np.full((1,1,12,16),-1.0);logits[:,:,3:10,4:12]=1
                    yield i,[1],logits
        fake_torch=types.SimpleNamespace(inference_mode=contextlib.nullcontext)
        with tempfile.TemporaryDirectory() as temp,patch.dict(sys.modules,{"torch":fake_torch}):
            root=Path(temp);paths=[]
            for i in range(6):
                p=root/f"{i*12:06d}.png";Image.new("RGB",(16,12)).save(p);paths.append(p)
            segmenter=SAM21Segmenter();segmenter.predictor=Predictor()
            config=SelectionConfig(segmentation="sam2.1",segmentation_init="box",sam_window=3)
            with patch.object(segmenter,"_load"):
                records=segmenter.segment_video(paths,root/"masks"/"candidates",config,
                    {"coordinateSpace":"decoded-pixels","box":[4,3,12,10]})
            self.assertEqual([r["position"] for r in records],list(range(6)))
            self.assertEqual([r["mask"] for r in records],[p.name for p in paths])
            self.assertEqual(segmenter.predictor.prompts,3)
            for record in records:
                with Image.open(root/"masks"/"candidates"/record["mask"]) as mask: self.assertEqual(mask.size,(16,12))
