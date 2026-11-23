#!/usr/bin/env python3
"""Photo express: ONE photograph of a dish -> a complete 3D model (GLB), by generative AI. A trial, kept apart
from the calculator: nothing here is used by the scan.

  python tools/photo_express.py photo.jpg --triposr <folder of the TripoSR code> --out resultat
  python tools/photo_express.py --self-test          (checks the mesh extraction replacement, no model needed)

The model is TripoSR (Tripo AI and Stability AI, 2024). What was read on the official sources (23 Nov 2026):
  code and weights          MIT             github.com/VAST-AI-Research/TripoSR, huggingface.co/stabilityai/TripoSR
  image encoder             Apache-2.0      DINO ViT-B/16 (only its configuration is fetched; weights are in TripoSR's file)
  background removal        MIT             rembg, with the U2-Net weights (Apache-2.0), asked for BY NAME: since
                                            2025 rembg's default model is BRIA RMBG, whose licence is not permissive
Two entries of TripoSR's own requirements are deliberately NOT used:
  torchmcubes               MPL-2.0         replaced below by scikit-image (BSD-3-Clause)
  imageio-ffmpeg            ships a GPL build of FFmpeg; only needed for a video this program does not make
Its texture baker (xatlas + moderngl, both MIT) is not used either: it needs an OpenGL context that a notebook
machine does not reliably have. The model keeps its colours per vertex, which a GLB can carry.

What the model does and does not do: the sides the camera did not see are INVENTED so that the object looks
plausible; nothing is measured, and the size is arbitrary. The scan measures; this guesses.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import types
from pathlib import Path

import numpy as np

TRIPOSR_COMMIT = "107cefdc244c39106fa830359024f6a2f1c78871"     # github.com/VAST-AI-Research/TripoSR
WEIGHTS_REPO = "stabilityai/TripoSR"
WEIGHTS_REVISION = "5b521936b01fbe1890f6f9baed0254ab6351c04a"   # huggingface.co/stabilityai/TripoSR
DENSITY_THRESHOLD = 25.0                                        # TripoSR's own default for the surface
CUTOUT_MODEL = "u2net"                                          # Apache-2.0 weights; never rembg's default (see above)
PREVIEW_GRID = 128                                              # a light copy of the model for the viewer in the page


# ----------------------------------------------------------------------------- mesh extraction replacement
def surface_in_index_order(volume: np.ndarray, level: float):
    """Marching cubes with scikit-image. Vertices are returned in the order of the array's axes: a vertex
    (a, b, c) lies at volume[a, b, c]. Faces index the vertices."""
    from skimage import measure
    verts, faces, _, _ = measure.marching_cubes(np.ascontiguousarray(volume, dtype=np.float32), level=float(level))
    return verts.astype(np.float32), faces.astype(np.int64)


def install_marching_cubes_replacement() -> None:
    """TripoSR imports `marching_cubes` from the package torchmcubes (MPL-2.0, compiled at install). This puts a
    module of the same name in its place, backed by scikit-image. torchmcubes returns each vertex with its
    coordinates in the REVERSE order of the array's axes (TripoSR then reorders them with [2, 1, 0]); the
    replacement does the same so TripoSR's code runs unchanged."""
    import torch

    def marching_cubes(volume, level):
        v, f = surface_in_index_order(volume.detach().cpu().numpy(), level)
        return torch.from_numpy(np.ascontiguousarray(v[:, ::-1])), torch.from_numpy(f)

    module = types.ModuleType("torchmcubes")
    module.marching_cubes = marching_cubes
    sys.modules["torchmcubes"] = module


def self_test() -> None:
    """A box that is not centred and has three different sides: any mix-up of the axes shows."""
    vol = np.zeros((40, 48, 56), np.float32)
    vol[5:15, 10:30, 20:50] = 1.0
    v, f = surface_in_index_order(vol, 0.5)
    lo, hi = v.min(0), v.max(0)
    assert np.allclose(lo, [4.5, 9.5, 19.5], atol=0.01) and np.allclose(hi, [14.5, 29.5, 49.5], atol=0.01), (lo, hi)
    assert len(f) > 100 and f.max() < len(v)
    import torch
    install_marching_cubes_replacement()
    from torchmcubes import marching_cubes
    tv, tf = marching_cubes(torch.from_numpy(vol), 0.5)
    back = tv[..., [2, 1, 0]].numpy()      # what TripoSR does with the result
    assert np.allclose(back, v), "the replacement must give TripoSR the axes it expects"
    assert tf.dtype == torch.int64
    print("auto-test : extraction de la surface correcte (axes vérifiés sur une boîte de synthèse)")


