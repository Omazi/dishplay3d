import cv2
from .blur import measure as blur
from .exposure import measure as exposure


def analyze(rgb, config, timestamp_ms):
    height, width = rgb.shape[:2]
    scale = min(1.0, config.analysis_edge / max(height, width))
    small = cv2.resize(rgb, (round(width*scale), round(height*scale)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    metrics = {**blur(gray), **exposure(gray), "resolution": [width, height], "timestampMs": timestamp_ms,
               "objectVisibility": None, "objectCrop": None, "visibilityStatus": "UNKNOWN_WITHOUT_MASK"}
    reasons = []
    if min(width, height) < config.min_short_edge:
        reasons.append("INSUFFICIENT_RESOLUTION")
    if metrics["sharpness"] < config.min_laplacian and metrics["gradientEnergy"] < config.min_gradient:
        reasons.append("BLURRED_FRAME")
    if metrics["directionalGradientRatio"] > config.max_directional_ratio and metrics["highFrequencyRatio"] < config.min_high_frequency:
        reasons.append("MOTION_BLUR")
    if (metrics["highlightClipping"] > config.max_white_fraction or metrics["shadowClipping"] > config.max_black_fraction
            or metrics["exposure"] < config.min_mean_luminance or metrics["exposure"] > config.max_mean_luminance):
        reasons.append("CATASTROPHIC_EXPOSURE")
    metrics["qualityScore"] = min(1.0, metrics["sharpness"]/max(config.min_laplacian*config.sharpness_saturation_multiple, 1)) * (1-max(metrics["highlightClipping"], metrics["shadowClipping"]))
    return gray, metrics, reasons
