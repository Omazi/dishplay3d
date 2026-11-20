"""Will this scan give a good model? A verdict computed while the scan is still running.

The coverage ring only says that the dish was looked at from every side. It says nothing about what
the engine managed to rebuild. This module looks at the model itself:

  top_coverage    seen from above, share of the dish's footprint that has a surface (holes lower it)
  measured_share  share of the surface that was really measured (the rest was interpolated because
                  the food or the plate is too uniform or too shiny there)
  raggedness      how much the surface is in pieces (open edges compared with its area)
  sides_seen      share of the 12 directions around the dish that contributed views
  views           views that the engine could actually use

Thresholds were set on the synthetic scenes and on three public handheld captures; they have not
been checked against scans of real dishes yet.
"""
from __future__ import annotations

import numpy as np

from .mesh_preview import MEASURED, DishFootprint

GOOD, FAIR, POOR, EARLY = "good", "fair", "poor", "too_early"


def top_coverage(V: np.ndarray, fp: DishFootprint) -> float:
    """Share of the footprint (without its outer ring) that has model surface above it."""
    from scipy import ndimage
    region = fp.core if fp.core is not None else fp.grid
    if region.sum() < 20:
        return 0.0
    ij = np.floor((V[:, [0, 2]] - fp.origin) / fp.cell_m).astype(int)
    ok = (ij[:, 0] >= 0) & (ij[:, 0] < region.shape[0]) & (ij[:, 1] >= 0) & (ij[:, 1] < region.shape[1])
    occ = np.zeros(region.shape, bool)
    occ[ij[ok, 0], ij[ok, 1]] = True
    occ = ndimage.binary_closing(occ, iterations=2)   # vertices are a few cells apart: only real gaps remain
    return float((occ & region).sum() / region.sum())


def own_coverage(V: np.ndarray, cell_m: float = 0.002) -> float:
    """Seen from above, share of the model's own outline that has a surface. Used when no table was found under
    the dish (uneven support, or a table too plain to be reconstructed): the outline of the dish is then not
    known from the table, only from the model itself, so this sees the holes inside it and not a missing side."""
    from scipy import ndimage
    if len(V) < 50:
        return 0.0
    origin = V[:, [0, 2]].min(0) - 8 * cell_m
    ij = np.floor((V[:, [0, 2]] - origin) / cell_m).astype(int)
    occ = np.zeros(ij.max(0) + 9, bool)
    occ[ij[:, 0], ij[:, 1]] = True
    occ = ndimage.binary_closing(occ, iterations=2)          # vertices are a few cells apart: only real gaps remain
    region = ndimage.binary_fill_holes(ndimage.binary_closing(occ, iterations=6))
    return float(occ.sum() / region.sum()) if region.sum() else 0.0


def raggedness(V: np.ndarray, T: np.ndarray) -> float:
    """Length of the open edges of the surface divided by the square root of its area. A whole dish has
    one outline; every hole and every loose fragment adds open edges. About 10-16 on the clean test
    scenes, about 28-34 on the captures whose walls were missing."""
    if len(T) == 0:
        return 0.0
    T = T.astype(np.int64)
    edges = np.sort(np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]]), 1)
    uniq, count = np.unique(edges, axis=0, return_counts=True)
    open_edges = uniq[count == 1]
    length = float(np.linalg.norm(V[open_edges[:, 0]] - V[open_edges[:, 1]], axis=1).sum())
    a = V[T[:, 1]] - V[T[:, 0]]
    b = V[T[:, 2]] - V[T[:, 0]]
    area = float(0.5 * np.linalg.norm(np.cross(a, b), axis=1).sum())
    return length / np.sqrt(area) if area > 0 else 0.0


def scan_quality(V, T, cls, fp: DishFootprint | None, integrated: int, sides_seen: float) -> dict:
    """Verdict for the app: level, score (0-100), the numbers behind it and what to do about it."""
    if len(V) < 500 or integrated < 8:
        return {"level": EARLY, "score": 0, "issues": [], "top_coverage": None, "measured_share": None,
                "raggedness": None, "sides_seen": round(float(sides_seen), 2), "views": int(integrated)}
    V = np.asarray(V, np.float64)
    # Without a table under the dish the verdict is still given (it used to stay "too early" for the whole scan).
    cov = top_coverage(V, fp) if fp is not None else own_coverage(V)
    rag = raggedness(V, np.asarray(T))
    whole = float(np.clip((30.0 - rag) / 14.0, 0.0, 1.0))   # 1 at 16 and below, 0 at 30 and above
    measured = float((cls == MEASURED).mean()) if len(cls) else 0.0
    views = min(1.0, integrated / 45.0)
    score = 100.0 * (0.30 * cov + 0.25 * whole + 0.20 * measured + 0.15 * float(sides_seen) + 0.10 * views)
    issues = []
    if rag > 22:
        issues.append("fragmented")          # the surface is in pieces: walls or large parts are missing
    if sides_seen < 0.75:
        issues.append("sides_missing")       # walk around the remaining sides
    if cov < 0.85:
        issues.append("holes")               # parts of the dish have no surface yet
    if measured < 0.55:
        issues.append("uniform_or_shiny")    # little real measurement: uniform or glossy food / plate
    if integrated < 25:
        issues.append("few_views")           # go slower, or keep turning
    if cov >= 0.9 and rag <= 20 and measured >= 0.55 and sides_seen >= 0.9 and integrated >= 30:
        level = GOOD
    elif cov >= 0.75 and rag <= 26 and sides_seen >= 0.6:
        level = FAIR
    else:
        level = POOR
    return {"level": level, "score": int(round(score)), "issues": issues, "top_coverage": round(cov, 3),
            "measured_share": round(measured, 3), "raggedness": round(rag, 1), "sides_seen": round(float(sides_seen), 2),
            "views": int(integrated)}
