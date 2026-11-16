#!/usr/bin/env python3
"""Train a Gaussian-splatting model of a scanned dish from a dataset made by export_splat_dataset.py.

Needs an NVIDIA GPU (Google Colab, a cloud machine, or a local card) with PyTorch and gsplat:
  pip install gsplat imageio imageio-ffmpeg
  python tools/splat_train.py --data <folder or zip> --out <folder> [--steps 7000]

Outputs in --out:
  splat.ply         the model (standard 3DGS PLY, object frame, metres, +y up), cropped to the scan box
  turntable.mp4     the model turning, rendered from viewpoints that were never photographed
  compare.jpg       held-out real photos (left) next to the model seen from the same camera (right)
  report.json       held-out PSNR inside the box, number of Gaussians, timings

Method: 3D Gaussian splatting (Kerbl et al. 2023) with the gsplat library (Apache-2.0). Cameras come
from the phone's tracking (refined by the finishing step when available) and are fine-tuned during
training. One view out of 8 is never trained on: it is used to score the result.
"""
from __future__ import annotations

import argparse
import json
import math
import time
import zipfile
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F

C_CV_FROM_GL = np.diag([1.0, -1.0, -1.0, 1.0])
SH_C0 = 0.28209479177387814


# --------------------------------------------------------------------------- data
def load_dataset(path: Path, work: Path):
    """Returns dict(images uint8 [N,H,W,3] RGB, masks bool [N,H,W], Ks [N,3,3], c2w [N,4,4] OpenCV, names, box, init)."""
    if path.is_file() and path.suffix == ".zip":
        root = work / "dataset"
        root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path) as zf:
            zf.extractall(root)
        cands = [p.parent for p in root.rglob("transforms.json")]
        if not cands:
            raise SystemExit("transforms.json not found in the zip")
        path = cands[0]
    scene = json.loads((path / "transforms.json").read_text())
    images, masks, Ks, c2ws, names = [], [], [], [], []
    for fr in scene["frames"]:
        img = cv2.imread(str(path / fr["file_path"]), cv2.IMREAD_COLOR)
        if img is None:
            continue
        h, w = img.shape[:2]
        mp = path / "masks" / (Path(fr["file_path"]).stem + ".png")
        m = cv2.imread(str(mp), cv2.IMREAD_GRAYSCALE) if mp.exists() else None
        masks.append((m > 127) if m is not None and m.shape == (h, w) else np.ones((h, w), bool))
        images.append(img[:, :, ::-1].copy())
        Ks.append(np.array([[fr["fl_x"], 0, fr["cx"]], [0, fr["fl_y"], fr["cy"]], [0, 0, 1]], np.float32))
        c2ws.append(np.array(fr["transform_matrix"], np.float64) @ C_CV_FROM_GL)   # OpenGL camera -> OpenCV camera
        names.append(Path(fr["file_path"]).stem)
    if len(images) < 8:
        raise SystemExit(f"Only {len(images)} usable images: not enough to train")
    shapes = {im.shape for im in images}
    if len(shapes) != 1:
        raise SystemExit(f"Images have different sizes: {shapes}")
    init = None
    if scene.get("ply_file_path") and (path / scene["ply_file_path"]).exists():
        init = read_point_ply(path / scene["ply_file_path"])
    box = scene.get("dishplay", {}).get("box_size_m")
    return {"images": np.stack(images), "masks": np.stack(masks), "Ks": np.stack(Ks), "c2w": np.stack(c2ws).astype(np.float32),
            "names": names, "box": box, "init": init}


def read_point_ply(path: Path):
    """Minimal reader for the binary PLY written by export_splat_dataset.py (x y z float, red green blue uchar)."""
    raw = path.read_bytes()
    end = raw.index(b"end_header\n") + len(b"end_header\n")
    head = raw[:end].decode("ascii", "replace")
    n = int(next(l.split()[-1] for l in head.splitlines() if l.startswith("element vertex")))
    dt = np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1")])
    a = np.frombuffer(raw, dt, n, end)
    return np.stack([a["x"], a["y"], a["z"]], 1).astype(np.float32), np.stack([a["r"], a["g"], a["b"]], 1).astype(np.float32) / 255.0