# ----------------------------------------------------------------------------- picture in, picture out
def open_photo(path: Path):
    from PIL import Image, ImageOps
    try:
        im = Image.open(path)
        im = ImageOps.exif_transpose(im)   # iPhone photographs carry their rotation apart from the pixels
        im.load()
    except Exception as exc:
        raise SystemExit(f"Photo illisible ({path.name}) : {exc}. Utilisez un fichier JPEG ou PNG "
                         "(iPhone : Réglages > Appareil photo > Formats > « Le plus compatible », ou envoyez une capture d'écran).")
    if max(im.size) > 1600:
        im.thumbnail((1600, 1600))
    return im.convert("RGBA") if im.mode == "RGBA" else im.convert("RGB")


def views_sheet(V: np.ndarray, C: np.ndarray, N: np.ndarray, size: int = 360, bg: int = 21) -> np.ndarray:
    """Five small pictures of the model (four sides and the top), drawn point by point with no 3D library:
    enough to see the shape and the colours, and to send as one image. Only points whose surface faces the
    viewer are drawn, each as a square as wide as the spacing between points, nearest last."""
    V = V - (V.max(0) + V.min(0)) / 2
    scale = (size * 0.42) / max(1e-9, np.abs(V).max())
    r = int(np.clip(np.ceil(0.6 * size * 0.84 / max(1.0, np.sqrt(len(V) / 2))), 1, 6))
    offsets = [(dx, dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1)]
    tiles = []
    for az, el in ((0, 20), (90, 20), (180, 20), (270, 20), (0, 89)):
        a, e = np.radians(az), np.radians(el)
        Ry = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
        Rx = np.array([[1, 0, 0], [0, np.cos(e), -np.sin(e)], [0, np.sin(e), np.cos(e)]])
        R = Rx @ Ry
        P, Nz = V @ R.T, (N @ R.T)[:, 2]
        front = Nz > 0.05                                # the viewer looks down -z: these surfaces face it
        P, col = P[front], C[front]
        order = np.argsort(P[:, 2])                      # far first: the nearest point is written last and stays
        px = np.clip((P[order, 0] * scale + size / 2).astype(int), r, size - 1 - r)
        py = np.clip((size / 2 - P[order, 1] * scale).astype(int), r, size - 1 - r)
        tile = np.full((size, size, 3), bg, np.uint8)
        col = col[order]
        for dx, dy in offsets:
            tile[py + dy, px + dx] = col
        tiles.append(tile)
    return np.concatenate(tiles, axis=1)


