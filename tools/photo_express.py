#!/usr/bin/env python3
"""Photo express: ONE photograph of a dish -> a complete 3D model (GLB), by generative AI. A trial, kept apart
from the calculator: nothing here is used by the scan.

  python tools/photo_express.py photo.jpg --triposr <folder of the TripoSR code> --out resultat
  python tools/photo_express.py --self-test          (checks the program's own parts, no model needed)

The model is TripoSR (Tripo AI and Stability AI, 2024). What was read on the official sources (23 Nov 2026):
  code and weights          MIT             github.com/VAST-AI-Research/TripoSR, huggingface.co/stabilityai/TripoSR
  image encoder             Apache-2.0      DINO ViT-B/16 (only its configuration is fetched; weights are in TripoSR's file)
  background removal        MIT             rembg, with the U2-Net weights (Apache-2.0), asked for BY NAME: recent
                                            versions of rembg default to BRIA RMBG, whose licence is not permissive
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
import struct
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
VIEW_NAMES = ("photo", "profil", "dos", "profil", "dessus")     # the five small pictures, in order

# TripoSR's file names the image encoder's parameters as transformers did until 5.8. From 5.9 on the same
# parameters have other names, and TripoSR loads its file strictly: without this the model does not load.
ENCODER = "image_tokenizer.model."
ENCODER_RENAMES = (
    (".encoder.layer.", ".layers."),
    (".attention.attention.query.", ".attention.q_proj."),
    (".attention.attention.key.", ".attention.k_proj."),
    (".attention.attention.value.", ".attention.v_proj."),
    (".attention.output.dense.", ".attention.o_proj."),
    (".intermediate.dense.", ".mlp.fc1."),
    (".output.dense.", ".mlp.fc2."),
)


def names_for_installed_encoder(state: dict, wanted) -> dict:
    """The weights under the names the installed transformers expects: unchanged when they already match,
    otherwise the encoder's parameters renamed from the older scheme to the newer one."""
    wanted = set(wanted)
    if set(state) == wanted:
        return state
    out = {}
    for name, value in state.items():
        if name.startswith(ENCODER):
            for old, new in ENCODER_RENAMES:
                name = name.replace(old, new)
        out[name] = value
    return out


# ----------------------------------------------------------------------------- mesh extraction replacement
def surface_in_index_order(volume: np.ndarray, level: float):
    """Marching cubes with scikit-image for a volume that is HIGHER inside the object (what TripoSR passes).
    Vertices come in the order of the array's axes: a vertex (a, b, c) lies at volume[a, b, c]. Faces index
    the vertices and are wound so that they face outwards. No surface: two empty arrays."""
    from skimage import measure
    try:
        verts, faces, _, _ = measure.marching_cubes(np.ascontiguousarray(volume, dtype=np.float32), level=float(level))
    except (ValueError, RuntimeError):       # level outside the data, or nothing crosses it
        return np.zeros((0, 3), np.float32), np.zeros((0, 3), np.int64)
    return verts.astype(np.float32), np.ascontiguousarray(faces[:, ::-1]).astype(np.int64)


def signed_volume(V: np.ndarray, F: np.ndarray) -> float:
    """Positive when the faces of a closed surface look outwards."""
    a, b, c = (np.asarray(V, np.float64)[F[:, k]] for k in range(3))
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


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


