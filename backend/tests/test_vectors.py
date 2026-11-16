import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))


def test_swift_golden_vectors_are_current():
    import make_test_vectors
    assert make_test_vectors.main(check=True), "run tools/make_test_vectors.py and commit the vectors"
