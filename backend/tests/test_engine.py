import json

import numpy as np
import pytest

from reconstruction.engine import Box, EngineConfig, SessionEngine
from reconstruction.preview_format import decode_geometry
from tests.helpers import box_json, write_session
from tests.synthetic import FOOD_CENTER, FOOD_RADIUS, SyntheticScene, distance_to_scene, orbit_poses


def run(sdir, cfg=None, limit=None, events=None):
    sj = json.loads((sdir / "session.json").read_text())
    clock = {"t": 0.0}
    eng = SessionEngine(sdir, Box.from_json(sj["box"]), cfg or EngineConfig(), emit=(events.append if events is not None else None),
                        clock=lambda: clock["t"])
    snaps = []
    for mp in sorted((sdir / "frames").glob("*.json"))[:limit]:
        meta = json.loads(mp.read_text())
        clock["t"] = meta["timestamp_s"]
        eng.add_frame(meta, mp.with_suffix(".jpg"), received_at=clock["t"])
        eng.process_pending(live=False)
        if eng.should_snapshot():
            snaps.append(eng.snapshot())
    if eng.flush():
        snaps.append(eng.snapshot())
    return eng, snaps


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    return write_session(tmp_path_factory.mktemp("s"), n=60)


def test_progressive_points_then_mesh_before_finish(session):
    eng, snaps = run(session)
    assert len(snaps) >= 5
    kinds = [h["kind"] for h, _ in snaps]
    assert kinds[0] in ("points", "points+mesh")
    first_mesh = next(i for i, k in enumerate(kinds) if k == "points+mesh")
    assert first_mesh <= 3, "a partial surface must appear early in the capture, long before finishing"
    versions = [h["version"] for h, _ in snaps]
    assert versions == sorted(versions) and len(set(versions)) == len(versions)
    # Geometry is real: every snapshot decodes and the points lie on the true surfaces.
    sc = SyntheticScene()
    g = decode_geometry(snaps[-1][1])
    d = distance_to_scene(sc, g["points"])
    assert np.median(d) < 0.004 and np.percentile(d, 80) < 0.008
    dm = distance_to_scene(sc, g["verts"])
    assert np.median(dm) < 0.003
    # Measured surface grows as new regions are observed.
    areas = [h["surface"]["measured_m2"] for h, _ in snaps if h["kind"] == "points+mesh"]
    assert areas[-1] > areas[0] * 1.3
    assert {"0", "1", "4"} <= set(snaps[-1][0]["classes"])


def test_concavity_preserved(session):
    eng, snaps = run(session)
    g = decode_geometry(snaps[-1][1])
    V = g["verts"]
    r = np.hypot(V[:, 0], V[:, 2])
    food = np.linalg.norm(V - FOOD_CENTER, axis=1) < FOOD_RADIUS + 0.01
    centre = V[(r < 0.03) & ~food, 1]
    rim = V[(r > 0.1) & (r < 0.115), 1]
    assert len(centre) > 10 and len(rim) > 10
    assert np.median(centre) < 0.013, "well of the plate must stay hollow (true 8 mm)"
    assert np.percentile(rim, 90) > 0.018, "rim must stay higher than the well (true 22 mm)"


def test_unobserved_region_stays_unknown(tmp_path):
    """Only part of an orbit is captured: geometry may exist only where a camera actually looked."""
    from scipy.spatial import cKDTree
    from tests.synthetic import visible_ground_truth
    P = orbit_poses(60)[:20]
    sdir = write_session(tmp_path, poses=P)
    eng, snaps = run(sdir)
    g = decode_geometry(snaps[-1][1])
    seen = visible_ground_truth(SyntheticScene(), P)
    d, _ = cKDTree(seen).query(g["verts"])
    assert np.percentile(d, 98) < 0.008, "no surface may be invented in regions no camera saw"
    # and the unseen part of the plate exists in reality: make sure the test is meaningful
    allgt = visible_ground_truth(SyntheticScene(), orbit_poses(60))
    assert len(allgt) > 1.05 * len(seen)


def test_epochs_are_never_mixed(tmp_path):
    sdir = write_session(tmp_path, n=30, epoch_of=lambda i: 0 if i < 20 else 1)
    events = []
    eng, _ = run(sdir, events=events)
    assert all(eng.frames[i].status == "other_epoch" for i in range(20, 30))
    assert set(eng.fusion.integrated_frames) <= set(range(20))
    assert any(e["type"] == "frame" and e["status"] == "other_epoch" for e in events)


