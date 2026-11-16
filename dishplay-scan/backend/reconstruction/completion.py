"""Completion interface. DISABLED by default: P1 never fills geometry on its own.

A provider may propose geometry for regions that were not observed (e.g. the
hidden base of a plate). Its output is kept SEPARATE from the measured mesh,
with a mask of modified regions and a provenance string, and must be accepted
by the creator. Measured vertices are protected: a proposal may never move them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np


@dataclass
class CompletionProposal:
    vertices: np.ndarray
    triangles: np.ndarray
    modified_mask: np.ndarray      # per proposed vertex: True where geometry is new/changed
    provenance: str                 # e.g. "geometric_base_v1", model name + licence
    licence: str
    notes: list[str] = field(default_factory=list)


class CompletionProvider(Protocol):
    name: str

    def propose(self, vertices: np.ndarray, triangles: np.ndarray, classes: np.ndarray, box_size_m) -> CompletionProposal | None: ...


class NoCompletion:
    name = "none"

    def propose(self, vertices, triangles, classes, box_size_m):
        return None


def check_measured_protected(original_vertices: np.ndarray, original_classes: np.ndarray, proposal: CompletionProposal,
                             tol_m: float = 1e-6) -> bool:
    """A proposal is acceptable only if every MEASURED vertex still exists unchanged."""
    from scipy.spatial import cKDTree

    measured = original_vertices[original_classes == 0]
    if len(measured) == 0:
        return True
    if len(proposal.vertices) == 0:
        return False
    d, _ = cKDTree(proposal.vertices).query(measured)
    return bool(np.all(d <= tol_m))
