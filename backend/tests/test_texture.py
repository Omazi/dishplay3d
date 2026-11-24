"""The texture of the delivered model: which photographs paint it, and what the projection does where the
surface turns away from the cameras (reconstruction/refinement.py)."""
import json

import numpy as np
import open3d as o3d
import pytest

from reconstruction.coordinates import C_AR_FROM_CV, intrinsics_matrix, look_at_ar
from reconstruction.engine import Box, EngineConfig, SessionEngine
from reconstruction.refinement import _texture_views, texture_mesh
from reconstruction.stereo_depth import View
from tests.helpers import write_session
from tests.synthetic import orbit_poses

MARKER_BGR = (0.0, 0.0, 255.0)      # the "fused colour" given to the texture step: pure red, easy to tell from a photograph
PLAIN = 200                         # grey level of the plain photographs


def _engine_with_poses(tmp_path, poses):
    """An engine that knows `len(poses)` frames (all showing the same stored picture: only the cameras matter)."""
    sdir = write_session(tmp_path, n=2)
    sj = json.loads((sdir / "session.json").read_text())
    eng = SessionEngine(sdir, Box.from_json(sj["box"]), EngineConfig())
    meta0 = json.loads((sdir / "frames" / "000000.json").read_text())
    for i, T in enumerate(poses):
        m = {**meta0, "frame_id": i, "T_world_from_cameraAR": [float(v) for v in np.asarray(T).reshape(-1)]}
        eng.add_frame(m, sdir / "frames" / "000000.jpg", received_at=0.0)
    return eng