# --------------------------------------------------------------------------- maths
def ssim(a: torch.Tensor, b: torch.Tensor, window: int = 11, sigma: float = 1.5) -> torch.Tensor:
    """Mean structural similarity of two [B,3,H,W] images in 0..1."""
    x = torch.arange(window, dtype=a.dtype, device=a.device) - window // 2
    g = torch.exp(-(x ** 2) / (2 * sigma ** 2))
    g = (g / g.sum())[:, None] @ (g / g.sum())[None, :]
    k = g.expand(a.shape[1], 1, window, window).contiguous()
    pad = window // 2
    mu_a = F.conv2d(a, k, padding=pad, groups=a.shape[1])
    mu_b = F.conv2d(b, k, padding=pad, groups=a.shape[1])
    va = F.conv2d(a * a, k, padding=pad, groups=a.shape[1]) - mu_a ** 2
    vb = F.conv2d(b * b, k, padding=pad, groups=a.shape[1]) - mu_b ** 2
    cov = F.conv2d(a * b, k, padding=pad, groups=a.shape[1]) - mu_a * mu_b
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    return (((2 * mu_a * mu_b + c1) * (2 * cov + c2)) / ((mu_a ** 2 + mu_b ** 2 + c1) * (va + vb + c2))).mean()


def skew(v: torch.Tensor) -> torch.Tensor:
    z = torch.zeros_like(v[..., 0])
    return torch.stack([torch.stack([z, -v[..., 2], v[..., 1]], -1), torch.stack([v[..., 2], z, -v[..., 0]], -1),
                        torch.stack([-v[..., 1], v[..., 0], z], -1)], -2)


class PoseAdjust(torch.nn.Module):
    """Small learnable correction of each camera (the tracker's poses are good to about a millimetre)."""

    def __init__(self, n: int):
        super().__init__()
        self.delta = torch.nn.Parameter(torch.zeros(n, 6))

    def forward(self, c2w: torch.Tensor, idx: torch.Tensor) -> torch.Tensor:
        d = self.delta[idx]
        R = torch.linalg.matrix_exp(skew(d[:, 3:]))
        T = torch.eye(4, device=c2w.device, dtype=c2w.dtype).repeat(len(idx), 1, 1)
        T[:, :3, :3] = R
        T[:, :3, 3] = d[:, :3]
        return c2w @ T


def knn_scale(points: np.ndarray, k: int = 3) -> np.ndarray:
    try:
        from scipy.spatial import cKDTree
        d, _ = cKDTree(points).query(points, k=k + 1)
        return np.sqrt((d[:, 1:] ** 2).mean(1)).astype(np.float32)
    except ImportError:
        p = torch.from_numpy(points)
        out = []
        for i in range(0, len(p), 4096):
            d = torch.cdist(p[i:i + 4096], p)
            out.append(d.topk(k + 1, largest=False).values[:, 1:].pow(2).mean(1).sqrt())
        return torch.cat(out).numpy().astype(np.float32)


def look_at_cv(eye: np.ndarray, target: np.ndarray, up=(0.0, 1.0, 0.0)) -> np.ndarray:
    """Camera-to-world, OpenCV camera (x right, y down, z forward)."""
    z = target - eye
    z = z / np.linalg.norm(z)
    x = np.cross(z, np.asarray(up, float))
    x = x / np.linalg.norm(x)
    y = np.cross(z, x)
    T = np.eye(4)
    T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = x, y, z, eye
    return T