# ----------------------------------------------------------------------------- the file of the model
def upright(P: np.ndarray) -> np.ndarray:
    """TripoSR's frame (z up, the photographed side towards +x) -> the frame of GLB files (y up, front towards
    +z): (x, y, z) becomes (y, z, x). A rotation, so the faces keep their orientation."""
    return np.ascontiguousarray(np.asarray(P)[:, [1, 2, 0]])


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    c = np.asarray(c, np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def write_glb(path: Path, V: np.ndarray, F: np.ndarray, N: np.ndarray, C: np.ndarray) -> None:
    """A GLB with colours per vertex. C holds the colours as pictures store them (sRGB, 0-255); a GLB wants
    them linear. A material is written (not metallic, matte): without one, viewers fall back to a metallic
    default that washes the colours out. Both sides of each face are drawn."""
    V = np.asarray(V, np.float32)
    N = np.asarray(N, np.float64)
    length = np.linalg.norm(N, axis=1, keepdims=True)
    N = np.where(length > 1e-12, N / np.maximum(length, 1e-12), [[0.0, 1.0, 0.0]]).astype(np.float32)
    colours = np.empty((len(V), 4), np.uint16)
    colours[:, :3] = np.round(srgb_to_linear(np.asarray(C)[:, :3] / 255.0) * 65535.0)
    colours[:, 3] = 65535
    parts = [V.tobytes(), N.tobytes(), colours.tobytes(), np.asarray(F, np.uint32).tobytes()]
    views, blob = [], b""
    for k, part in enumerate(parts):
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(part), "target": 34963 if k == 3 else 34962})
        blob += part + b"\0" * (-len(part) % 4)
    doc = {
        "asset": {"version": "2.0", "generator": "DishPlay photo express"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "plat"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "COLOR_0": 2}, "indices": 3, "material": 0, "mode": 4}]}],
        "materials": [{"name": "couleurs du plat", "doubleSided": True,
                       "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0, "roughnessFactor": 1}}],
        "buffers": [{"byteLength": len(blob)}], "bufferViews": views,
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(V), "type": "VEC3",
             "min": [float(x) for x in V.min(0)], "max": [float(x) for x in V.max(0)]},
            {"bufferView": 1, "componentType": 5126, "count": len(V), "type": "VEC3"},
            {"bufferView": 2, "componentType": 5123, "normalized": True, "count": len(V), "type": "VEC4"},
            {"bufferView": 3, "componentType": 5125, "count": int(np.asarray(F).size), "type": "SCALAR"},
        ],
    }
    text = json.dumps(doc, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    total = 12 + 8 + len(text) + 8 + len(blob)
    Path(path).write_bytes(struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(text), b"JSON") + text
                           + struct.pack("<I4s", len(blob), b"BIN\0") + blob)


def self_test() -> None:
    """The program's own parts, on shapes whose answer is known. A box that is not centred and has three
    different sides: any mix-up of the axes shows."""
    vol = np.zeros((40, 48, 56), np.float32)
    vol[5:15, 10:30, 20:50] = 1.0
    v, f = surface_in_index_order(vol, 0.5)
    lo, hi = v.min(0), v.max(0)
    assert np.allclose(lo, [4.5, 9.5, 19.5], atol=0.01) and np.allclose(hi, [14.5, 29.5, 49.5], atol=0.01), (lo, hi)
    assert len(f) > 100 and f.max() < len(v)
    assert 5000 < signed_volume(v, f) < 6100, "faces must look outwards (the box holds 10 x 20 x 30 cells)"
    assert len(surface_in_index_order(np.zeros((8, 8, 8), np.float32), 0.5)[1]) == 0, "no surface must give an empty result, not an error"
    import torch
    install_marching_cubes_replacement()
    from torchmcubes import marching_cubes
    tv, tf = marching_cubes(torch.from_numpy(vol), 0.5)
    back = tv[..., [2, 1, 0]].numpy()      # what TripoSR does with the result
    assert np.allclose(back, v), "the replacement must give TripoSR the axes it expects"
    assert tf.dtype == torch.int64 and signed_volume(back, tf.numpy()) > 0
    old = {ENCODER + "encoder.layer.0.attention.attention.query.weight": 1, ENCODER + "encoder.layer.0.output.dense.bias": 2, "decoder.x": 3}
    new = {ENCODER + "layers.0.attention.q_proj.weight", ENCODER + "layers.0.mlp.fc2.bias", "decoder.x"}
    assert set(names_for_installed_encoder(old, new)) == new and names_for_installed_encoder(old, set(old)) is old
    print("auto-test : extraction de la surface, orientation des faces et noms du modèle corrects")


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
    """Five small pictures of the model in the GLB frame (y up, front towards +z): the side of the photograph,
    a profile, the back, the other profile, and the top. Drawn point by point with no 3D library: enough to see
    the shape and the colours, and to send as one image. Only points whose surface faces the viewer are drawn,
    each as a square as wide as the spacing between points, nearest last."""
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


def name_the_views(sheet: np.ndarray, size: int) -> np.ndarray:
    """Write under each small picture what it shows (words without accents: the built-in font has none)."""
    from PIL import Image, ImageDraw
    im = Image.fromarray(sheet)
    draw = ImageDraw.Draw(im)
    for k, word in enumerate(VIEW_NAMES):
        draw.text((k * size + 8, sheet.shape[0] - 18), word, fill=(235, 235, 235))
    return np.asarray(im)