def test_box_revision_rebuilds_from_frames(session):
    eng, _ = run(session, limit=20)
    n_before = len(eng.fusion.integrated_frames)
    b = json.loads((session / "session.json").read_text())["box"]
    b2 = dict(b, size_m={"width": 0.30, "height": 0.08, "depth": 0.30}, revision=1)
    eng.set_box(Box.from_json(b2), reprocess=True)
    assert len(eng.fusion.integrated_frames) == 0  # nothing silently transformed
    eng.process_pending(live=False)
    assert len(eng.fusion.integrated_frames) >= n_before - 2
    h, _ = eng.snapshot()
    assert h["box_revision"] == 1 and h["box_size_m"][0] == pytest.approx(0.30)


def test_replay_is_deterministic(session):
    a, sa = run(session, limit=25)
    b, sb = run(session, limit=25)
    assert [h["version"] for h, _ in sa] == [h["version"] for h, _ in sb]
    ga, gb = decode_geometry(sa[-1][1]), decode_geometry(sb[-1][1])
    assert np.array_equal(ga["points"], gb["points"]) and np.array_equal(ga["tris"], gb["tris"])


def test_duplicate_views_do_not_inflate_coverage(tmp_path):
    P = orbit_poses(60)
    poses = [P[0], P[1], P[2]] * 6
    sdir = write_session(tmp_path, poses=poses)
    eng, _ = run(sdir)
    cov = eng.coverage()
    assert cov["visited_bins"] <= 2 < cov["total_bins"]


def test_tracking_limited_and_blur_rejected(tmp_path):
    sdir = write_session(tmp_path, n=8)
    mp = sdir / "frames" / "000003.json"
    m = json.loads(mp.read_text())
    m["tracking"] = {"state": "limited", "reason": "excessive_motion"}
    mp.write_text(json.dumps(m))
    eng, _ = run(sdir)
    assert eng.frames[3].status == "rejected" and eng.frames[3].reason == "tracking_not_normal"


def test_backlog_defers_but_keeps_frames(session):
    sj = json.loads((session / "session.json").read_text())
    eng = SessionEngine(session, Box.from_json(sj["box"]), EngineConfig(max_backlog_live=4))
    for mp in sorted((session / "frames").glob("*.json"))[:12]:
        eng.add_frame(json.loads(mp.read_text()), mp.with_suffix(".jpg"))
    eng.process_pending(live=True)
    deferred = [f for f, r in eng.frames.items() if r.status == "deferred"]
    assert len(deferred) == 8 and all((session / "frames" / f"{f:06d}.jpg").exists() for f in deferred)


def test_weak_texture_is_never_called_measured(tmp_path):
    """A plain white plate: whatever surface appears on it must be labelled interpolated, or be accurate."""
    sc = SyntheticScene(uniform_plate=True)
    sdir = write_session(tmp_path, n=60, scene=sc)
    eng, snaps = run(sdir)
    g = decode_geometry(snaps[-1][1])
    V, cls = g["verts"], g["vert_rgbc"][:, 3]
    r = np.hypot(V[:, 0], V[:, 2])
    plate = (r < 0.10) & (V[:, 1] > 0.004)   # the white well, away from the textured table and rim edge
    d = distance_to_scene(sc, V)
    measured_plate = plate & (cls == 0)
    if measured_plate.sum() > 50:
        assert np.percentile(d[measured_plate], 90) < 0.004, "surfaces called MEASURED must be accurate"
    assert (cls[plate] == 1).mean() > 0.5 or plate.sum() < 200, "a texture-less surface is interpolated, and says so"


def test_confirmation_rejects_a_contradicted_depth():
    """A depth map contradicted by the neighbouring views is removed, an agreeing one is kept."""
    from reconstruction.consistency import DepthView, confirmed_depth
    K = np.array([[500.0, 0, 320], [0, 500.0, 240], [0, 0, 1]])

    def view(i, x, z):
        T = np.eye(4)
        T[0, 3] = x
        return DepthView(i, np.full((480, 640), z, np.float32), K, T)

    ref = view(0, 0.0, 0.50)
    good = [view(1, 0.03, 0.50), view(2, -0.03, 0.50)]
    out, agree, st = confirmed_depth(ref, good, 2)
    assert st["confirmed"] > 0.8 * st["valid"]
    bad = [view(1, 0.03, 0.60), view(2, -0.03, 0.60)]   # both neighbours see 10 cm farther: ref is a floater
    out, agree, st = confirmed_depth(ref, bad, 1)
    assert st["confirmed"] == 0 and st["violated"] > 0.8 * st["valid"]


