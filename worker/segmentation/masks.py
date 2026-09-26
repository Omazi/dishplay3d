import numpy as np


def measure(mask, previous=None):
    mask = np.asarray(mask, dtype=bool)
    if mask.ndim != 2:
        raise ValueError("Mask must be H x W")
    y, x = np.nonzero(mask)
    height, width = mask.shape
    border_count = int(mask[0].sum()+mask[-1].sum()+mask[1:-1, 0].sum()+mask[1:-1, -1].sum())
    union = np.logical_or(mask, previous).sum() if previous is not None else 0
    return {"maskAreaRatio": float(mask.mean()),
            "objectBoundingBox": [int(x.min()), int(y.min()), int(x.max()+1), int(y.max()+1)] if len(x) else None,
            "objectCenter": [float(x.mean()/width), float(y.mean()/height)] if len(x) else None,
            "touchesImageBorder": bool(border_count), "borderContactFraction": border_count/max(1, 2*height+2*width-4),
            "temporalMaskConsistency": float(np.logical_and(mask, previous).sum()/union) if union else None}


def rank_automatic(candidates, config):
    """Semantic heuristic, not a food classifier. Ambiguous plate/table proposals must fail closed."""
    ranked = []
    for candidate in candidates:
        metrics = measure(candidate["segmentation"])
        area, center, box = metrics["maskAreaRatio"], metrics["objectCenter"], metrics["objectBoundingBox"]
        if not center or not config.min_mask_area <= area <= config.max_mask_area:
            continue
        centered = max(0, 1-np.hypot(center[0]-config.auto_center_x, center[1]-config.auto_center_y)/config.auto_center_radius)
        aspect = (box[2]-box[0])/max(1, box[3]-box[1])
        placement = min(aspect, 1/aspect)  # plate viewed obliquely is allowed; extreme strips are discouraged
        model = min(float(candidate.get("stability_score", 0)), float(candidate.get("predicted_iou", 0)))
        score = float(model*centered*(config.auto_placement_base+config.auto_placement_weight*placement)*(1-min(1, config.auto_border_penalty*metrics["borderContactFraction"])))
        ranked.append((score, candidate, metrics))
    ranked.sort(key=lambda entry: -entry[0])
    return ranked
