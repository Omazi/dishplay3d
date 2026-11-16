import numpy as np
import pytest

from reconstruction.coordinates import (C_AR_FROM_CV, backproject, camera_cv_from_object, crop_intrinsics, intrinsics_matrix,
                                        invert_rigid, is_rigid, look_at_ar, mat4_from_rowmajor, mat4_to_rowmajor,
                                        object_from_camera_cv, project, scale_intrinsics)


def rand_pose(rng):
    q = rng.normal(size=4)
    q /= np.linalg.norm(q)
    w, x, y, z = q
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = rng.normal(size=3)
    return T


def test_rowmajor_roundtrip_and_layout():
    T = np.arange(16, dtype=float).reshape(4, 4)
    T[3] = [0, 0, 0, 1]
    v = mat4_to_rowmajor(T)
    assert v[3] == T[0, 3]  # translation x is the 4th number (row-major)
    assert np.array_equal(mat4_from_rowmajor(v), T)
    with pytest.raises(ValueError):
        mat4_from_rowmajor([0.0] * 15)
    with pytest.raises(ValueError):
        mat4_from_rowmajor([1.0] * 16)


def test_invert_rigid():
    rng = np.random.default_rng(0)
    for _ in range(20):
        T = rand_pose(rng)
        assert is_rigid(T)
        assert np.allclose(invert_rigid(T) @ T, np.eye(4), atol=1e-12)


def test_ar_to_cv_basis_change():
    # A camera at the origin looking down -z (AR) sees a point at z=-1 in front of it: CV depth must be +1.
    T_world_cam = np.eye(4)
    T_cv_obj = camera_cv_from_object(np.eye(4), T_world_cam)
    K = intrinsics_matrix(500, 500, 320, 240)
    uv, z = project(K, T_cv_obj, np.array([[0, 0, -1.0], [0.1, 0.1, -1.0]]))
    assert z[0] == pytest.approx(1.0)
    assert np.allclose(uv[0], [320, 240])
    # AR +y (up) must appear ABOVE the centre in the image (smaller v); AR +x to the right.
    assert uv[1, 0] > 320 and uv[1, 1] < 240
    assert np.array_equal(C_AR_FROM_CV @ C_AR_FROM_CV, np.eye(4))


def test_projection_roundtrip_and_fixed_object():
    rng = np.random.default_rng(1)
    K = intrinsics_matrix(1450.0, 1450.0, 959.5, 719.5)
    T_world_obj = rand_pose(rng)
    pts_obj = rng.uniform(-0.1, 0.1, size=(50, 3)) + [0, 0.05, 0]
    centre_world = (T_world_obj @ np.array([0, 0.05, 0, 1]))[:3]
    for _ in range(10):
        eye = centre_world + rng.normal(size=3) * 0.1 + [0, 0.35, 0]
        T_world_cam = look_at_ar(eye, centre_world, roll_deg=rng.uniform(-180, 180))
        T_obj_cv = object_from_camera_cv(T_world_obj, T_world_cam)
        uv, z = project(K, invert_rigid(T_obj_cv), pts_obj)
        assert (z > 0).all(), "points in front of a camera looking at them must have positive depth"
        back = backproject(K, uv, z)
        rec = (T_obj_cv[:3, :3] @ back.T).T + T_obj_cv[:3, 3]
        assert np.allclose(rec, pts_obj, atol=1e-9)  # the object stays fixed while the camera moves


def test_scale_and_crop_intrinsics():
    K = intrinsics_matrix(1450.0, 1450.0, 959.5, 719.5)
    Ks = scale_intrinsics(K, (1920, 1440), (640, 480))
    assert Ks[0, 0] == pytest.approx(1450 / 3)
    assert Ks[0, 2] == pytest.approx(319.5)  # centre stays centre with the pixel-centre convention
    # A 3D point projects to the same normalised location in the scaled image.
    T = np.eye(4)
    p = np.array([[0.05, -0.02, 0.5]])
    uv_full, _ = project(K, T, p)
    uv_small, _ = project(Ks, T, p)
    assert np.allclose((uv_full + 0.5) / 3 - 0.5, uv_small)
    Kc = crop_intrinsics(K, 100, 50)
    assert np.allclose(project(Kc, T, p)[0], uv_full - [100, 50])


def test_scale_consistency_baseline():
    # Distances measured in the object frame equal distances in the AR world (metric, no scale change).
    rng = np.random.default_rng(2)
    T_world_obj = rand_pose(rng)
    a, b = rand_pose(rng), rand_pose(rng)
    oa, ob = object_from_camera_cv(T_world_obj, a), object_from_camera_cv(T_world_obj, b)
    assert np.linalg.norm(oa[:3, 3] - ob[:3, 3]) == pytest.approx(np.linalg.norm(a[:3, 3] - b[:3, 3]))