def run(photo: Path, triposr: Path, out: Path, device: str | None, resolution: int, foreground: float) -> dict:
    import torch
    from PIL import Image
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    if not (triposr / "tsr" / "system.py").exists():
        raise SystemExit(f"Code de TripoSR introuvable dans {triposr} (dossier attendu : celui qui contient « tsr »).")
    install_marching_cubes_replacement()
    sys.path.insert(0, str(triposr))
    import rembg
    from huggingface_hub import snapshot_download
    from tsr.system import TSR
    from tsr.utils import remove_background, resize_foreground, to_gradio_3d_orientation

    device = device or ("cuda:0" if torch.cuda.is_available() else "cpu")
    if device == "cpu":
        print("Pas de carte graphique : le calcul se fait sur le processeur (plusieurs minutes).", flush=True)

    # 1. The dish alone, on the grey ground the model was trained with. This picture is what the model sees.
    im = open_photo(photo)
    cut = remove_background(im, rembg.new_session(CUTOUT_MODEL))
    alpha = np.asarray(cut)[..., 3]
    share = float((alpha > 127).mean())
    if share < 0.01:
        raise SystemExit("Le détourage n'a trouvé aucun plat dans la photo. Reprenez-la : plat entier, bien éclairé, fond simple.")
    cut = resize_foreground(cut, foreground)
    a = np.asarray(cut).astype(np.float32) / 255.0
    seen = Image.fromarray(((a[..., :3] * a[..., 3:4] + (1 - a[..., 3:4]) * 0.5) * 255).astype(np.uint8))
    seen.save(out / "decoupe.png")
    t_cut = time.time()
    print(f"1/3  plat détouré ({share:.0%} de la photo) -> decoupe.png", flush=True)

    # 2. The model. Weights at a fixed revision; checked to be plain tensors before TripoSR loads them.
    folder = Path(snapshot_download(WEIGHTS_REPO, revision=WEIGHTS_REVISION, allow_patterns=["config.yaml", "model.ckpt"]))
    try:
        torch.load(folder / "model.ckpt", map_location="cpu", weights_only=True)
    except Exception as exc:
        raise SystemExit(f"Le fichier du modèle n'est pas celui attendu (il devrait ne contenir que des nombres) : {exc!r}. Rien n'a été exécuté.")
    model = TSR.from_pretrained(str(folder), config_name="config.yaml", weight_name="model.ckpt")
    model.renderer.set_chunk_size(8192)
    model.to(device)
    t_load = time.time()
    with torch.no_grad():
        codes = model([seen], device=device)
    t_model = time.time()
    print("2/3  forme et couleurs imaginées par le modèle", flush=True)

    # 3. The surface, upright (y up, as GLB wants), facing outwards.
    mesh = model.extract_mesh(codes, True, resolution=resolution, threshold=DENSITY_THRESHOLD)[0]
    if len(mesh.faces) == 0:
        raise SystemExit("Le modèle n'a produit aucune surface pour cette photo. Essayez une photo plus nette, plat entier dans l'image.")
    if mesh.volume < 0:
        mesh.invert()
    mesh = to_gradio_3d_orientation(mesh)
    mesh.export(out / "plat.glb")
    light = model.extract_mesh(codes, True, resolution=PREVIEW_GRID, threshold=DENSITY_THRESHOLD)[0]
    if len(light.faces):
        if light.volume < 0:
            light.invert()
        to_gradio_3d_orientation(light).export(out / "plat_apercu.glb")
    V, C = np.asarray(mesh.vertices, np.float64), np.asarray(mesh.visual.vertex_colors)[:, :3].astype(np.uint8)
    sheet = views_sheet(V, C, np.asarray(mesh.vertex_normals, np.float64))
    left = np.asarray(seen.resize((sheet.shape[0], sheet.shape[0])))
    Image.fromarray(np.concatenate([left, sheet], axis=1)).save(out / "apercu.jpg", quality=90)
    t_end = time.time()
    report = {
        "photo": photo.name, "device": device, "vertices": int(len(mesh.vertices)), "triangles": int(len(mesh.faces)),
        "watertight": bool(mesh.is_watertight), "size": [round(float(x), 4) for x in mesh.extents],
        "foreground_share_of_photo": round(share, 3), "grid": resolution,
        "seconds": {"cut_out": round(t_cut - t0, 1), "load_model": round(t_load - t_cut, 1),
                    "model": round(t_model - t_load, 1), "surface_and_files": round(t_end - t_model, 1), "total": round(t_end - t0, 1)},
        "model": {"name": "TripoSR", "code_commit": TRIPOSR_COMMIT, "weights": WEIGHTS_REPO, "weights_revision": WEIGHTS_REVISION},
        "versions": {"torch": torch.__version__, "numpy": np.__version__},
        "cut_out_model": CUTOUT_MODEL,
        "files": ["decoupe.png", "plat.glb", "plat_apercu.glb", "apercu.jpg"],
    }
    (out / "report.json").write_text(json.dumps(report, indent=1))
    print(f"3/3  modèle écrit : plat.glb ({report['triangles']:,} triangles), apercu.jpg — {report['seconds']['total']} s au total".replace(",", " "), flush=True)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="One photograph of a dish -> a 3D model (trial, generative AI)")
    ap.add_argument("photo", nargs="?", type=Path)
    ap.add_argument("--triposr", type=Path, default=Path("TripoSR"), help="folder of the TripoSR code (the one that contains tsr/)")
    ap.add_argument("--out", type=Path, default=Path("resultat"))
    ap.add_argument("--device", default=None, help="cuda:0 or cpu (default: the graphics card when there is one)")
    ap.add_argument("--grid", type=int, default=256, help="resolution of the surface extraction (256 = TripoSR's default)")
    ap.add_argument("--foreground", type=float, default=0.85, help="share of the picture the dish fills (TripoSR's default)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        self_test()
        return
    if a.photo is None:
        ap.error("a photograph is required")
    run(a.photo, a.triposr, a.out, a.device, a.grid, a.foreground)


if __name__ == "__main__":
    main()
