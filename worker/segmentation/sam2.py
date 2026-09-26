"""Official SAM 2.1 video predictor adapter, windowed to bound eager frame loading.

Windows overlap by one frame and carry its propagated mask. Temporal model memory
is reset at boundaries; this limitation is recorded, not disguised as full-video inference.
No checkpoint download or global dependency installation occurs here.
"""
from pathlib import Path
import importlib.metadata
import json
import shutil
import numpy as np
from PIL import Image
from .base import DishSegmenter
from .masks import measure, rank_automatic
from ..frame_selection.models import SelectionError
from ..video import sha256


def mapped_masks(outputs, frame_ids, dimensions):
    """Strict predictor-position -> source-frame mapping, independently testable."""
    seen = set()
    for position, ids, logits in outputs:
        if not 0 <= position < len(frame_ids) or position in seen or list(ids) != [1]:
            raise SelectionError("SEGMENTATION_FAILED", "Unexpected SAM frame/object mapping")
        values = logits.detach().cpu().numpy() if hasattr(logits, "detach") else np.asarray(logits)
        mask = values[0, 0] > 0
        if mask.shape != dimensions[position]:
            raise SelectionError("SEGMENTATION_FAILED", "SAM mask dimensions differ from RGB")
        seen.add(position)
        yield position, frame_ids[position], mask
    if seen != set(range(len(frame_ids))):
        raise SelectionError("SEGMENTATION_FAILED", "SAM propagation omitted frames")


class SAM21Segmenter(DishSegmenter):
    def __init__(self):
        self.predictor = None

    def _load(self, config):
        try:
            version = tuple(int(v) for v in importlib.metadata.version("torch").split("+")[0].split(".")[:2])
            if version < (2, 5):
                raise ImportError("SAM 2.1 requires a separate PyTorch >=2.5 environment")
            if not config.sam_checkpoint or not Path(config.sam_checkpoint).is_file():
                raise ImportError("Configure a local official SAM 2.1 checkpoint")
            if config.sam_config != "configs/sam2.1/sam2.1_hiera_t.yaml":
                raise ImportError("Only the tiny SAM 2.1 model is enabled under the laptop budget")
            import torch
            from sam2.build_sam import build_sam2_video_predictor
            torch.set_num_threads(1)
            self.predictor = build_sam2_video_predictor(config.sam_config, config.sam_checkpoint, device="cpu", apply_postprocessing=False)
        except (ImportError, importlib.metadata.PackageNotFoundError) as error:
            raise SelectionError("SEGMENTATION_UNAVAILABLE", str(error)) from error

    def segment_frame(self, rgb, config):
        from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator
        generator = SAM2AutomaticMaskGenerator(self.predictor, points_per_side=8, points_per_batch=8,
                                               crop_n_layers=0, min_mask_region_area=0)
        return rank_automatic(generator.generate(rgb), config)

    def propagate(self, state):
        return self.predictor.propagate_in_video(state)

    def segment_video(self, paths, output, config, prompt=None):
        self._load(config)
        import torch
        output.mkdir(parents=True, exist_ok=True)
        records, previous, seed, confidence = [], None, None, None
        # Predictor expects numeric JPEG names. These are disposable RGB copies, never replacements.
        work = output.parent/"sam-input"
        dimensions = []
        for path in paths:
            with Image.open(path) as image:
                dimensions.append((image.height, image.width))
        if len(set(dimensions)) != 1:
            raise SelectionError("SEGMENTATION_FAILED", "SAM video input resolution must be stable")
        with torch.inference_mode():
            start = 0
            while start < len(paths):
                stop = min(len(paths), start+config.sam_window)
                work.mkdir(exist_ok=False)
                for position, path in enumerate(paths[start:stop]):
                    with Image.open(path) as image:
                        image.convert("RGB").save(work/f"{position:06d}.jpg", quality=95)
                try:
                    state = self.predictor.init_state(video_path=str(work), offload_video_to_cpu=True,
                                                       offload_state_to_cpu=True, async_loading_frames=False)
                    if seed is not None:
                        self.predictor.add_new_mask(state, frame_idx=0, obj_id=1, mask=seed)
                    elif config.segmentation_init == "auto":
                        with Image.open(paths[0]) as image:
                            ranked = self.segment_frame(np.array(image.convert("RGB")), config)
                        if not ranked or ranked[0][0] < config.min_mask_confidence or (len(ranked)>1 and ranked[0][0]-ranked[1][0] < config.min_auto_score_margin):
                            raise SelectionError("SEGMENTATION_LOW_CONFIDENCE", "Ambiguous automatic food-and-plate initialization")
                        confidence, proposal, _ = ranked[0]
                        self.predictor.add_new_mask(state, frame_idx=0, obj_id=1, mask=proposal["segmentation"])
                    else:
                        if not prompt or prompt.get("coordinateSpace") != "decoded-pixels" or prompt.get("framePosition", 0) != 0:
                            raise SelectionError("SEGMENTATION_LOW_CONFIDENCE", "Supply a point/box on first decoded candidate in decoded-pixels")
                        height, width = dimensions[0]
                        if config.segmentation_init == "point":
                            point = np.asarray(prompt.get("point"), dtype=float)
                            if point.shape != (2,) or not np.isfinite(point).all() or not (0 <= point[0] < width and 0 <= point[1] < height):
                                raise SelectionError("SEGMENTATION_FAILED", "Invalid segmentation point")
                            self.predictor.add_new_points_or_box(state, frame_idx=0, obj_id=1, points=[point], labels=[1])
                        else:
                            box = np.asarray(prompt.get("box"), dtype=float)
                            if box.shape != (4,) or not np.isfinite(box).all() or not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
                                raise SelectionError("SEGMENTATION_FAILED", "Invalid segmentation box")
                            self.predictor.add_new_points_or_box(state, frame_idx=0, obj_id=1, box=box)
                        confidence = 1.0  # supplied-object prior; NOT model confidence, labelled below
                    for position, frame_id, mask in mapped_masks(self.propagate(state), list(range(start, stop)), dimensions[start:stop]):
                        if start and position == 0:
                            continue
                        metrics = measure(mask, previous)
                        consistency = metrics["temporalMaskConsistency"]
                        score = min(confidence, consistency if consistency is not None else confidence)
                        if (not config.min_mask_area <= metrics["maskAreaRatio"] <= config.max_mask_area
                                or (consistency is not None and consistency < config.min_mask_consistency)):
                            score = 0.0
                        name = paths[frame_id].stem+".png"
                        Image.fromarray(mask.astype(np.uint8)*255).save(output/name)
                        records.append({"position": frame_id, "mask": name, "confidence": score,
                                        "confidenceMethod": "initialization-heuristic-and-temporal-IoU; not semantic probability",
                                        **metrics})
                        previous, seed = mask, mask
                    del state
                finally:
                    shutil.rmtree(work)
                if stop == len(paths):
                    break
                start = stop-1
        (output.parent/"sam-provenance.json").write_text(json.dumps({"engine": "SAM2.1-video-predictor", "device": "cpu",
            "config": config.sam_config, "checkpointSha256": sha256(Path(config.sam_checkpoint)) if config.sam_checkpoint else None,
            "torchVersion": getattr(torch,"__version__",None), "semantics": self.semantics, "windowFrames": config.sam_window,
            "boundaryBehavior": "last propagated mask prompts next window; model memory reset", "initialization": config.segmentation_init}, indent=2))
        return records
