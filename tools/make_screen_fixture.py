"""Sample dishes for the iPhone app's screen check (ios/UITests/Fixtures/Sessions).

The screen check opens every screen of the app in the iPhone simulator, which has neither camera nor
calculator: the dishes it shows are written here, once, by the real engine from the project's own synthetic
plate (backend/tests/synthetic.py). No photograph and no outside data are involved.

Three dishes, laid out exactly like the folders the app keeps on the iPhone:
  - one finished (result picture, final model, textured GLB and USDZ, the preview of the middle of its scan,
    the calculator's report with the check of the real width, and its verdict as the app keeps it);
  - one being computed (views only, all sent, finishing requested);
  - one interrupted (views only, most of them not sent).

The files are made small on purpose (coarser final mesh and texture than a real result).

    cd backend && .venv/bin/python ../tools/make_screen_fixture.py
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import open3d as o3d

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from reconstruction.engine import Box, EngineConfig, SessionEngine  # noqa: E402
from reconstruction.preview_format import decode_geometry, encode_geometry  # noqa: E402
from reconstruction.refinement import finish_session  # noqa: E402
from tests.helpers import write_session  # noqa: E402

OUT = ROOT / "ios" / "UITests" / "Fixtures" / "Sessions"
VIEWS = 60
LIVE_AFTER = 20          # the "middle of the scan" preview is the one made after this many views
FINAL_TRIANGLES = 9000   # final model shown by the app (a real one has up to 150 000)
FINAL_POINTS = 6000
REAL_WIDTH_M = 0.24      # the synthetic plate is 24 cm wide: what its owner would type as "largeur réelle"


def lighter_final(blob: bytes) -> bytes:
    """The final preview with fewer points and triangles, in the same format."""
    g = decode_geometry(blob)
    mesh = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(g["verts"].astype(np.float64)),
                                     o3d.utility.Vector3iVector(g["tris"].astype(np.int32)))
    mesh.vertex_colors = o3d.utility.Vector3dVector(g["vert_rgbc"][:, :3].astype(np.float64) / 255.0)
    small = mesh.simplify_quadric_decimation(FINAL_TRIANGLES)
    small.remove_unreferenced_vertices()
    small.compute_vertex_normals()
    V = np.asarray(small.vertices, np.float32)
    # each kept vertex takes the class (measured, interpolated, estimated) of the nearest original one
    tree = o3d.geometry.KDTreeFlann(mesh)
    nearest = np.array([tree.search_knn_vector_3d(v.astype(np.float64), 1)[1][0] for v in V])
    rgbc = np.concatenate([(np.asarray(small.vertex_colors) * 255).round().astype(np.uint8), g["vert_rgbc"][nearest, 3:4]], 1)
    keep = np.linspace(0, len(g["points"]) - 1, min(FINAL_POINTS, len(g["points"]))).astype(np.int64)
    return encode_geometry(g["header"], g["points"][keep], g["point_rgbc"][keep], V, rgbc,
                           np.asarray(small.vertex_normals, np.float32), np.asarray(small.triangles, np.uint32))


def copy_views(session: Path, dish: Path, ids, sent) -> None:
    """A few views of the scan, smaller than the originals, with the marker of those already sent."""
    (dish / "frames").mkdir(parents=True)
    for k, fid in enumerate(ids):
        picture = cv2.imread(str(session / "frames" / f"{fid:06d}.jpg"))
        cv2.imwrite(str(dish / "frames" / f"{k:06d}.jpg"), picture, [cv2.IMWRITE_JPEG_QUALITY, 72])
        shutil.copy(session / "frames" / f"{fid:06d}.json", dish / "frames" / f"{k:06d}.json")
        if k < sent:
            (dish / "frames" / f"{k:06d}.sent").write_bytes(b"")


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="dishplay-fixture-"))
    session = write_session(work, n=VIEWS)
    box = Box.from_json(json.loads((session / "session.json").read_text())["box"])
    clock = {"t": 0.0}
    engine = SessionEngine(session, box, EngineConfig(), clock=lambda: clock["t"])
    live = None
    for i, meta_path in enumerate(sorted((session / "frames").glob("*.json"))):
        meta = json.loads(meta_path.read_text())
        clock["t"] = meta["timestamp_s"]
        engine.add_frame(meta, meta_path.with_suffix(".jpg"), received_at=clock["t"])
        engine.process_pending(live=False)
        if engine.should_snapshot():
            snapshot = engine.snapshot()
            if i < LIVE_AFTER or live is None:
                live = snapshot
    engine.flush()
    report = finish_session(engine, work / "final", web_triangles=8000, texture_size=1024, reference_width_m=REAL_WIDTH_M)
    assert report["texture"]["status"] == "ok" and report["texture"]["usdz"]["status"] == "ok", report["texture"]

    if OUT.exists():
        shutil.rmtree(OUT)
    done = OUT / "2026-11-18T12-30-00Z"
    (done / "results").mkdir(parents=True)
    for name in ("apercu.png", "model.glb", "model.usdz", "report.json"):
        shutil.copy(work / "final" / name, done / "results" / name)
    # What the app keeps of the final verdict (SessionStore.saveOutcome): the two fields, keys sorted.
    outcome = {"fallbacks": report.get("fallbacks") or [], "verdict": report.get("verdict")}
    (done / "outcome.json").write_text(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
    (done / "results" / "final_preview.dpg").write_bytes(lighter_final((work / "final" / "final_preview.dpg").read_bytes()))
    (done / "results" / "live_preview.dpg").write_bytes(live[1])
    (done / "name.txt").write_text("Assiette d’essai")
    (done / "server_session.txt").write_text("exemple-termine")
    (done / "finish.requested").write_bytes(b"")
    copy_views(session, done, [5, 25, 45], sent=3)

    computing = OUT / "2026-11-19T19-05-00Z"
    copy_views(session, computing, [10, 30, 50], sent=3)
    (computing / "name.txt").write_text("Couscous royal aux sept légumes et merguez")
    (computing / "server_session.txt").write_text("exemple-en-calcul")
    (computing / "finish.requested").write_bytes(b"")

    interrupted = OUT / "2026-11-20T20-15-00Z"
    copy_views(session, interrupted, [0, 20, 40], sent=1)
    (interrupted / "server_session.txt").write_text("exemple-interrompu")

    shutil.rmtree(work)
    total = 0
    for f in sorted(OUT.rglob("*")):
        if f.is_file():
            total += f.stat().st_size
            print(f"{f.stat().st_size:>9}  {f.relative_to(OUT)}")
    print(f"{total / 1e6:.2f} MB in {OUT.relative_to(ROOT)}  (engine {report['engine']})")


if __name__ == "__main__":
    main()
