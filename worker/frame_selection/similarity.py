import hashlib
import cv2
import numpy as np


def fingerprint(gray):
    dct = cv2.dct(cv2.resize(gray, (32, 32)).astype(np.float32))[:8, :8].flatten()[1:]
    return {"phash": (dct > np.median(dct)).astype(np.uint8),
            "pixelSha256": hashlib.sha256(gray.tobytes()).hexdigest()}


def compare(a, b):
    return {"phashDistance": int(np.count_nonzero(a["phash"] != b["phash"])),
            "exactPixels": a["pixelSha256"] == b["pixelSha256"]}
