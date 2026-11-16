"""Exports: PLY point cloud, PLY mesh, GLB (vertex colours or embedded texture)."""
from __future__ import annotations

import json
import struct
from pathlib import Path

import cv2
import numpy as np


def write_points_ply(path: Path, xyz: np.ndarray, rgb: np.ndarray, cls: np.ndarray, nframes: np.ndarray):
    n = len(xyz)
    header = ("ply\nformat binary_little_endian 1.0\n"
              "comment DishPlay Scan measured points, object frame, metres, y up\n"
              "comment provenance: 0 measured(>=2 views) 4 provisional(single view)\n"
              f"element vertex {n}\nproperty float x\nproperty float y\nproperty float z\n"
              "property uchar red\nproperty uchar green\nproperty uchar blue\n"
              "property uchar provenance\nproperty ushort views\nend_header\n").encode()
    dt = np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1"), ("c", "u1"), ("v", "<u2")])
    a = np.zeros(n, dt)
    a["x"], a["y"], a["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    a["r"], a["g"], a["b"] = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    a["c"] = cls
    a["v"] = np.minimum(nframes, 65535)
    Path(path).write_bytes(header + a.tobytes())


def write_mesh_ply(path: Path, V, colors, normals, classes, T):
    nv, nt = len(V), len(T)
    header = ("ply\nformat binary_little_endian 1.0\n"
              "comment DishPlay Scan mesh, object frame, metres, y up\n"
              "comment provenance: 0 measured 1 interpolated 2 estimated\n"
              f"element vertex {nv}\nproperty float x\nproperty float y\nproperty float z\n"
              "property float nx\nproperty float ny\nproperty float nz\n"
              "property uchar red\nproperty uchar green\nproperty uchar blue\nproperty uchar provenance\n"
              f"element face {nt}\nproperty list uchar uint vertex_indices\nend_header\n").encode()
    dt = np.dtype([("p", "<f4", 3), ("n", "<f4", 3), ("c", "u1", 3), ("k", "u1")])
    a = np.zeros(nv, dt)
    a["p"], a["n"], a["c"], a["k"] = V, normals, colors, classes
    ft = np.dtype([("n", "u1"), ("i", "<u4", 3)])
    f = np.zeros(nt, ft)
    f["n"] = 3
    f["i"] = T
    Path(path).write_bytes(header + a.tobytes() + f.tobytes())


def write_glb(path: Path, V: np.ndarray, T: np.ndarray, normals: np.ndarray | None = None,
              colors: np.ndarray | None = None, uv: np.ndarray | None = None, texture_bgr: np.ndarray | None = None,
              provenance: np.ndarray | None = None, extras: dict | None = None) -> dict:
    """Minimal glTF 2.0 binary writer (y up, metres). Returns the JSON part for inspection.

    With uv + texture_bgr the PNG is embedded; else per-vertex COLOR_0. A custom
    attribute _PROVENANCE (float scalar) keeps measured/interpolated/estimated classes.
    """
    V = np.ascontiguousarray(V, np.float32)
    T = np.ascontiguousarray(T, np.uint32).reshape(-1)
    bin_chunks: list[bytes] = []
    views, accessors = [], []

    def add_view(data: bytes, target: int | None):
        off = sum(len(c) for c in bin_chunks)
        pad = (4 - len(data) % 4) % 4
        bin_chunks.append(data + b"\0" * pad)
        v = {"buffer": 0, "byteOffset": off, "byteLength": len(data)}
        if target:
            v["target"] = target
        views.append(v)
        return len(views) - 1

    def add_acc(arr: np.ndarray, comp: int, typ: str, normalized=False, minmax=False):
        vi = add_view(arr.tobytes(), 34962 if typ != "SCALAR" or comp == 5126 else 34963)
        a = {"bufferView": vi, "componentType": comp, "count": int(arr.shape[0]), "type": typ}
        if normalized:
            a["normalized"] = True
        if minmax:
            a["min"] = arr.min(0).tolist()
            a["max"] = arr.max(0).tolist()
        accessors.append(a)
        return len(accessors) - 1

    attrs = {"POSITION": add_acc(V, 5126, "VEC3", minmax=True)}
    if normals is not None:
        n = np.asarray(normals, np.float32)
        n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        attrs["NORMAL"] = add_acc(np.ascontiguousarray(n), 5126, "VEC3")
    material = {"name": "dish", "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 0.8}, "doubleSided": True}
    images, textures, samplers = [], [], []
    if uv is not None and texture_bgr is not None:
        attrs["TEXCOORD_0"] = add_acc(np.ascontiguousarray(uv, np.float32), 5126, "VEC2")
        ok, png = cv2.imencode(".png", texture_bgr)
        assert ok
        vi = add_view(png.tobytes(), None)
        images.append({"bufferView": vi, "mimeType": "image/png"})
        samplers.append({"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071})
        textures.append({"sampler": 0, "source": 0})
        material["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}
    elif colors is not None:
        c = np.ones((len(V), 4), np.uint8) * 255
        c[:, :3] = colors
        attrs["COLOR_0"] = add_acc(np.ascontiguousarray(c), 5121, "VEC4", normalized=True)
    if provenance is not None:
        attrs["_PROVENANCE"] = add_acc(np.ascontiguousarray(provenance, np.float32), 5126, "SCALAR")
    idx = add_acc(T, 5125, "SCALAR")
    accessors[idx]["count"] = int(len(T))
    gltf = {
        "asset": {"version": "2.0", "generator": "DishPlay Scan P1"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "dish"}],
        "meshes": [{"primitives": [{"attributes": attrs, "indices": idx, "material": 0, "mode": 4}]}],
        "materials": [material], "accessors": accessors, "bufferViews": views,
        "buffers": [{"byteLength": sum(len(c) for c in bin_chunks)}],
    }
    if images:
        gltf.update(images=images, textures=textures, samplers=samplers)
    if extras:
        gltf["asset"]["extras"] = extras
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    binb = b"".join(bin_chunks)
    total = 12 + 8 + len(js) + 8 + len(binb)
    out = struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(binb), 0x004E4942) + binb
    Path(path).write_bytes(out)
    return gltf


def read_glb(path: Path) -> tuple[dict, bytes]:
    data = Path(path).read_bytes()
    magic, version, total = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67 or version != 2 or total != len(data):
        raise ValueError("not a valid GLB v2 file")
    jl, jt = struct.unpack_from("<II", data, 12)
    if jt != 0x4E4F534A:
        raise ValueError("first chunk must be JSON")
    js = json.loads(data[20:20 + jl])
    off = 20 + jl
    bl, bt = struct.unpack_from("<II", data, off)
    if bt != 0x004E4942:
        raise ValueError("second chunk must be BIN")
    return js, data[off + 8: off + 8 + bl]


def glb_accessor(js: dict, binb: bytes, idx: int) -> np.ndarray:
    a = js["accessors"][idx]
    v = js["bufferViews"][a["bufferView"]]
    dt = {5126: "<f4", 5125: "<u4", 5121: "u1"}[a["componentType"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    return np.frombuffer(binb, dt, a["count"] * width, v["byteOffset"]).reshape(a["count"], width)
