"""The neural trial (a scan -> a Gaussian-splatting model on Colab): what can be checked without a graphics
card and without PyTorch (neither is a dependency of the calculator). The trainer itself is checked by a dry
run described in docs/ESSAI_NEURONAL.md, not here."""
import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import export_splat_dataset  # noqa: E402


def session(data: Path, name: str, finished: bool, age_s: float) -> Path:
    d = data / "sessions" / name
    (d / "frames").mkdir(parents=True)
    (d / "frames" / "000001.json").write_text("{}")
    if finished:
        (d / "final").mkdir()
        (d / "final" / "report.json").write_text("{}")
    t = time.time() - age_s
    os.utime(d, (t, t))
    return d


def test_the_dataset_is_made_from_the_latest_finished_scan_not_from_a_newer_unfinished_one(tmp_path, capsys):
    older = session(tmp_path, "20261120-120000-aaaaaa", finished=True, age_s=3000)
    done = session(tmp_path, "20261121-120000-bbbbbb", finished=True, age_s=2000)
    session(tmp_path, "20261122-120000-cccccc", finished=False, age_s=10)      # started after, never finished
    assert export_splat_dataset.latest_finished_session(tmp_path) == done != older
    said = capsys.readouterr().out
    assert "n'est pas terminé" in said and done.name in said


def test_without_a_finished_scan_the_tool_says_what_to_do(tmp_path):
    with pytest.raises(SystemExit) as none:
        export_splat_dataset.latest_finished_session(tmp_path)
    assert "Aucun scan trouvé" in str(none.value)
    session(tmp_path, "20261122-120000-cccccc", finished=False, age_s=10)
    with pytest.raises(SystemExit) as unfinished:
        export_splat_dataset.latest_finished_session(tmp_path)
    assert "Terminer" in str(unfinished.value)


def code_cells():
    nb = json.loads((ROOT / "colab" / "essai_neuronal.ipynb").read_text())
    return ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]


def test_the_notebook_stops_on_a_failure_and_never_shows_a_previous_result():
    cells = [c for c in code_cells() if not c.startswith("%%writefile")]
    train = next(c for c in cells if "splat_train.py --data" in c)
    assert train.index("rm -rf /content/resultat") < train.index("splat_train.py --data") < train.index("assert _exit_code == 0")
    build = next(c for c in cells if "gsplat==1.5.3" in c)
    assert "MAX_JOBS=2" in build and "assert _exit_code == 0" in build     # the library is built, visibly, before the training
    assert build.index("MAX_JOBS=2") < build.index("gsplat.cuda._backend")
    assert not any("nvidia-smi" in c for c in cells)                        # that program is missing exactly when there is no card
    assert all("ffmpeg" not in c and "imageio" not in c for c in cells)     # no video encoder (the old one was under GPL)


def test_the_trainer_makes_up_for_the_opacity_reset_missing_in_the_pinned_library():
    """gsplat 1.5.3 never resets the opacities (a precedence mistake in its test); the trainer does it."""
    source = (ROOT / "backend" / "reconstruction" / "splat_train.py").read_text()
    assert "reset_opa(params=params, optimizers=optimizers, state=state" in source
    assert "0 < step < strategy.refine_stop_iter and step % strategy.reset_every == 0" in source
    assert "shutil.rmtree(root)" in source                                  # a second scan does not inherit the first one's files
    assert 'format="ply_compressed"' in source and "torch.isfinite" in source
