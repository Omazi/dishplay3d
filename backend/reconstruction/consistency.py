"""Multi-view geometric consistency of depth maps.

A depth pixel of the reference view is kept as MEASURED only when other views, each with its
own independently computed depth map, see a surface at the same place. A view that sees
*through* the point (its own depth is clearly farther along the same line of sight) is a
free-space violation: evidence that the point is a floater. This is what removes flying
fragments and fattened edges, and what lets weakly textured regions in: a smooth guess of the
stereo matcher survives only if independent pairs agree on it.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .coordinates import invert_rigid


@dataclass
class DepthView:
    frame_id: int
    depth: np.ndarray            # float32 metres, 0 = unknown
    K: np.ndarray
    T_obj_from_cam: np.ndarray
    image: np.ndarray | None = None   # BGR on the depth grid, lightly blurred (photo-consistency)
    confirmed: np.ndarray | None = None   # the same depth once other views have confirmed it (set when fused)
    predicted: np.ndarray | None = None   # mask of the pixels whose depth was predicted, not measured


def consistency_counts(ref: DepthView, others: list[DepthView], rel_tol: float = 0.012, abs_tol: float = 0.0015,
                       violation_factor: float = 2.0, color_tol: float = 48.0, near_front_m: float = 0.03) -> tuple[np.ndarray, np.ndarray]:
    """Per reference pixel: (number of agreeing views, number of contradictions).

    Agreement needs the same place AND the same colour in the other image. A pixel whose depth
    lands on a real surface of a different colour is "seeing through" its own surface (typical on
    weak texture, where the matcher copies the background): that counts as a contradiction, because
    fusing it would both smear the wrong colour and carve away the real surface in front.
    """
    h, w = ref.depth.shape
    agree = np.zeros((h, w), np.uint8)
    viol = np.zeros((h, w), np.uint8)
    vs, us = np.nonzero(ref.depth > 0)
    if len(vs) == 0 or not others:
        return agree, viol
    z = ref.depth[vs, us].astype(np.float64)
    K = ref.K
    pc = np.stack([(us - K[0, 2]) / K[0, 0] * z, (vs - K[1, 2]) / K[1, 1] * z, z], 1)
    po = pc @ ref.T_obj_from_cam[:3, :3].T + ref.T_obj_from_cam[:3, 3]
    a = np.zeros(len(vs), np.uint8)
    f = np.zeros(len(vs), np.uint8)
    col_ref = ref.image[vs, us].astype(np.float32) if ref.image is not None else None
    for o in others:
        T = invert_rigid(o.T_obj_from_cam)
        q = po @ T[:3, :3].T + T[:3, 3]
        zq = q[:, 2]
        ok = zq > 0.03
        uq = np.full(len(zq), -1.0)
        vq = np.full(len(zq), -1.0)
        uq[ok] = q[ok, 0] / zq[ok] * o.K[0, 0] + o.K[0, 2]
        vq[ok] = q[ok, 1] / zq[ok] * o.K[1, 1] + o.K[1, 2]
        ui = np.round(uq).astype(np.int64)
        vi = np.round(vq).astype(np.int64)
        oh, ow = o.depth.shape
        inside = ok & (ui >= 0) & (ui < ow) & (vi >= 0) & (vi < oh)
        d = np.zeros(len(zq))
        d[inside] = o.depth[vi[inside], ui[inside]]
        seen = inside & (d > 0)
        tol = np.maximum(abs_tol, rel_tol * zq)
        same_place = seen & (np.abs(d - zq) <= tol)
        if col_ref is not None and o.image is not None:
            diff = np.zeros(len(zq), np.float32)
            diff[inside] = np.linalg.norm(o.image[vi[inside], ui[inside]].astype(np.float32) - col_ref[inside], axis=1)
            same_color = diff <= color_tol
            f += (same_place & ~same_color).astype(np.uint8)
            same_place &= same_color
        a += same_place.astype(np.uint8)
        # The other view sees farther along this line of sight (it looks through the point), or it
        # places a surface slightly in front of it (same surface, different answer): both contradict.
        # A surface far in front is a genuine occluder and says nothing.
        f += (seen & (d - zq > violation_factor * tol)).astype(np.uint8)
        f += (seen & (zq - d > violation_factor * tol) & (zq - d < near_front_m)).astype(np.uint8)
    agree[vs, us] = a
    viol[vs, us] = f
    return agree, viol


def confirmed_depth(ref: DepthView, others: list[DepthView], min_agree: int = 1, majority: float = 1.5, **kw) -> tuple[np.ndarray, np.ndarray, dict]:
    """(depth with unconfirmed pixels removed, agreeing-view count, stats)."""
    agree, viol = consistency_counts(ref, others, **kw)
    valid = ref.depth > 0
    # Majority rule among the views that have an opinion about this spot.
    keep = valid & (agree >= min_agree) & (agree >= viol * majority)
    out = np.where(keep, ref.depth, 0).astype(np.float32)
    stats = {"valid": int(valid.sum()), "confirmed": int(keep.sum()),
             "violated": int((valid & (agree < viol * majority)).sum()), "neighbours": len(others)}
    return out, agree, stats


def pick_neighbours(ref: DepthView, cache: list[DepthView], max_n: int = 5, min_baseline_m: float = 0.008,
                    max_angle_deg: float = 40.0) -> list[DepthView]:
    """Nearest other views that look at the scene from a usefully different, not too different, place."""
    c0 = ref.T_obj_from_cam[:3, 3]
    z0 = ref.T_obj_from_cam[:3, 2]
    cand = []
    for o in cache:
        if o.frame_id == ref.frame_id:
            continue
        b = float(np.linalg.norm(o.T_obj_from_cam[:3, 3] - c0))
        ang = float(np.degrees(np.arccos(np.clip(np.dot(z0, o.T_obj_from_cam[:3, 2]), -1, 1))))
        if b >= min_baseline_m and ang <= max_angle_deg:
            cand.append((b, o))
    cand.sort(key=lambda t: (t[0], t[1].frame_id))
    return [o for _, o in cand[:max_n]]


def depth_scale_from_views(ref: DepthView, others: list[DepthView], max_dev: float = 0.06, min_samples: int = 1500,
                           step: int = 3) -> tuple[float, int] | None:
    """Scale of the reference depth map that best agrees with already accepted views.

    The depth of a stereo pair is proportional to the length of its baseline, and that length comes
    from the tracker: an error of 1 mm on a 35 mm baseline moves the whole depth map by 3 %, i.e.
    about a centimetre at arm's length. The direction of the rays is not affected. So the surfaces
    seen by the other views are projected into the reference view and the median ratio
    (their depth along the reference rays) / (reference depth) is returned, with the sample count.
    One number per view: nothing can slide along a plane or around a round dish, unlike a full ICP.
    """
    if not others:
        return None
    Tinv = invert_rigid(ref.T_obj_from_cam)
    h, w = ref.depth.shape
    K = ref.K
    ratios = []
    for o in others:
        sub = o.depth[::step, ::step]
        vs, us = np.nonzero(sub > 0)
        if len(vs) == 0:
            continue
        z = sub[vs, us].astype(np.float64)
        vs, us = vs * step, us * step
        pc = np.stack([(us - o.K[0, 2]) / o.K[0, 0] * z, (vs - o.K[1, 2]) / o.K[1, 1] * z, z], 1)
        po = pc @ o.T_obj_from_cam[:3, :3].T + o.T_obj_from_cam[:3, 3]
        q = po @ Tinv[:3, :3].T + Tinv[:3, 3]
        zq = q[:, 2]
        ok = zq > 0.03
        ui = np.round(q[ok, 0] / zq[ok] * K[0, 0] + K[0, 2]).astype(np.int64)
        vi = np.round(q[ok, 1] / zq[ok] * K[1, 1] + K[1, 2]).astype(np.int64)
        zq = zq[ok]
        inside = (ui >= 0) & (ui < w) & (vi >= 0) & (vi < h)
        d = ref.depth[vi[inside], ui[inside]].astype(np.float64)
        seen = d > 0
        ratios.append(zq[inside][seen] / d[seen])
    if not ratios:
        return None
    r = np.concatenate(ratios)
    centre = 1.0
    for dev in (max_dev, max_dev / 2):   # second pass re-centred: a large error is not pulled back towards 1
        sel = r[np.abs(r - centre) <= dev]
        if len(sel) < min_samples:
            return None
        centre = float(np.median(sel))
    return centre, int(len(sel))


# ---------------------------------------------------------------------------------------------------
# Smooth bias of a depth map
#
# Measured on real iPhone captures: two stereo pairs sharing the same reference view give depth maps that
# differ by several per cent, smoothly across the image (a plane seen by both is tilted by about 2 degrees
# between them, up to 8). The cause is the relative position of the two views — tracking error and rolling
# shutter — which shifts the disparity by a pixel or so, differently across the image. In inverse depth
# that is, to first order, a scale, an offset and a tilt. Treating the disagreement as outliers removes
# good data and leaves torn surfaces; estimating the four numbers and removing the bias keeps it.

@dataclass
class DepthBias:
    """Correction of a depth map in inverse depth: w' = scale * w + offset + gu * un + gv * vn,
    with un = u / width - 0.5 and vn = v / height - 0.5."""
    scale: float
    offset: float
    gu: float
    gv: float
    samples: int
    residual_rel: float      # robust scatter of what remains, relative to the depth

    def apply(self, depth: np.ndarray, gain: float = 1.0, max_rel: float = 0.08) -> np.ndarray:
        """Corrected depth map. gain < 1 applies part of the correction; no depth moves by more than max_rel."""
        h, w_img = depth.shape
        valid = depth > 0
        w = 1.0 / np.maximum(depth.astype(np.float64), 1e-6)
        un = (np.arange(w_img) / w_img - 0.5)[None, :]
        vn = (np.arange(h) / h - 0.5)[:, None]
        corr = gain * ((self.scale - 1.0) * w + self.offset + self.gu * un + self.gv * vn)
        corr = np.clip(corr, -max_rel * w, max_rel * w)
        return np.where(valid, 1.0 / (w + corr), 0.0).astype(np.float32)


def _fit_depth_bias(un: np.ndarray, vn: np.ndarray, w_ref: np.ndarray, w_tgt: np.ndarray, max_rel: float,
                    min_samples: int, ridge: float = 0.02) -> DepthBias | None:
    """Robust fit of w_tgt = scale * w_ref + offset + gu * un + gv * vn."""
    ratio = w_tgt / w_ref
    centre = 1.0
    sel = np.ones(len(ratio), bool)
    for dev in (max_rel, max_rel * 0.75):          # same two-pass gate as the scale estimate: occlusions and
        sel = np.abs(ratio - centre) <= dev        # gross errors are not part of a smooth bias
        if sel.sum() < min_samples:
            return None
        centre = float(np.median(ratio[sel]))
    un, vn, w_ref, w_tgt = un[sel], vn[sel], w_ref[sel], w_tgt[sel]
    wbar = float(np.median(w_ref))
    y = (w_tgt - w_ref) / wbar
    use_scale = float(np.std(w_ref / wbar)) > 0.03                      # enough depth variation to tell a scale from an offset
    use_tilt = float(np.std(un)) > 0.06 and float(np.std(vn)) > 0.06    # enough spread to see a tilt
    cols = []
    if use_scale:
        cols.append(w_ref / wbar - 1.0)
    if use_tilt:
        cols += [un, vn]
    keep = np.ones(len(y), bool)
    e0, beta, mad = 0.0, np.zeros(len(cols)), 0.0
    X = np.stack(cols, 1) if cols else np.zeros((len(y), 0))
    for _ in range(4):
        if keep.sum() < min_samples:
            return None
        if cols:
            # On a table seen obliquely the depth is itself a ramp across the image: scale and tilt are then
            # almost the same column, and plain least squares trades one against the other with huge opposite
            # values that cancel on the table and throw off whatever stands on it. The columns are brought
            # to unit variance and a small ridge removes exactly those undetermined combinations; a
            # direction the data does determine is shrunk by `ridge` (2 %) at most.
            mu, sd = X[keep].mean(0), X[keep].std(0) + 1e-12
            Z = (X[keep] - mu) / sd
            ym = float(y[keep].mean())
            C = Z.T @ Z / len(Z)
            g = Z.T @ (y[keep] - ym) / len(Z)
            beta = np.linalg.solve(C + ridge * np.eye(len(cols)), g) / sd
            e0 = ym - float(mu @ beta)
        else:
            e0 = float(np.median(y[keep]))
        r = y - e0 - X @ beta
        mad = 1.4826 * float(np.median(np.abs(r[keep] - np.median(r[keep])))) + 1e-9
        keep = np.abs(r) < 2.5 * mad
    e1 = float(beta[0]) if use_scale else 0.0
    gu, gv = (float(beta[-2]), float(beta[-1])) if use_tilt else (0.0, 0.0)
    return DepthBias(scale=1.0 + e1, offset=float((e0 - e1) * wbar), gu=gu * wbar, gv=gv * wbar,
                     samples=int(keep.sum()), residual_rel=float(mad))


def depth_bias_from_views(ref: DepthView, others: list[DepthView], max_rel: float = 0.08, min_samples: int = 1500,
                          step: int = 3) -> DepthBias | None:
    """Smooth bias of the reference depth map against the surfaces seen by already accepted views."""
    if not others:
        return None
    Tinv = invert_rigid(ref.T_obj_from_cam)
    h, w = ref.depth.shape
    K = ref.K
    U, V, WR, WT = [], [], [], []
    for o in others:
        sub = o.depth[::step, ::step]
        vs, us = np.nonzero(sub > 0)
        if len(vs) == 0:
            continue
        z = sub[vs, us].astype(np.float64)
        vs, us = vs * step, us * step
        pc = np.stack([(us - o.K[0, 2]) / o.K[0, 0] * z, (vs - o.K[1, 2]) / o.K[1, 1] * z, z], 1)
        po = pc @ o.T_obj_from_cam[:3, :3].T + o.T_obj_from_cam[:3, 3]
        q = po @ Tinv[:3, :3].T + Tinv[:3, 3]
        zq = q[:, 2]
        ok = zq > 0.03
        ui = np.round(q[ok, 0] / zq[ok] * K[0, 0] + K[0, 2]).astype(np.int64)
        vi = np.round(q[ok, 1] / zq[ok] * K[1, 1] + K[1, 2]).astype(np.int64)
        zq = zq[ok]
        inside = (ui >= 0) & (ui < w) & (vi >= 0) & (vi < h)
        ui, vi, zq = ui[inside], vi[inside], zq[inside]
        d = ref.depth[vi, ui].astype(np.float64)
        seen = d > 0
        U.append(ui[seen] / w - 0.5)
        V.append(vi[seen] / h - 0.5)
        WR.append(1.0 / d[seen])
        WT.append(1.0 / zq[seen])
    if not U:
        return None
    return _fit_depth_bias(np.concatenate(U), np.concatenate(V), np.concatenate(WR), np.concatenate(WT), max_rel, min_samples)


def depth_bias_between(target: np.ndarray, depth: np.ndarray, max_rel: float = 0.08, min_samples: int = 1500,
                       step: int = 2) -> DepthBias | None:
    """Smooth bias of `depth` against `target`, two depth maps of the SAME view (two stereo pairs)."""
    a, b = target[::step, ::step], depth[::step, ::step]
    vs, us = np.nonzero((a > 0) & (b > 0))
    if len(vs) < min_samples:
        return None
    h, w = target.shape
    return _fit_depth_bias(us * step / w - 0.5, vs * step / h - 0.5, 1.0 / b[vs, us].astype(np.float64),
                           1.0 / a[vs, us].astype(np.float64), max_rel, min_samples)
