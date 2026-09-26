"""Complementary blur proxies, not a calibrated motion-blur probability."""
import cv2
import numpy as np


def measure(gray):
    pixels = gray.astype(np.float32)
    dx = cv2.Sobel(pixels, cv2.CV_32F, 1, 0)
    dy = cv2.Sobel(pixels, cv2.CV_32F, 0, 1)
    tensor = np.array([[np.mean(dx*dx), np.mean(dx*dy)], [np.mean(dx*dy), np.mean(dy*dy)]])
    eigen = np.linalg.eigvalsh(tensor)
    ratio = float((eigen[1]+1)/(eigen[0]+1))
    spectrum = cv2.dct(cv2.resize(pixels, (64, 64))) ** 2
    spectrum[0, 0] = 0
    yy, xx = np.indices((64, 64))
    high = float(spectrum[(xx+yy) >= 32].sum() / max(float(spectrum.sum()), 1e-8))
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    gradient = float(np.sqrt(dx*dx+dy*dy).mean())
    return {"sharpness": sharpness, "gradientEnergy": gradient,
            "highFrequencyRatio": high, "directionalGradientRatio": ratio,
            "motionBlur": {"method": "directional-gradient-and-frequency-proxy", "directionalRatio": ratio,
                           "highFrequencyRatio": high, "calibratedProbability": False}}
