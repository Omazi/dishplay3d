"""Opt-in preprocessing; invoke through the bounded reconstruct.py runner."""
from __future__ import annotations
import argparse
import copy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import resource
import shutil
import time
from .frame_selection.models import SelectionConfig, SelectionError, sample_indices


def associate_metadata(frames, capture, config):
    supplied = capture.get("captureMetadata", {}).get("videoFrames", capture.get("frames", []))
    if not isinstance(supplied, list):
        return
    indexed = {f.get("frameIndex"): f for f in supplied if isinstance(f, dict) and isinstance(f.get("frameIndex"), int)}
    timed = [f for f in supplied if isinstance(f, dict) and isinstance(f.get("timestampMs"), (int, float))]
    for frame in frames:
        metadata = indexed.get(frame["frameIndex"])
        if metadata is None and timed:
            closest = min(timed, key=lambda f: abs(f["timestampMs"]-frame["timestampMs"]))
            if abs(closest["timestampMs"]-frame["timestampMs"]) <= config.pose_max_gap_ms:
                metadata = closest
        if metadata:
            frame["metadata"] = copy.deepcopy(metadata.get("metadata", {}))
    references = {frame.get("metadata",{}).get("poseReference") for frame in frames
                  if isinstance(frame.get("metadata",{}).get("poseReference"),str)}
    if len(references)>1:
        for frame in frames:
            if "metadata" in frame:
                frame["metadata"]["poseSelectionRejectedCode"] = "POSE_REFERENCE_CHANGED"