def load_model(folder: Path, device: str):
    """TripoSR with its weights. Not TSR.from_pretrained: that loads the file strictly under the parameter names
    of the transformers version TripoSR was written for (see ENCODER_RENAMES)."""
    import torch
    import transformers
    from omegaconf import OmegaConf
    from tsr.system import TSR
    cfg = OmegaConf.load(folder / "config.yaml")
    OmegaConf.resolve(cfg)
    model = TSR(cfg)
    try:    # plain tensors only: nothing in the file is executed
        state = torch.load(folder / "model.ckpt", map_location="cpu", weights_only=True)
    except Exception as exc:
        raise SystemExit(f"Le fichier du modèle n'est pas celui attendu (il devrait ne contenir que des nombres) : {exc!r}. Rien n'a été exécuté.")
    wanted = set(model.state_dict())
    state = names_for_installed_encoder(state, wanted)
    missing, extra = sorted(wanted - set(state)), sorted(set(state) - wanted)
    if missing or extra:
        raise SystemExit("Le modèle ne se charge pas avec la version de la bibliothèque « transformers » de cette machine "
                         f"({transformers.__version__}) : {len(missing)} paramètres manquent, {len(extra)} sont en trop "
                         f"(par exemple {(missing or extra)[0]}). Envoyez une capture de ce message.")
    model.load_state_dict(state)
    model.renderer.set_chunk_size(8192)
    model.to(device)
    return model


def surface(model, codes, grid: int):
    """(vertices, faces, normals, colours) of the model's surface in the GLB frame, or None when there is none."""
    mesh = model.extract_mesh(codes, True, resolution=grid, threshold=DENSITY_THRESHOLD)[0]
    if len(mesh.faces) == 0:
        return None
    return (upright(mesh.vertices), np.asarray(mesh.faces), upright(mesh.vertex_normals),
            np.asarray(mesh.visual.vertex_colors)[:, :3].astype(np.uint8))


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
    import transformers
    from huggingface_hub import snapshot_download
    from tsr.utils import remove_background, resize_foreground

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

    # 2. The model, its weights at a fixed revision.
    folder = Path(snapshot_download(WEIGHTS_REPO, revision=WEIGHTS_REVISION, allow_patterns=["config.yaml", "model.ckpt"]))
    model = load_model(folder, device)
    t_load = time.time()
    with torch.no_grad():
        codes = model([seen], device=device)
    t_model = time.time()
    print("2/3  forme et couleurs imaginées par le modèle", flush=True)

    # 3. The surface, as a file and as a picture.
    full = surface(model, codes, resolution)
    if full is None:
        raise SystemExit("Le modèle n'a produit aucune surface pour cette photo. Essayez une photo plus nette, plat entier dans l'image.")
    V, F, N, C = full
    write_glb(out / "plat.glb", V, F, N, C)
    files = ["decoupe.png", "plat.glb"]
    light = surface(model, codes, PREVIEW_GRID)
    if light is not None:
        write_glb(out / "plat_apercu.glb", *light)
        files.append("plat_apercu.glb")
    size = 360
    sheet = name_the_views(views_sheet(V.astype(np.float64), C, N.astype(np.float64), size), size)
    left = np.asarray(seen.resize((size, size)))
    Image.fromarray(np.concatenate([left, sheet], axis=1)).save(out / "apercu.jpg", quality=90)
    files.append("apercu.jpg")
    t_end = time.time()
    report = {
        "photo": photo.name, "device": device, "vertices": int(len(V)), "triangles": int(len(F)),
        "size": [round(float(x), 4) for x in (V.max(0) - V.min(0))],
        "foreground_share_of_photo": round(share, 3), "grid": resolution,
        "seconds": {"cut_out": round(t_cut - t0, 1), "load_model": round(t_load - t_cut, 1),
                    "model": round(t_model - t_load, 1), "surface_and_files": round(t_end - t_model, 1), "total": round(t_end - t0, 1)},
        "model": {"name": "TripoSR", "code_commit": TRIPOSR_COMMIT, "weights": WEIGHTS_REPO, "weights_revision": WEIGHTS_REVISION},
        "versions": {"torch": torch.__version__, "transformers": transformers.__version__, "numpy": np.__version__},
        "cut_out_model": CUTOUT_MODEL, "files": files,
    }
    (out / "report.json").write_text(json.dumps(report, indent=1))
    triangles = f"{report['triangles']:,}".replace(",", " ")
    print(f"3/3  modèle écrit : plat.glb ({triangles} triangles) et apercu.jpg, en {report['seconds']['total']} s", flush=True)
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
