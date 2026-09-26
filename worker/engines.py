"""Versioned engine registry. New engines must be explicit opt-ins with separate identities."""
from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class ReconstructionEngine:
    id: str
    versions: dict
    geometry_pipeline: str


LEGACY_ENGINE = ReconstructionEngine(
    id='legacy-photogrammetry-v1',
    versions=json.loads((Path(__file__).parent/'toolchain.json').read_text()),
    geometry_pipeline='colmap-exhaustive-openmvs-blender',
)
ENGINES = {LEGACY_ENGINE.id: LEGACY_ENGINE}


def engine_for(engine_id: str) -> ReconstructionEngine:
    if engine_id not in ENGINES:
        raise ValueError(f'Unsupported engine: {engine_id}. No implicit fallback is allowed.')
    return ENGINES[engine_id]
