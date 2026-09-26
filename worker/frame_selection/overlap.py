"""ORB + ratio-filtered mutual matches + deterministic RANSAC, at bounded resolution."""
import cv2
import numpy as np


def features(gray, config, mask=None):
    cv2.setNumThreads(1)
    points, descriptors = cv2.ORB_create(nfeatures=config.max_features).detectAndCompute(gray, mask)
    return {"points": np.array([p.pt for p in points], dtype=np.float32).reshape(-1, 2),
            "descriptors": descriptors, "diagonal": float(np.hypot(*gray.shape))}


def estimate(a, b, config):
    result = {"featureCountA": len(a["points"]), "featureCountB": len(b["points"]), "matches": 0,
              "inliers": 0, "inlierRatio": 0.0, "overlap": 0.0, "medianDisplacement": 0.0,
              "homographyResidual": None, "model": None, "sufficient": False}
    if a["descriptors"] is None or b["descriptors"] is None or min(len(a["points"]), len(b["points"])) < 8:
        return result
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    def good(x, y):
        return {p.queryIdx: p.trainIdx for pair in matcher.knnMatch(x, y, k=2) if len(pair) == 2
                for p, q in [pair] if p.distance < config.match_ratio*q.distance}
    forward, reverse = good(a["descriptors"], b["descriptors"]), good(b["descriptors"], a["descriptors"])
    pairs = [(i, j) for i, j in sorted(forward.items()) if reverse.get(j) == i]
    result["matches"] = len(pairs)
    if len(pairs) < 8:
        return result
    left = np.array([a["points"][i] for i, _ in pairs])
    right = np.array([b["points"][j] for _, j in pairs])
    cv2.setRNGSeed(0)
    _, fmask = cv2.findFundamentalMat(left, right, cv2.FM_RANSAC, config.ransac_pixels, 0.99)
    cv2.setRNGSeed(0)
    homography, hmask = cv2.findHomography(left, right, cv2.RANSAC, config.ransac_pixels)
    # Planar dishes/tables can be degenerate for F; H is a valid overlap check, not proof of 3D parallax.
    alternatives = [(name, mask.reshape(-1).astype(bool)) for name, mask in [("fundamental", fmask), ("homography", hmask)]
                    if mask is not None and mask.size == len(pairs)]
    if not alternatives:
        return result
    name, inliers = max(alternatives, key=lambda item: int(item[1].sum()))
    count = int(inliers.sum())
    if count:
        result["medianDisplacement"] = float(np.median(np.linalg.norm(left[inliers]-right[inliers], axis=1))/a["diagonal"])
        if homography is not None:
            predicted = cv2.perspectiveTransform(left.reshape(-1, 1, 2), homography).reshape(-1, 2)
            result["homographyResidual"] = float(np.median(np.linalg.norm(predicted[inliers]-right[inliers], axis=1))/a["diagonal"])
    ratio = count/len(pairs)
    result.update(inliers=count, inlierRatio=ratio, overlap=count/max(1, min(len(a["points"]), len(b["points"]))), model=name,
                  sufficient=count >= config.min_inliers and ratio >= config.min_inlier_ratio)
    return result
