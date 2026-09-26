from __future__ import annotations
from dataclasses import asdict, dataclass, fields
import math


class SelectionError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SelectionConfig:
    method: str = "SMART_SELECTION_V1"
    candidate_count: int = 150
    final_count: int = 32
    minimum_count: int = 8
    analysis_edge: int = 640
    min_short_edge: int = 200
    min_laplacian: float = 18.0
    min_gradient: float = 5.0
    sharpness_saturation_multiple: float = 8.0
    min_high_frequency: float = 0.025
    max_directional_ratio: float = 18.0
    max_white_fraction: float = 0.65
    max_black_fraction: float = 0.80
    min_mean_luminance: float = 12.0
    max_mean_luminance: float = 247.0
    phash_distance: int = 6
    duplicate_displacement: float = 0.004
    min_novel_displacement: float = 0.008
    ideal_displacement: float = 0.045
    min_inliers: int = 18
    min_inlier_ratio: float = 0.30
    max_features: int = 1200
    match_ratio: float = 0.75
    ransac_pixels: float = 2.5
    lookahead: int = 24
    beam_width: int = 2
    quality_weight: float = 1.0
    novelty_weight: float = 1.0
    coverage_weight: float = 0.7
    redundancy_weight: float = 0.8
    crop_weight: float = 1.0
    blur_weight: float = 0.5
    segmentation: str = "none"
    segmentation_fallback: str = "fail"
    segmentation_init: str = "auto"
    sam_checkpoint: str | None = None
    sam_config: str = "configs/sam2.1/sam2.1_hiera_t.yaml"
    sam_window: int = 8
    min_mask_confidence: float = 0.65
    min_auto_score_margin: float = 0.05
    auto_center_x: float = 0.5
    auto_center_y: float = 0.55
    auto_center_radius: float = 0.65
    auto_placement_base: float = 0.7
    auto_placement_weight: float = 0.3
    auto_border_penalty: float = 4.0
    min_mask_area: float = 0.03
    max_mask_area: float = 0.80
    max_border_fraction: float = 0.08
    min_mask_consistency: float = 0.35
    experiment: str = "POSE_FULL__OBJECT_MASKED"
    azimuth_bins: int = 8
    required_azimuth_bins: int = 6
    pose_max_gap_ms: float = 80.0
    max_pose_distance_m: float = 10.0
    min_pose_distance_m: float = 0.03

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            default = field.default
            if isinstance(default, (int, float)):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"Invalid numeric setting: {field.name}")
                if isinstance(default, int) and not isinstance(value, int):
                    raise ValueError(f"Integer required: {field.name}")
                if value < 0:
                    raise ValueError(f"Negative setting: {field.name}")
        if self.method not in ("SMART_SELECTION_V1", "TEMPORAL_BASELINE"):
            raise ValueError("Unknown selection method")
        if not 3 <= self.minimum_count <= self.final_count <= 80 or not self.final_count <= self.candidate_count <= 200:
            raise ValueError("Require 3 <= minimum <= final <= 80, final <= candidates <= 200")
        if not 128 <= self.analysis_edge <= 960 or not 1 <= self.lookahead <= 80:
            raise ValueError("Analysis edge/lookahead outside memory budget")
        if not 64 <= self.max_features <= 3000 or not 2 <= self.sam_window <= 12:
            raise ValueError("Feature/window budget exceeded")
        if self.segmentation not in ("none", "sam2.1") or self.segmentation_fallback not in ("fail", "no-mask"):
            raise ValueError("Invalid segmentation configuration")
        if self.segmentation_init not in ("auto", "point", "box"):
            raise ValueError("Invalid initialization mode")
        if self.experiment not in ("POSE_FULL__OBJECT_MASKED", "POSE_MASKED__OBJECT_MASKED"):
            raise ValueError("Invalid mask experiment")
        if not 1 <= self.beam_width <= 4 or self.auto_center_radius <= 0 or self.sharpness_saturation_multiple <= 0:
            raise ValueError("Invalid scoring/search configuration")
        if not 4 <= self.azimuth_bins <= 36 or not 1 <= self.required_azimuth_bins <= self.azimuth_bins:
            raise ValueError("Invalid coverage bins")
        for name in ("min_high_frequency", "max_white_fraction", "max_black_fraction", "match_ratio",
                     "min_inlier_ratio", "min_mask_confidence", "min_mask_area", "max_mask_area",
                     "max_border_fraction", "min_mask_consistency"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must be a fraction")
        if self.ideal_displacement <= 0 or self.ransac_pixels <= 0 or self.min_mask_area >= self.max_mask_area:
            raise ValueError("Invalid geometric/area thresholds")

    def document(self):
        return asdict(self)


def sample_indices(length, count):
    count = min(length, count)
    if count < 2:
        return list(range(count))
    return [i * (length - 1) // (count - 1) for i in range(count)]