def turntable_cameras(c2w: np.ndarray, centre: np.ndarray, n: int = 120, elevation_deg: float = 32.0) -> np.ndarray:
    r = float(np.median(np.linalg.norm(c2w[:, :3, 3] - centre, axis=1)))
    e = math.radians(elevation_deg)
    out = []
    for i in range(n):
        a = 2 * math.pi * i / n
        eye = centre + r * np.array([math.cos(e) * math.cos(a), math.sin(e), math.cos(e) * math.sin(a)])
        out.append(look_at_cv(eye, centre))
    return np.stack(out).astype(np.float32)


# --------------------------------------------------------------------------- model
def init_params(data, n_random: int, sh_degree: int, device, seed: int = 0):
    g = np.random.default_rng(seed)
    box = data["box"] or [0.3, 0.12, 0.3]
    if data["init"] is not None and len(data["init"][0]) >= 500:
        pts, rgb = data["init"]
    else:   # no finished model: start from random points inside the scan box
        pts = (g.uniform(-0.5, 0.5, (n_random, 3)) * [box[0], box[1], box[2]] + [0, box[1] / 2, 0]).astype(np.float32)
        rgb = np.full((n_random, 3), 0.5, np.float32)
    scale = np.clip(knn_scale(pts), 1e-4, 0.02)
    n = len(pts)
    quats = np.zeros((n, 4), np.float32)
    quats[:, 0] = 1
    k = (sh_degree + 1) ** 2 - 1
    p = {
        "means": torch.from_numpy(pts),
        "scales": torch.log(torch.from_numpy(scale))[:, None].repeat(1, 3),
        "quats": torch.from_numpy(quats),
        "opacities": torch.logit(torch.full((n,), 0.1)),
        "sh0": ((torch.from_numpy(rgb) - 0.5) / SH_C0)[:, None, :],
        "shN": torch.zeros((n, k, 3)),
    }
    return torch.nn.ParameterDict({k_: torch.nn.Parameter(v.float().to(device)) for k_, v in p.items()})


def render(params, viewmats, Ks, w, h, sh_degree, rasterize, bg=None, **kw):
    colors = torch.cat([params["sh0"], params["shN"]], 1)
    return rasterize(params["means"], F.normalize(params["quats"], dim=-1), torch.exp(params["scales"]),
                     torch.sigmoid(params["opacities"]), colors, viewmats, Ks, w, h, sh_degree=sh_degree,
                     packed=False, backgrounds=bg, near_plane=0.02, far_plane=20.0, **kw)