def test_depth_scale_is_recovered_from_neighbouring_views():
    """A depth map 3 % too far (baseline length error) is measured as such against accepted views."""
    from reconstruction.consistency import DepthView, depth_scale_from_views
    K = np.array([[500.0, 0, 320], [0, 500.0, 240], [0, 0, 1]])

    def view(i, x, z):
        T = np.eye(4)
        T[0, 3] = x
        return DepthView(i, np.full((480, 640), z, np.float32), K, T)

    others = [view(1, 0.03, 0.40), view(2, -0.03, 0.40)]
    est = depth_scale_from_views(view(0, 0.0, 0.40 * 1.03), others)
    assert est is not None and abs(est[0] - 1 / 1.03) < 0.002
    est = depth_scale_from_views(view(0, 0.0, 0.40), others)
    assert est is not None and abs(est[0] - 1.0) < 0.001
    # too far off to be a baseline error: no estimate rather than a wrong one
    assert depth_scale_from_views(view(0, 0.0, 0.40 * 1.25), others) is None


def test_preview_points_stay_close_to_the_surface(session):
    """Displayed points are consistent with the fused surface; the hidden ones are counted."""
    eng, snaps = run(session)
    header, blob = snaps[-1]
    g = decode_geometry(blob)
    assert len(g["tris"]) > 0 and len(g["points"]) > 1000
    import open3d as o3d
    from reconstruction.engine import point_to_mesh_distance
    m = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(g["verts"].astype(np.float64)),
                                  o3d.utility.Vector3iVector(g["tris"].astype(np.int32)))
    d = point_to_mesh_distance(m, g["points"])
    assert d.max() <= eng.cfg.outlier_dist_m + 1e-4
    assert header["hidden_inconsistent_points"] > 0
    assert eng.metrics()["depth_scale"]["applied"] > 0


def test_finished_model_texture_reads_correctly_in_gltf(session, tmp_path):
    """The exported GLB, read with the glTF convention (v from the top), shows the real colours and has
    no black patches; the dish-only variant and the result picture are written; poses were refined."""
    import cv2
    import open3d as o3d
    from reconstruction.exports import glb_accessor, read_glb
    from reconstruction.refinement import finish_session
    from tests.synthetic import surface_color
    eng, _ = run(session, limit=45)
    rep = finish_session(eng, tmp_path / "final")
    assert rep["texture"]["status"] == "ok"
    assert (tmp_path / "final" / "apercu.png").exists() and (tmp_path / "final" / "plat_seul.glb").exists()
    assert "applied" in rep["pose_refinement"]
    js, b = read_glb(tmp_path / "final" / "model.glb")
    at = js["meshes"][0]["primitives"][0]["attributes"]
    P = glb_accessor(js, b, at["POSITION"]).astype(np.float64)
    N = glb_accessor(js, b, at["NORMAL"]).astype(np.float64)
    UV = glb_accessor(js, b, at["TEXCOORD_0"])
    v = js["bufferViews"][js["images"][0]["bufferView"]]
    tex = cv2.imdecode(np.frombuffer(b[v["byteOffset"]: v["byteOffset"] + v["byteLength"]], np.uint8), 1)
    H, W = tex.shape[:2]
    sel = np.random.default_rng(0).choice(len(P), min(8000, len(P)), replace=False)
    P, N, UV = P[sel], N[sel], UV[sel]
    seen = tex[np.clip((UV[:, 1] * (H - 1)).round().astype(int), 0, H - 1), np.clip((UV[:, 0] * (W - 1)).round().astype(int), 0, W - 1)][:, ::-1].astype(float)
    sc = SyntheticScene()
    org = P + N * 0.006
    ans = sc.scene.cast_rays(o3d.core.Tensor(np.concatenate([org, -N], 1).astype(np.float32)))
    t = ans["t_hit"].numpy()
    hit = np.isfinite(t) & (t < 0.02)
    geom = ans["geometry_ids"].numpy()
    mat = np.zeros(len(geom), int)
    for gid, k in sc.ids.items():
        mat[geom == gid] = k
    X = org - N * np.where(hit, t, 0)[:, None]
    light = np.array([0.3, 1.0, 0.2]) / np.linalg.norm([0.3, 1.0, 0.2])
    truth = np.clip(surface_color(X, mat) * (0.55 + 0.45 * np.abs(ans["primitive_normals"].numpy().astype(float) @ light))[:, None], 0, 1) * 255
    assert (seen.sum(1) < 15)[hit].mean() < 0.05, "no black (unprojected) patches"
    assert np.abs(seen[hit] - truth[hit]).mean() < 30, "texture colours match the scene when read as glTF"
