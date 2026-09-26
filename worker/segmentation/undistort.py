"""Carry binary masks into the actual undistorted COLMAP camera coordinates."""
from pathlib import Path
import argparse
import json
import numpy as np
from PIL import Image
import cv2
from ..colmap_artifacts import cameras, images


def warp(mask, source, target):
    if source["model"]!=2 or target["model"]!=1:
        raise ValueError("Mask warp requires legacy SIMPLE_RADIAL -> PINHOLE cameras")
    if mask.shape!=(source["height"],source["width"]):
        raise ValueError("Mask and calibrated camera dimensions differ")
    f,cx,cy,k=source["params"]
    fx,fy,tx,ty=target["params"]
    if not np.isfinite([f,cx,cy,k,fx,fy,tx,ty]).all() or min(f,fx,fy)<=0:
        raise ValueError("Invalid mask calibration")
    width,height=target["width"],target["height"]
    if not 0<width<=4096 or not 0<height<=4096:
        raise ValueError("Mask dimensions exceed budget")
    y,x=np.indices((height,width),dtype=np.float32)
    # COLMAP camera coordinates use pixel centers at +0.5; OpenCV remap uses integer centers.
    x=(x+.5-tx)/fx;y=(y+.5-ty)/fy
    radial=1+k*(x*x+y*y)
    return cv2.remap(mask,(f*x*radial+cx-.5).astype(np.float32),(f*y*radial+cy-.5).astype(np.float32),
                     cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT,borderValue=0)


def prepare(output):
    old_cameras=cameras(output/"sparse"/"0"/"cameras.bin")
    new_cameras=cameras(output/"dense"/"sparse"/"cameras.bin")
    old_images=images(output/"sparse"/"0"/"images.bin")
    new_images=images(output/"dense"/"sparse"/"images.bin")
    destination=output/"masks"/"undistorted"
    destination.mkdir()
    mapping=[]
    for iid,image in new_images.items():
        name=image["name"]
        if Path(name).name!=name or old_images[iid]["name"]!=name:
            raise ValueError("Unexpected image name/mapping")
        with Image.open(output/"masks"/"colmap"/(name+".png")) as image_mask:
            mask=np.array(image_mask.convert("L"))
        target=new_cameras[image["cameraId"]]
        warped=warp(mask,old_cameras[old_images[iid]["cameraId"]],target)
        with Image.open(output/"dense"/"images"/name) as rgb:
            if rgb.size!=(target["width"],target["height"]): raise ValueError("Undistorted RGB dimensions mismatch")
        # OpenMVS Util::getFileName removes the original extension.
        mask_name=Path(name).stem+".mask.png"
        Image.fromarray(warped).save(destination/mask_name)
        mapping.append({"image":name,"mask":mask_name,"width":target["width"],"height":target["height"]})
    (destination/"mapping.json").write_text(json.dumps({"maskBackgroundLabel":0,"foregroundLabel":255,
        "coordinates":"COLMAP dense undistorted cameras","images":mapping},indent=2))
    return mapping


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("output",type=Path)
    prepare(parser.parse_args().output)
