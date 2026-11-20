"""Exports: PLY point cloud, PLY mesh, GLB (vertex colours or embedded texture), USDZ (textured, for AR Quick Look)."""
from __future__ import annotations

import json
import struct
import zlib
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
              provenance: np.ndarray | None = None, extras: dict | None = None,
              texture_jpeg_quality: int | None = None) -> dict:
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
        if texture_jpeg_quality:   # photographs compress ten times better as JPEG; glTF accepts both
            ok, enc = cv2.imencode(".jpg", texture_bgr, [cv2.IMWRITE_JPEG_QUALITY, int(texture_jpeg_quality)])
            mime = "image/jpeg"
        else:
            ok, enc = cv2.imencode(".png", texture_bgr)
            mime = "image/png"
        assert ok
        vi = add_view(enc.tobytes(), None)
        images.append({"bufferView": vi, "mimeType": mime})
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


# ----------------------------------------------------------------------------------------------- USDZ
def _zip_stored_aligned(files: list[tuple[str, bytes]], align: int = 64) -> bytes:
    """Zip archive as the USDZ format wants it: nothing compressed, and the bytes of every file starting on a
    multiple of 64 from the start of the archive (the padding goes in the "extra" field of its header)."""
    out = bytearray()
    central = bytearray()
    date, clock = (1 << 5) | 1, 0                     # 1980-01-01 00:00: the same bytes for the same model
    for name, data in files:
        nb = name.encode("utf-8")
        offset = len(out)
        pad = (-(offset + 30 + len(nb))) % align
        if 0 < pad < 4:                               # an extra field cannot be shorter than its own 4-byte header
            pad += align
        extra = struct.pack("<HH", 0x1986, pad - 4) + b"\0" * (pad - 4) if pad else b""
        crc = zlib.crc32(data) & 0xFFFFFFFF
        out += struct.pack("<IHHHHHIIIHH", 0x04034B50, 10, 0, 0, clock, date, crc, len(data), len(data), len(nb), len(extra))
        out += nb + extra + data
        central += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 10, 10, 0, 0, clock, date, crc, len(data), len(data),
                               len(nb), 0, 0, 0, 0, 0, offset) + nb
    start = len(out)
    out += central
    out += struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(files), len(files), len(central), start, 0)
    return bytes(out)


def _usd_tuples(a: np.ndarray, fmt: str) -> str:
    cell = "(" + ", ".join([fmt] * a.shape[1]) + ")"
    return ", ".join(cell % tuple(row) for row in a.tolist())


def write_usdz(path: Path, V: np.ndarray, T: np.ndarray, normals: np.ndarray, uv: np.ndarray, texture_bgr: np.ndarray,
               texture_jpeg_quality: int = 88, name: str = "Dish") -> dict:
    """Textured model as a .usdz (y up, metres, real size): what an iPhone or iPad opens in AR Quick Look and
    places on the table, with no app to install. Same mesh and texture as the GLB.

    uv follows the glTF convention used everywhere else in the engine (v counted from the top of the picture);
    USD counts it from the bottom, so it is turned over here. The scene is one text layer (USDA) with the mesh
    and a UsdPreviewSurface material reading the JPEG texture. Returns {"bytes", "files"}.
    """
    V = np.asarray(V, np.float64)
    T = np.asarray(T, np.int64).reshape(-1, 3)
    n = np.asarray(normals, np.float64)
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    st = np.stack([np.asarray(uv, np.float64)[:, 0], 1.0 - np.asarray(uv, np.float64)[:, 1]], 1)
    ok, jpg = cv2.imencode(".jpg", texture_bgr, [cv2.IMWRITE_JPEG_QUALITY, int(texture_jpeg_quality)])
    assert ok
    mat = f"/{name}/Materials/Surface"
    usda = f"""#usda 1.0
(
    customLayerData = {{
        string creator = "DishPlay Scan"
    }}
    defaultPrim = "{name}"
    metersPerUnit = 1
    upAxis = "Y"
)

def Xform "{name}" (
    kind = "component"
)
{{
    def Mesh "Geometry" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {{
        uniform bool doubleSided = 1
        float3[] extent = [{_usd_tuples(np.stack([V.min(0), V.max(0)]), "%.5f")}]
        int[] faceVertexCounts = [{", ".join(["3"] * len(T))}]
        int[] faceVertexIndices = [{", ".join(map(str, T.reshape(-1).tolist()))}]
        rel material:binding = <{mat}>
        normal3f[] normals = [{_usd_tuples(n, "%.3f")}] (
            interpolation = "vertex"
        )
        point3f[] points = [{_usd_tuples(V, "%.5f")}]
        texCoord2f[] primvars:st = [{_usd_tuples(st, "%.5f")}] (
            interpolation = "vertex"
        )
        uniform token subdivisionScheme = "none"
    }}

    def Scope "Materials"
    {{
        def Material "Surface"
        {{
            token outputs:surface.connect = <{mat}/PreviewSurface.outputs:surface>

            def Shader "PreviewSurface"
            {{
                uniform token info:id = "UsdPreviewSurface"
                color3f inputs:diffuseColor.connect = <{mat}/Texture.outputs:rgb>
                float inputs:metallic = 0
                float inputs:roughness = 0.9
                token outputs:surface
            }}

            def Shader "TexCoord"
            {{
                uniform token info:id = "UsdPrimvarReader_float2"
                string inputs:varname = "st"
                float2 outputs:result
            }}

            def Shader "Texture"
            {{
                uniform token info:id = "UsdUVTexture"
                asset inputs:file = @textures/dish.jpg@
                token inputs:sourceColorSpace = "sRGB"
                float2 inputs:st.connect = <{mat}/TexCoord.outputs:result>
                token inputs:wrapS = "clamp"
                token inputs:wrapT = "clamp"
                float3 outputs:rgb
            }}
        }}
    }}
}}
"""
    files = [("model.usda", usda.encode("utf-8")), ("textures/dish.jpg", jpg.tobytes())]
    data = _zip_stored_aligned(files)
    Path(path).write_bytes(data)
    return {"bytes": len(data), "files": [f[0] for f in files]}


def read_usdz(path: Path) -> tuple[str, dict]:
    """(text of the scene layer, {name: bytes} of every file) of a .usdz, for tests and inspection."""
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(Path(path).read_bytes())) as z:
        names = z.namelist()
        files = {nm: z.read(nm) for nm in names}
    return files[names[0]].decode("utf-8"), files