def train(data, out: Path, steps: int = 7000, sh_degree: int = 3, pose_opt: bool = True, test_every: int = 8,
          device: str = "cuda", rasterize=None, log_every: int = 250, seed: int = 0, max_gaussians: int = 1_500_000) -> dict:
    from gsplat.strategy import DefaultStrategy
    if rasterize is None:
        from gsplat import rasterization as rasterize
    torch.manual_seed(seed)
    out.mkdir(parents=True, exist_ok=True)
    n, h, w = data["images"].shape[:3]
    test_idx = np.arange(n)[test_every - 1::test_every] if test_every > 0 else np.zeros(0, int)
    train_idx = np.setdiff1d(np.arange(n), test_idx)
    c2w = torch.from_numpy(data["c2w"]).to(device)
    Ks = torch.from_numpy(data["Ks"]).to(device)
    centres = data["c2w"][:, :3, 3]
    scene_scale = float(np.linalg.norm(centres - centres.mean(0), axis=1).max()) * 1.1
    params = init_params(data, 60_000, sh_degree, device, seed)
    lrs = {"means": 1.6e-4 * scene_scale, "scales": 5e-3, "quats": 1e-3, "opacities": 5e-2, "sh0": 2.5e-3, "shN": 2.5e-3 / 20}
    optimizers = {k: torch.optim.Adam([{"params": params[k], "lr": lr, "name": k}], eps=1e-15) for k, lr in lrs.items()}
    means_sched = torch.optim.lr_scheduler.ExponentialLR(optimizers["means"], gamma=0.01 ** (1.0 / steps))
    # Small object, close cameras: stop growing a little before the end so the last steps only refine.
    strategy = DefaultStrategy(refine_start_iter=300, refine_stop_iter=int(steps * 0.8), reset_every=3000,
                               refine_every=100, pause_refine_after_reset=len(train_idx), verbose=False)
    strategy.check_sanity(params, optimizers)
    state = strategy.initialize_state(scene_scale=scene_scale)
    poses = PoseAdjust(n).to(device) if pose_opt else None
    pose_optim = torch.optim.Adam(poses.parameters(), lr=1e-5, weight_decay=1e-6) if pose_opt else None
    t0 = time.time()
    order = np.zeros(0, int)
    rng = np.random.default_rng(seed)
    log = []
    for step in range(steps):
        if len(order) == 0:
            order = rng.permutation(train_idx)
        i, order = int(order[0]), order[1:]
        gt = torch.from_numpy(data["images"][i]).to(device).float() / 255.0
        mask = torch.from_numpy(data["masks"][i]).to(device)[..., None].float()
        idx = torch.tensor([i], device=device)
        cam = poses(c2w[idx], idx) if pose_opt else c2w[idx]
        sh_now = min(step // 1000, sh_degree)
        bg = torch.rand(1, 3, device=device)   # random background: empty space cannot hide behind a fixed colour
        colors, alphas, info = render(params, torch.linalg.inv(cam), Ks[idx], w, h, sh_now, rasterize, bg=bg)
        strategy.step_pre_backward(params, optimizers, state, step, info)
        pred = colors[0] * mask + bg[0] * (1 - mask)
        target = gt * mask + bg[0] * (1 - mask)
        l1 = (pred - target).abs().mean()
        s = ssim(pred.permute(2, 0, 1)[None], target.permute(2, 0, 1)[None])
        loss = 0.8 * l1 + 0.2 * (1 - s)
        loss.backward()
        strategy.step_post_backward(params, optimizers, state, step, info, packed=False)
        for o in optimizers.values():
            o.step()
            o.zero_grad(set_to_none=True)
        if pose_opt:
            pose_optim.step()
            pose_optim.zero_grad(set_to_none=True)
        means_sched.step()
        if len(params["means"]) > max_gaussians:   # memory guard for small cards
            strategy.refine_stop_iter = step
        if step % log_every == 0 or step == steps - 1:
            rec = {"step": step, "loss": float(loss.detach()), "gaussians": int(len(params["means"])), "seconds": round(time.time() - t0, 1)}
            log.append(rec)
            print(json.dumps(rec), flush=True)
    train_s = time.time() - t0
    report = {"steps": steps, "train_seconds": round(train_s, 1), "images": int(n), "train_views": int(len(train_idx)),
              "test_views": int(len(test_idx)), "width": int(w), "height": int(h), "gaussians": int(len(params["means"])),
              "pose_opt": pose_opt, "log": log}
    with torch.no_grad():
        report.update(evaluate(data, params, c2w, Ks, poses, test_idx, sh_degree, rasterize, out, device))
        report.update(export(data, params, sh_degree, rasterize, out, device))
    (out / "report.json").write_text(json.dumps(report, indent=1))
    return report


def evaluate(data, params, c2w, Ks, poses, test_idx, sh_degree, rasterize, out: Path, device) -> dict:
    """Held-out views: PSNR inside the box mask, and a picture real | model for the first four."""
    n, h, w = data["images"].shape[:3]
    psnrs, tiles = [], []
    black = torch.zeros(1, 3, device=device)
    for j in test_idx:
        idx = torch.tensor([int(j)], device=device)
        colors, _, _ = render(params, torch.linalg.inv(c2w[idx]), Ks[idx], w, h, sh_degree, rasterize, bg=black)
        pred = colors[0].clamp(0, 1)
        gt = torch.from_numpy(data["images"][j]).to(device).float() / 255.0
        m = torch.from_numpy(data["masks"][j]).to(device)
        mse = ((pred - gt) ** 2)[m].mean()
        psnrs.append(float(-10 * torch.log10(mse.clamp_min(1e-10))))
        if len(tiles) < 4:
            a = (gt * m[..., None]).cpu().numpy()
            b = (pred * m[..., None]).cpu().numpy()
            tiles.append(np.concatenate([a, b], 1))
    res = {"heldout_psnr_db": round(float(np.mean(psnrs)), 2) if psnrs else None,
           "heldout_psnr_min_db": round(float(np.min(psnrs)), 2) if psnrs else None}
    if tiles:
        sheet = (np.concatenate(tiles, 0) * 255).astype(np.uint8)[:, :, ::-1]
        if sheet.shape[1] > 1600:
            f = 1600 / sheet.shape[1]
            sheet = cv2.resize(sheet, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(out / "compare.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return res


def box_keep(means: torch.Tensor, box, margin: float = 0.01) -> torch.Tensor:
    if not box:
        return torch.ones(len(means), dtype=torch.bool, device=means.device)
    return ((means[:, 0].abs() <= box[0] / 2 + margin) & (means[:, 2].abs() <= box[2] / 2 + margin)
            & (means[:, 1] >= -margin) & (means[:, 1] <= box[1] + margin))


def export(data, params, sh_degree, rasterize, out: Path, device) -> dict:
    from gsplat import export_splats
    keep = box_keep(params["means"], data["box"])
    p = {k: v[keep] for k, v in params.items()}
    export_splats(p["means"], p["scales"], p["quats"], p["opacities"], p["sh0"], p["shN"], format="ply", save_to=str(out / "splat.ply"))
    box = data["box"] or [0.3, 0.12, 0.3]
    centre = np.array([0.0, box[1] * 0.45, 0.0])
    cams = turntable_cameras(data["c2w"], centre)
    n, h, w = data["images"].shape[:3]
    s = 720 / max(h, w) if max(h, w) > 720 else 1.0
    tw, th = int(round(w * s)) // 2 * 2, int(round(h * s)) // 2 * 2
    K = torch.from_numpy(data["Ks"][0].copy()).to(device)
    K[:2] *= s
    frames = []
    white = torch.full((1, 3), 0.08, device=device)
    for T in cams:
        vm = torch.linalg.inv(torch.from_numpy(T).to(device))[None]
        colors, _, _ = render(p, vm, K[None], tw, th, sh_degree, rasterize, bg=white)
        frames.append((colors[0].clamp(0, 1) * 255).byte().cpu().numpy())
    video = None
    try:
        import imageio.v2 as imageio
        with imageio.get_writer(str(out / "turntable.mp4"), fps=30, codec="libx264", quality=8, macro_block_size=None) as wr:
            for f in frames:
                wr.append_data(f)
        video = "turntable.mp4"
    except Exception as exc:   # no ffmpeg: keep still pictures instead of failing the whole run
        print("video not written:", repr(exc))
    cv2.imwrite(str(out / "preview.jpg"), np.concatenate([frames[k] for k in (0, 30, 60, 90)], 1)[:, :, ::-1],
                [cv2.IMWRITE_JPEG_QUALITY, 90])
    return {"exported_gaussians": int(keep.sum()), "video": video}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="dataset folder or zip from export_splat_dataset.py")
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=7000)
    ap.add_argument("--no-pose-opt", action="store_true")
    ap.add_argument("--test-every", type=int, default=8)
    a = ap.parse_args()
    if not torch.cuda.is_available():
        raise SystemExit("No NVIDIA GPU visible to PyTorch. In Colab: Runtime > Change runtime type > T4 GPU.")
    out = Path(a.out)
    data = load_dataset(Path(a.data), out)
    print(f"{len(data['images'])} images {data['images'].shape[2]}x{data['images'].shape[1]}, "
          f"init points: {0 if data['init'] is None else len(data['init'][0])}", flush=True)
    rep = train(data, out, steps=a.steps, pose_opt=not a.no_pose_opt, test_every=a.test_every)
    print(json.dumps({k: v for k, v in rep.items() if k != "log"}, indent=1))


if __name__ == "__main__":
    main()
