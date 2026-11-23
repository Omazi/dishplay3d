"""Optional neural finishing step: Gaussian splatting on the calculator's own graphics card.

It runs after the classic final model, only when the machine has an NVIDIA GPU with PyTorch and gsplat
installed. On a machine without them (the usual Windows/Linux PC of the prototype) nothing happens and
the classic result stands. PyTorch is imported lazily: the base install does not depend on it.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Callable


def neural_available() -> tuple[bool, str]:
    try:
        import torch
    except ImportError:
        return False, "pytorch_not_installed"
    try:
        import gsplat  # noqa: F401
    except ImportError:
        return False, "gsplat_not_installed"
    if not torch.cuda.is_available():
        return False, "no_cuda_gpu"
    return True, torch.cuda.get_device_name(0)


def run_neural(session_dir: Path, final_dir: Path, emit: Callable[[dict], None] = lambda e: None, steps: int = 7000,
               max_width: int = 1280, device: str = "cuda", rasterize=None) -> dict:
    """Export the session, train, and put splat.ply / turntable.webp / compare.jpg / neural_report.json in final_dir."""
    from .splat_export import export
    from .splat_train import load_dataset, train
    t0 = time.time()
    work = final_dir / "neural_work"
    if work.exists():
        shutil.rmtree(work)
    info = export(session_dir, work / "dataset", max_width=max_width, final_dir=final_dir)
    emit({"type": "finish_progress", "step": "neural", "done": 0, "total": steps})
    data = load_dataset(work / "dataset", work)
    rep = train(data, work / "out", steps=steps, device=device, rasterize=rasterize,
                progress=lambda d, t: emit({"type": "finish_progress", "step": "neural", "done": int(d), "total": int(t)}))
    files = []
    for name in ("splat.ply", "turntable.webp", "compare.jpg", "preview.jpg"):
        src = work / "out" / name
        if src.exists():
            dst = final_dir / ("neural_" + name if name in ("compare.jpg", "preview.jpg") else name)
            shutil.copyfile(src, dst)
            files.append(dst.name)
    rep = {"schema": "dishplay.neural/1", "method": "3D Gaussian splatting (gsplat)", "dataset": info,
           **{k: v for k, v in rep.items() if k != "log"}, "total_seconds": round(time.time() - t0, 1), "files": files}
    (final_dir / "neural_report.json").write_text(json.dumps(rep, indent=1))
    shutil.rmtree(work, ignore_errors=True)   # the dataset is a copy of the frames: do not keep it twice
    return rep
