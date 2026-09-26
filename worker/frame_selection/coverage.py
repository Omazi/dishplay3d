"""Pose engineering coverage or explicitly weak sequence proxy; no invented camera poses."""
import math
import numpy as np


def direction(metadata, config):
    if (not metadata or metadata.get("trackingState") != "normal"
            or metadata.get("poseConvention") != "camera-to-world-row-major"
            or not isinstance(metadata.get("poseReference"),str) or not metadata["poseReference"]
            or metadata.get("poseSelectionRejectedCode")):
        return None
    try:
        pose = np.asarray(metadata["cameraTransform"], dtype=float)
        center = np.asarray(metadata["objectCenterWorld"], dtype=float)
        if pose.shape != (4, 4) or center.shape != (3,) or not np.isfinite(pose).all() or not np.isfinite(center).all():
            return None
        rotation = pose[:3, :3]
        if not np.allclose(rotation.T@rotation, np.eye(3), atol=0.05) or abs(np.linalg.det(rotation)-1) > 0.05:
            return None
        if not np.allclose(pose[3], [0, 0, 0, 1]) or metadata.get("worldUp") != "+Y":
            return None
        offset = pose[:3, 3]-center
        distance = np.linalg.norm(offset)
        if distance < config.min_pose_distance_m or distance > config.max_pose_distance_m:
            return None
        azimuth = math.degrees(math.atan2(offset[0], offset[2])) % 360
        elevation = math.degrees(math.asin(float(offset[1]/distance)))
        return {"azimuth": azimuth, "elevation": elevation,
                "azimuthBin": min(config.azimuth_bins-1, int(azimuth/(360/config.azimuth_bins))),
                "elevationBin": "low" if elevation < 20 else "medium" if elevation < 55 else "high"}
    except (KeyError, TypeError, ValueError):
        return None


def report(selected, pairs, config):
    directions = [direction(frame.get("metadata"), config) for frame in selected]
    trusted = [value for value in directions if value]
    connected = bool(pairs) and all(pair["sufficient"] for pair in pairs)
    diverse = sum(pair["medianDisplacement"] >= config.min_novel_displacement for pair in pairs)
    reasons = []
    if len(selected) < config.minimum_count:
        reasons.append("INSUFFICIENT_SHARP_FRAMES")
    if not connected:
        reasons.append("INSUFFICIENT_OVERLAP")
    if diverse < max(2, config.minimum_count//2):
        reasons.append("INSUFFICIENT_VIEWPOINT_DIVERSITY")
    if len(trusted) == len(selected) and trusted:
        azimuth = sorted({value["azimuthBin"] for value in trusted})
        elevation = sorted({value["elevationBin"] for value in trusted})
        if len(azimuth) < config.required_azimuth_bins:
            reasons.append("CAPTURE_COVERAGE_INSUFFICIENT")
        if "high" not in elevation:
            reasons.append("LOW_TOP_COVERAGE")
        return {"method": "validated-supplied-pose-around-supplied-object-center", "confidence": "medium",
                "azimuthCoverage": azimuth, "azimuthBinCount": config.azimuth_bins,
                "elevationCoverage": elevation, "directions": trusted, "captureSufficient": not reasons,
                "reasons": reasons, "metricIsPhysicalGroundTruth": False}
    reasons.append("ANGULAR_COVERAGE_UNKNOWN")
    return {"method": "ordered-geometric-matching-proxy", "confidence": "low", "azimuthCoverage": None,
            "elevationCoverage": None, "trustedPoseCount": len(trusted), "diverseAdjacentPairs": diverse,
            "captureSufficient": False, "reasons": reasons,
            "recommendation": "Angular coverage cannot be certified without tracked poses and an object center; inspect contact sheets."}
