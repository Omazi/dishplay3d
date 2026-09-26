"""Bounded beam search in an ordered overlap graph; weights remain experimental."""
from .coverage import direction
from .models import sample_indices


def select(records, pair, config):
    if config.method == "TEMPORAL_BASELINE":
        # Caller supplies exact source-timeline quantiles; this branch intentionally ignores QA.
        selected = [i for i, record in enumerate(records) if record.get("temporalBaseline")]
        for i in selected:
            records[i]["selectionReason"] = "SOURCE_TIMELINE_QUANTILE"
        return selected, {"failure": None, "loopClosureCandidate": closure(selected, pair, records)}
    eligible = [i for i, record in enumerate(records) if not record["reasons"]]
    if not eligible:
        return [], {"failure": "INSUFFICIENT_SHARP_FRAMES", "loopClosureCandidate": None}
    # Exact-pixel duplicates can never add geometric information, except a late loop-closing view.
    seen = {}
    usable = []
    for i in eligible:
        key = records[i]["pixelSha256"]
        duplicate = seen.get(key)
        late_loop = duplicate is not None and i >= len(records)*0.8 and duplicate <= len(records)*0.2
        if duplicate is not None and not late_loop:
            records[i]["reasons"].append("EXACT_DUPLICATE")
            records[i]["duplicateOf"] = records[duplicate]["frameIndex"]
        else:
            usable.append(i)
            seen.setdefault(key, i)
    if len(usable) < config.minimum_count:
        reason = "INSUFFICIENT_VIEWPOINT_DIVERSITY" if len(eligible) >= config.minimum_count else "INSUFFICIENT_SHARP_FRAMES"
        return [], {"failure": reason, "loopClosureCandidate": None}

    # At most two best states per (end frame, count). Cache descriptors/pairs outside this module.
    # Keeping a second path avoids one locally attractive frame forcing a disconnected dead end.
    directions = {i: direction(records[i].get("metadata"),config) for i in usable}
    states = {i: {} for i in usable}
    for i in usable[:min(config.lookahead, len(usable))]:
        states[i][1] = [(records[i]["metrics"]["qualityScore"], [i], [])]
    for position, i in enumerate(usable):
        for j in usable[position+1:position+1+config.lookahead]:
            metrics = pair(i, j)
            if not metrics["sufficient"]:
                continue
            duplicate = (metrics["phashDistance"] <= config.phash_distance
                         and metrics["medianDisplacement"] < config.duplicate_displacement)
            loop = j >= len(records)*0.8 and i <= len(records)*0.2
            if duplicate and not loop:
                continue
            for count, paths in list(states[i].items()):
                if count >= config.final_count:
                    continue
                for score, path, contributions in paths:
                    d = directions[j]
                    covered = {directions[k]["azimuthBin"] for k in path if directions[k]}
                    # No fabricated angular bins: when pose is absent use only normalized temporal span, labelled a proxy.
                    gain = float(d["azimuthBin"] not in covered) if d else (j-i)/max(1, len(records)-1)
                    motion = metrics["medianDisplacement"]
                    novelty = min(1.0, motion/config.ideal_displacement) * min(1.0, config.ideal_displacement/max(motion, 1e-8))
                    quality = records[j]["metrics"]
                    components = {"quality": config.quality_weight*quality["qualityScore"],
                                  "novelty": config.novelty_weight*novelty, "coverage": config.coverage_weight*gain,
                                  "redundancy": -config.redundancy_weight*float(motion < config.min_novel_displacement),
                                  "blur": -config.blur_weight*max(0, 1-quality["highFrequencyRatio"]/max(config.min_high_frequency, 1e-8)),
                                  "crop": -config.crop_weight*(quality.get("objectCrop") or 0)}
                    utility = sum(components.values())
                    if utility > records[j].get("bestEvaluatedUtility",float("-inf")):
                        records[j]["bestEvaluatedUtility"] = utility
                        records[j]["bestEvaluatedContributions"] = components
                        records[j]["bestEvaluatedPredecessor"] = records[i]["frameIndex"]
                    candidate = (score+utility, path+[j], contributions+[components])
                    bucket = states[j].setdefault(count+1, [])
                    bucket.append(candidate)
                    bucket.sort(key=lambda item: (-item[0], item[1]))
                    del bucket[config.beam_width:]
    candidates = [state for counts in states.values() for count, paths in counts.items()
                  if count >= config.minimum_count for state in paths]
    if not candidates:
        return [], {"failure": "INSUFFICIENT_OVERLAP", "loopClosureCandidate": None}
    # Prefer a full chain, then chronological span, then composite utility.
    score, chosen, contributions = max(candidates, key=lambda item: (len(item[1]), item[1][-1]-item[1][0], item[0], [-i for i in item[1]]))
    # Reserve the last slot for a geometrically connected return to the first viewpoint when available.
    start, penultimate = chosen[0], chosen[-2]
    loops = [j for j in usable if j > penultimate and j >= len(records)*0.8
             and pair(start, j)["sufficient"] and pair(start, j)["phashDistance"] <= config.phash_distance
             and pair(penultimate, j)["sufficient"]]
    if loops:
        chosen[-1] = loops[-1]
        contributions[-1] = {"loopClosureOverride": True, "scoreNotUsed": True}
    for offset, i in enumerate(chosen):
        records[i]["selectionReason"] = "OVERLAP_CHAIN_START" if offset == 0 else "QUALITY_NOVELTY_OVERLAP_CHAIN"
        records[i]["scoreContributions"] = contributions[offset-1] if offset else {"quality": records[i]["metrics"]["qualityScore"]}
    for i in usable:
        if i in chosen:
            continue
        previous = max((j for j in chosen if j < i), default=chosen[0])
        m = pair(min(previous, i), max(previous, i)) if previous != i else None
        reason = ("NEAR_DUPLICATE" if m and m["sufficient"] and m["phashDistance"] <= config.phash_distance
                  and m["medianDisplacement"] < config.duplicate_displacement else "NOT_IN_BEST_OVERLAP_CHAIN")
        records[i]["reasons"].append(reason)
    return chosen, {"failure": None, "chainScore": score, "loopClosureCandidate": closure(chosen, pair, records)}


def closure(chosen, pair, records):
    if len(chosen) < 3:
        return None
    first, last = chosen[0], chosen[-1]
    metrics = pair(first, last)
    return {"firstFrameIndex": records[first]["frameIndex"], "lastFrameIndex": records[last]["frameIndex"],
            "candidate": metrics["sufficient"], "evidence": metrics,
            "note": "Verified matches suggest closure; they do not prove a complete orbit."}
