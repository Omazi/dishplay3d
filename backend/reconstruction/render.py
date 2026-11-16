"""Software rendering of a DPG1 geometry to an image (no GPU). Used for reports and for the
`apercu.png` written next to every finished model, so a result can be judged or shared at a glance."""
from __future__ import annotations

import cv2
import numpy as np


def view_matrix(az_deg, el_deg, centre, dist):
    az, el = np.radians(az_deg), np.radians(el_deg)
    eye = centre + dist * np.array([np.cos(el) * np.cos(az), np.sin(el), np.cos(el) * np.sin(az)])
    f = centre - eye
    f /= np.linalg.norm(f)
    r = np.cross(f, [0, 1, 0])
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    R = np.stack([r, -u, f])  # CV camera rows
    return R, -R @ eye


def render(g, az, el, size=480, mode="both"):
    h = g["header"]
    bs = np.array(h["box_size_m"])
    centre = np.array([0, bs[1] / 3, 0])
    R, t = view_matrix(az, el, centre, 1.6 * max(bs[0], bs[2]))
    f = size * 0.95
    img = np.full((size, size, 3), 40, np.uint8)
    zbuf = np.full((size, size), np.inf)
    light = np.array([0.3, 1.0, 0.4]) / np.linalg.norm([0.3, 1.0, 0.4])

    def proj(P):
        pc = P @ R.T + t
        return np.stack([pc[:, 0] / pc[:, 2] * f + size / 2, pc[:, 1] / pc[:, 2] * f + size / 2], 1), pc[:, 2]

    if mode in ("mesh", "both") and len(g["tris"]):
        V = g["verts"].astype(np.float64)
        uv, z = proj(V)
        T = g["tris"].astype(np.int64)
        col = g["vert_rgbc"][:, :3].astype(np.float64)
        cls = g["vert_rgbc"][:, 3]
        col[cls == 1] = col[cls == 1] * 0.5 + np.array([60, 90, 200]) * 0.5
        col[cls == 2] = col[cls == 2] * 0.4 + np.array([220, 60, 200]) * 0.6
        n = np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        shade = 0.45 + 0.55 * np.abs(n @ light)
        zt = z[T].mean(1)
        for i in np.argsort(-zt):
            tri = uv[T[i]]
            c = col[T[i]].mean(0) * shade[i]
            cv2.fillConvexPoly(img, np.round(tri * 4).astype(np.int32), c[::-1].tolist(), lineType=cv2.LINE_AA, shift=2)
        # crude z for points occlusion
        for i in range(0):
            pass
    if mode in ("points", "both") and len(g["points"]) and (mode == "points" or len(g["tris"]) == 0):
        uv, z = proj(g["points"].astype(np.float64))
        c = g["point_rgbc"][:, :3].astype(np.float64)
        prov = g["point_rgbc"][:, 3] == 4
        c[prov] *= 0.6
        order = np.argsort(-z)
        ui = np.round(uv[order, 0]).astype(int)
        vi = np.round(uv[order, 1]).astype(int)
        ok = (ui >= 1) & (ui < size - 1) & (vi >= 1) & (vi < size - 1)
        for du in (0, 1):
            for dv in (0, 1):
                img[vi[ok] + dv, ui[ok] + du] = c[order][ok][:, ::-1].astype(np.uint8)
    return img



def contact_sheet(g, mode: str = "mesh", label: str | None = None) -> np.ndarray:
    """Four views (two oblique, top, side) in one image."""
    tiles = [render(g, az, el, mode=mode) for az, el in ((30, 35), (150, 35), (270, 70), (90, 15))]
    out = np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:])])
    h = g["header"]
    text = label or f"v{h['version']} {h['kind']} frames={h.get('integrated_frames')} pts={h['point_count']} tris={h['triangle_count']}"
    cv2.putText(out, text, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(out, "bleu = interpole (texture trop faible pour mesurer)", (8, out.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                (255, 200, 150), 1, cv2.LINE_AA)
    return out