def _sides(eng, frame_ids):
    """The sides of the dish (out of 12) that these cameras look from."""
    return {int((np.degrees(np.arctan2(*eng._geometry(f)[0][[2, 0], 3])) % 360) // 30) for f in frame_ids}


def _farthest_camera_m(eng, frame_ids, chosen):
    """How far the camera of the scan that is worst served stands from the nearest chosen camera."""
    C = np.stack([eng._geometry(f)[0][:3, 3] for f in frame_ids])
    S = np.stack([eng._geometry(f)[0][:3, 3] for f in chosen])
    return float(np.linalg.norm(C[:, None] - S[None], axis=2).min(1).max())


@pytest.mark.parametrize("n", [60, 71, 85, 94, 107, 140])
def test_the_texture_takes_one_view_per_direction_from_the_whole_main_tour(tmp_path, n):
    """36 photographs paint the texture. They used to be the first ones in capture order (`ids[::step][:36]`):
    a tour lost its end (with 71 views, its second half) and that side of the dish got no photograph. They are
    now taken all around the dish, from the main tour (orbit_poses: one lap, then a higher one)."""
    eng = _engine_with_poses(tmp_path, orbit_poses(n))
    ids, tour = list(range(n)), int(n * 0.7)
    chosen = [v.frame_id for v in _texture_views(eng, ids)]
    assert len(chosen) == 36 and chosen == sorted(set(chosen)) and set(chosen) <= set(ids)
    assert _sides(eng, chosen) == _sides(eng, ids), "every side of the dish"
    assert all(f < tour for f in chosen), "the higher pass is not mixed in while the tour shows every direction"
    for part in range(4):       # every quarter of the tour gives its share (9 of 36 when they are dealt evenly)
        got = sum(part * tour / 4 <= f < (part + 1) * tour / 4 for f in chosen)
        assert got >= 7, f"quarter {part + 1} of a tour of {tour} views gives {got} of the 36 texture views: {chosen}"
    # every photograph of the tour has a texture view close to it (the cameras are 31 cm from the axis of the dish)
    assert _farthest_camera_m(eng, range(tour), chosen) < 0.06


def test_the_texture_prefers_the_sharpest_view_of_each_place(tmp_path):
    """Two neighbouring photographs show the same thing; the blurred one must not be the one that paints it."""
    n = 120
    eng = _engine_with_poses(tmp_path, orbit_poses(n))
    for f, rec in eng.frames.items():
        rec.sharpness = 30.0 if f % 2 else 100.0        # every other view is blurred
    tour = int(n * 0.7)
    chosen = [v.frame_id for v in _texture_views(eng, list(range(n)))]
    assert len(chosen) == 36
    assert sum(f % 2 == 0 for f in chosen) >= 33, f"blurred views chosen: {[f for f in chosen if f % 2]}"
    assert _sides(eng, chosen) == _sides(eng, range(n)) and _farthest_camera_m(eng, range(tour), chosen) < 0.06, \
        "and no part of the tour is given up for it"
    assert sum(0.75 * tour <= f < tour for f in chosen) >= 7


def test_what_the_main_tour_did_not_show_is_taken_from_another_pass():
    """Half a tour at one height, the other half of the turn only seen from higher up: every direction still
    gets its photograph. And two tours of the same size: the lower one, which sees the flanks, is the main one."""
    from reconstruction.refinement import texture_view_choice

    def ring(n, elevation_deg, start_deg, sweep_deg, radius=0.38):
        az = np.radians(start_deg + sweep_deg * (np.arange(n) + 0.5) / n)
        e = np.radians(elevation_deg)
        return np.stack([radius * np.cos(e) * np.cos(az), np.full(n, radius * np.sin(e)), radius * np.cos(e) * np.sin(az)], 1)

    centres = np.concatenate([ring(40, 35, 0, 180), ring(30, 60, 180, 180)])
    chosen = texture_view_choice(centres, 36)
    side = lambda idx: {int((np.degrees(np.arctan2(centres[i, 2], centres[i, 0])) % 360) // 30) for i in idx}     # noqa: E731
    assert len(chosen) == 36 and side(chosen) == set(range(12))
    assert sum(i < 40 for i in chosen) == 18 and sum(i >= 40 for i in chosen) == 18
    both = np.concatenate([ring(50, 60, 0, 360), ring(50, 35, 0, 360)])
    assert all(i >= 50 for i in texture_view_choice(both, 36))
    few = ring(20, 35, 0, 360)
    assert texture_view_choice(few, 36) == list(range(20))            # fewer views than places: all of them


def _ball(radius=0.06):
    """A ball standing on the table: its upper half faces the cameras, its lower half turns away from them."""
    m = o3d.geometry.TriangleMesh.create_sphere(radius=radius, resolution=40)
    m.translate([0, radius, 0])
    return np.asarray(m.vertices), np.asarray(m.triangles)


def _plain_ring(n, elevation_deg=35.0, radius=0.38, w=640, h=480, fx=500.0):
    """n cameras around the ball, each with a perfectly plain photograph."""
    K = intrinsics_matrix(fx, fx, w / 2 - 0.5, h / 2 - 0.5)
    views = []
    e = np.radians(elevation_deg)
    for i in range(n):
        az = 2 * np.pi * i / n
        eye = np.array([radius * np.cos(e) * np.cos(az), radius * np.sin(e), radius * np.cos(e) * np.sin(az)])
        views.append(View(i, np.full((h, w, 3), PLAIN, np.uint8), K, look_at_ar(eye, [0, 0.06, 0], roll_deg=-90) @ C_AR_FROM_CV))
    return views


def _texels_inside_triangles(uv, tex):
    """Colour of the atlas at four points well inside every triangle: (triangles, 4, 3) BGR."""
    H, W = tex.shape[:2]
    weights = np.array([[1 / 3, 1 / 3, 1 / 3], [0.6, 0.2, 0.2], [0.2, 0.6, 0.2], [0.2, 0.2, 0.6]])
    p = np.einsum("sk,tkc->tsc", weights, uv)
    x = np.clip(np.round(p[:, :, 0] * (W - 1)).astype(int), 0, W - 1)
    y = np.clip(np.round(p[:, :, 1] * (H - 1)).astype(int), 0, H - 1)
    return tex[y, x].astype(int)


def _sorted_texels(V, T, views):
    uv, tex, used, filled = texture_mesh(V, T, views, tex_size=1024, colors_bgr=np.tile(MARKER_BGR, (len(V), 1)))
    col = _texels_inside_triangles(uv, tex)
    photo = (np.abs(col - PLAIN) <= 8).all(2)                               # the plain photograph, as it is
    marker = (np.abs(col - np.array(MARKER_BGR, int)) <= 2).all(2)          # the fused colour, where no photograph reaches
    height_mm = V[T].mean(1)[:, 1] * 1000
    return col, photo, marker, height_mm, used, filled


def test_plain_photographs_give_a_plain_texture():
    """Where the surface turns away from the cameras the projection used to leave a darkened band (grey 35 to
    130 instead of 200 on the lower flank of this ball): only texels left completely black were corrected.
    Every texel is now either the photograph at its true brightness or the fused colour, never a darkened mix."""
    V, T = _ball()
    col, photo, marker, height_mm, used, filled = _sorted_texels(V, T, _plain_ring(16))
    assert used == 16
    odd = ~(photo | marker)
    assert odd.mean() < 0.002, (f"{odd.mean() * 100:.1f} % of the texels are neither the photograph nor the fused colour, "
                                f"for example {col[odd][:5].tolist()}")
    assert photo[height_mm > 30].mean() > 0.995, "what the cameras see well is painted by the photographs"
    # the flank that turns away (20 to 30 mm up, seen at a grazing angle) keeps the photographs, at full brightness
    band = (height_mm > 20) & (height_mm <= 30)
    assert photo[band].mean() > 0.95, photo[band].mean()
    assert marker[height_mm < 8].mean() > 0.99, "the underside, which no camera sees, takes the fused colour"
    assert 0.05 < filled < 0.3, filled


def test_a_tour_of_71_views_paints_every_side():
    """The same ball, one tour of 71 plain photographs: taking the first 36 left the far side of the tour to
    the fused colour (11 % of the triangles the cameras see well)."""
    V, T = _ball()
    col, photo, marker, height_mm, used, filled = _sorted_texels(V, T, _plain_ring(71))
    assert used == 36
    seen = height_mm > 35
    assert photo[seen].mean() > 0.995, f"{(~photo[seen]).mean() * 100:.1f} % of the well seen triangles are not painted by a photograph"