def process(source, output, settings, config, capture=None, expected_sha=None):
    import cv2
    import numpy as np
    from PIL import Image
    from .video import extract_video
    from .reconstruct import execute_stage, resource_guard
    from .frame_selection import quality, similarity, overlap, coverage
    from .frame_selection.selector import select
    from .frame_selection.artifacts import contact_sheet, coverage_svg
    cv2.setNumThreads(1)
    start, cpu = time.monotonic(), time.process_time()
    records, chosen, pair_records = [], [], {}
    timings = {name:None for name in ("probeAndTimelineDecode","decodeAndCandidateExtraction","qualityAnalysis",
        "fingerprintingAndFeatureExtraction","segmentation","similarityAndGeometricMatching","keyframeSelection","debugArtifacts")}
    report = {"schema":1,"method":config.method,"config":config.document(),"source":{},"selection":{},
              "segmentation":{"enabled":False,"requested":config.segmentation,"engine":None,
                              "semantics":"dish_object = food + plate; exclude table","meanMaskConfidence":None,"lowConfidenceFrames":None},
              "continuity":{},"coverage":{},"frames":records,"timingsSeconds":timings,"warnings":[],"qualityImprovementProven":False,
              "maskApplication":{"experiment":config.experiment,"colmapMasked":False,"denseMasksApplied":False,
                                 "reason":"Pending reconstruction; masks not yet applied"}}
    try:
        source, frames, manifest = extract_video(source, output, settings, execute_stage, expected_sha,
                                                candidate_budget=config.candidate_count, extra_indices_count=config.final_count)
        timings.update(manifest["timings"])
        report["source"] = {**manifest["sourceVideo"],"durationMs":manifest["durationMs"],
                            "sourceFrameCount":manifest["sourceFrameCount"],"candidateFrameCount":len(frames)}
        associate_metadata(frames, capture or {}, config)
        baseline_indexes = set(sample_indices(manifest["sourceFrameCount"], config.final_count))
        fingerprints, feature_sets = [], []
        quality_start, similarity_seconds = time.monotonic(), 0.0
        for frame in frames:
            resource_guard(output, settings)
            with Image.open(source/frame["name"]) as image:
                rgb = np.array(image.convert("RGB"))
            gray, metrics, reasons = quality.analyze(rgb, config, frame["timestampMs"])
            t = time.monotonic()
            fp = similarity.fingerprint(gray)
            fp["pixelSha256"] = hashlib.sha256(rgb.tobytes()).hexdigest()
            fingerprints.append(fp)
            feature_sets.append(overlap.features(gray, config))
            similarity_seconds += time.monotonic()-t
            metrics["featureCount"] = len(feature_sets[-1]["points"])
            records.append({**frame,"metrics":metrics,"reasons":reasons,"selected":False,
                            "pixelSha256":fp["pixelSha256"],"temporalBaseline":frame["frameIndex"] in baseline_indexes})
        timings["qualityAnalysis"] = time.monotonic()-quality_start-similarity_seconds
        timings["fingerprintingAndFeatureExtraction"] = similarity_seconds
        segment_start = time.monotonic()
        if config.segmentation != "none":
            try:
                from .segmentation.sam2 import SAM21Segmenter
                masks = SAM21Segmenter().segment_video([source/f["name"] for f in frames], output/"masks"/"candidates", config,
                                                      (capture or {}).get("captureMetadata", {}).get("segmentationPrompt"))
                report["segmentation"].update(enabled=True,engine="SAM2.1-video-predictor",
                    meanMaskConfidence=float(np.mean([m["confidence"] for m in masks])),
                    lowConfidenceFrames=sum(m["confidence"] < config.min_mask_confidence for m in masks))
                for mask in masks:
                    record = records[mask["position"]]
                    record["mask"] = mask["mask"]
                    record["metrics"].update(mask)
                    record["metrics"].update(objectVisibility=mask["confidence"],objectCrop=mask["borderContactFraction"],
                                             visibilityStatus="MASK_HEURISTIC_NOT_SEMANTIC_CERTIFICATION")
                    if mask["confidence"] < config.min_mask_confidence:
                        record["reasons"].append("SEGMENTATION_LOW_CONFIDENCE")
                    if mask["borderContactFraction"] > config.max_border_fraction:
                        record["reasons"].append("OBJECT_NOT_FULLY_VISIBLE")
                if any(m["confidence"] < config.min_mask_confidence for m in masks):
                    raise SelectionError("SEGMENTATION_LOW_CONFIDENCE", "One or more propagated masks are uncertain")
            except (SelectionError, ImportError, RuntimeError, ValueError) as error:
                if config.segmentation_fallback != "no-mask":
                    if isinstance(error, SelectionError):
                        raise
                    raise SelectionError("SEGMENTATION_FAILED", str(error)) from error
                report["segmentation"].update(enabled=False,fallback="EXPLICIT_NO_MASK_BASELINE",error=str(error))
                for record in records:
                    record.pop("mask", None)
                    record["reasons"] = [r for r in record["reasons"] if r not in ("SEGMENTATION_LOW_CONFIDENCE","OBJECT_NOT_FULLY_VISIBLE")]
                    record["metrics"].update(objectVisibility=None,objectCrop=None,visibilityStatus="EXPLICIT_NO_MASK_FALLBACK")
        else:
            report["warnings"].append("OBJECT_VISIBILITY_UNKNOWN_SEGMENTATION_DISABLED")
        if report["segmentation"]["enabled"] and config.experiment == "POSE_MASKED__OBJECT_MASKED":
            for i, frame in enumerate(frames):
                with Image.open(source/frame["name"]) as image:
                    gray, _, _ = quality.analyze(np.array(image.convert("RGB")),config,frame["timestampMs"])
                with Image.open(output/"masks"/"candidates"/records[i]["mask"]) as mask:
                    small = cv2.resize(np.array(mask.convert("L")),(gray.shape[1],gray.shape[0]),interpolation=cv2.INTER_NEAREST)
                feature_sets[i] = overlap.features(gray,config,small)
                records[i]["metrics"]["featureCount"] = len(feature_sets[i]["points"])
        timings["segmentation"] = time.monotonic()-segment_start
        matching_seconds = 0.0
        @lru_cache(maxsize=24000)
        def pair(i, j):
            nonlocal matching_seconds
            t = time.monotonic()
            value = {**similarity.compare(fingerprints[i], fingerprints[j]),**overlap.estimate(feature_sets[i],feature_sets[j],config)}
            pair_records[f'{records[i]["frameIndex"]}:{records[j]["frameIndex"]}'] = value
            matching_seconds += time.monotonic()-t
            return value
        selection_start = time.monotonic()
        chosen, decisions = select(records, pair, config)
        timings["similarityAndGeometricMatching"] = matching_seconds
        timings["keyframeSelection"] = time.monotonic()-selection_start-matching_seconds
        report["decision"] = decisions
        for i in chosen:
            records[i]["selected"] = True
        adjacent = [pair(a,b) for a,b in zip(chosen,chosen[1:])]
        report["continuity"] = {"meanAdjacentOverlap":float(np.mean([p["overlap"] for p in adjacent])) if adjacent else None,
                                "minimumAdjacentOverlap":min((p["overlap"] for p in adjacent),default=None),
                                "loopClosureCandidate":decisions["loopClosureCandidate"],"adjacentPairs":adjacent}
        report["coverage"] = coverage.report([records[i] for i in chosen],adjacent,config)
        coverage_svg(report["coverage"],output/"coverage.svg")
        report["warnings"].extend(report["coverage"]["reasons"])
        if decisions["failure"]:
            raise SelectionError(decisions["failure"],"No acceptable ordered reconstruction chain; inspect capture_report.json")
        if config.experiment == "POSE_MASKED__OBJECT_MASKED" and not report["segmentation"]["enabled"]:
            raise SelectionError("SEGMENTATION_FAILED","Masked-pose experiment requires valid masks")
        selected_dir, selected_masks = output/"frames"/"selected",output/"masks"/"selected"
        selected_dir.mkdir(parents=True)
        selected_masks.mkdir(parents=True)
        selected_frames = []
        for i in chosen:
            frame = frames[i]
            shutil.copyfile(source/frame["name"],selected_dir/frame["name"])
            if records[i].get("mask"):
                shutil.copyfile(output/"masks"/"candidates"/records[i]["mask"],selected_masks/records[i]["mask"])
            selected_frames.append(frame)
        manifest.update(extractor=config.method,frames=selected_frames,selectionConfig=config.document(),
                        report="capture_report.json",maskExperiment=config.experiment,masksAvailable=report["segmentation"]["enabled"])
        (output/"input"/"selected_manifest.json").write_text(json.dumps(manifest,indent=2))
        return selected_frames,manifest
    except BaseException as error:
        report["failure"] = {"code":getattr(error,"code","PREPROCESSING_FAILED"),"message":str(error)}
        raise
    finally:
        for record in records:
            if not record["selected"] and not record["reasons"]:
                record["reasons"].append(report.get("failure",{}).get("code", "NOT_SELECTED_TEMPORAL_BASELINE" if config.method == "TEMPORAL_BASELINE" else "NOT_IN_BEST_OVERLAP_CHAIN"))
        def count(reasons):
            return sum(not r["selected"] and bool(set(r["reasons"]) & set(reasons)) for r in records)
        report["selection"] = {"selectedFrameCount":len(chosen),"rejectedFrameCount":len(records)-len(chosen),
                                "rejectedBlur":count(["BLURRED_FRAME","MOTION_BLUR"]),"rejectedExposure":count(["CATASTROPHIC_EXPOSURE"]),
                                "rejectedDuplicate":count(["EXACT_DUPLICATE","NEAR_DUPLICATE"]),"rejectedCrop":count(["OBJECT_NOT_FULLY_VISIBLE"])}
        report["pairMetrics"] = pair_records
        timings["preprocessingTotal"] = time.monotonic()-start
        report["resources"] = {"cpuSeconds":time.process_time()-cpu,"selfPeakRssKiB":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                               "childPeakRssKiB":resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,"gpuUsed":False,"threads":1}
        (output/"capture_report.json").write_text(json.dumps(report,indent=2,allow_nan=False))
        artifact_start = time.monotonic()
        if records:
            contact_sheet(records,source,output/"contact_sheet_candidates.jpg")
            contact_sheet([records[i] for i in chosen],source,output/"contact_sheet_selected.jpg")
            contact_sheet(records,source,output/"contact_sheet_masks.jpg",output/"masks"/"candidates")
        timings["debugArtifacts"] = time.monotonic()-artifact_start
        timings["preprocessingTotal"] = time.monotonic()-start
        (output/"capture_report.json").write_text(json.dumps(report,indent=2,allow_nan=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request",required=True,type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    try:
        process(Path(request["source"]),Path(request["output"]),request["settings"],SelectionConfig(**request["config"]),
                capture=request.get("capture"),expected_sha=request.get("expectedSha"))
    except Exception as error:
        print(f'{getattr(error,"code","PREPROCESSING_FAILED")}: {error}',flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
