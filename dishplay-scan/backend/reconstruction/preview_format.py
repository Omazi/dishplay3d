"""Binary preview geometry (DPG1) and frame upload envelope (DPF1).

Both formats are little-endian and documented in contracts/*.schema.json.

DPG1 layout
  0   4  magic b"DPG1"
  4   4  u32 header_len
  8   h  UTF-8 JSON header (contracts/preview-message.schema.json, "geometry_header")
  ..     zero padding to a multiple of 4
  then sections in this order, each 4-byte aligned:
    points_xyz    point_count * 3 * f32
    points_rgbc   point_count * 4 * u8      (r, g, b, class)
    mesh_xyz      vertex_count * 3 * f32
    mesh_rgbc     vertex_count * 4 * u8     (r, g, b, class)
    mesh_normal   vertex_count * 4 * i8     (nx, ny, nz, 0) scaled by 127
    mesh_index    triangle_count * 3 * u32

DPF1 layout (iPhone -> server, one keyframe)
  0   4  magic b"DPF1"
  4   4  u32 meta_len,  meta JSON (contracts/capture-session.schema.json#/$defs/frame)
  ..  4  u32 image_len, JPEG bytes (sensor-native orientation)
  ..  4  u32 depth_len, optional float32 depth (metres) row-major, 0 if absent
  ..  4  u32 conf_len,  optional uint8 confidence (ARKit 0/1/2), 0 if absent
"""
from __future__ import annotations

import json
import struct

import numpy as np

MAX_META = 64 * 1024
MAX_IMAGE = 16 * 1024 * 1024
MAX_DEPTH = 4 * 1024 * 1024


def _pad4(n: int) -> int:
    return (4 - n % 4) % 4


def encode_geometry(header: dict, points=None, point_rgbc=None, verts=None, vert_rgbc=None, normals=None, tris=None) -> bytes:
    points = np.zeros((0, 3), np.float32) if points is None else np.asarray(points, np.float32).reshape(-1, 3)
    point_rgbc = np.zeros((0, 4), np.uint8) if point_rgbc is None else np.asarray(point_rgbc, np.uint8).reshape(-1, 4)
    verts = np.zeros((0, 3), np.float32) if verts is None else np.asarray(verts, np.float32).reshape(-1, 3)
    vert_rgbc = np.zeros((0, 4), np.uint8) if vert_rgbc is None else np.asarray(vert_rgbc, np.uint8).reshape(-1, 4)
    if normals is None:
        normals = np.zeros((len(verts), 3), np.float32)
    n8 = np.zeros((len(verts), 4), np.int8)
    n8[:, :3] = np.clip(np.round(np.asarray(normals, np.float32).reshape(-1, 3) * 127), -127, 127).astype(np.int8)
    tris = np.zeros((0, 3), np.uint32) if tris is None else np.asarray(tris, np.uint32).reshape(-1, 3)
    assert len(point_rgbc) == len(points) and len(vert_rgbc) == len(verts)
    header = dict(header)
    header.update(point_count=len(points), vertex_count=len(verts), triangle_count=len(tris))
    hb = json.dumps(header, separators=(",", ":")).encode()
    out = bytearray(b"DPG1" + struct.pack("<I", len(hb)) + hb + b"\0" * _pad4(len(hb)))
    for arr in (points, point_rgbc, verts, vert_rgbc, n8, tris):
        out += np.ascontiguousarray(arr).astype(arr.dtype.newbyteorder("<")).tobytes()
    return bytes(out)


def decode_geometry(buf: bytes) -> dict:
    if buf[:4] != b"DPG1":
        raise ValueError("bad magic")
    (hl,) = struct.unpack_from("<I", buf, 4)
    header = json.loads(buf[8:8 + hl])
    off = 8 + hl + _pad4(hl)
    out = {"header": header}
    n, v, t = header["point_count"], header["vertex_count"], header["triangle_count"]
    for name, dtype, count, width in (("points", "<f4", n, 3), ("point_rgbc", "u1", n, 4), ("verts", "<f4", v, 3),
                                      ("vert_rgbc", "u1", v, 4), ("normals", "i1", v, 4), ("tris", "<u4", t, 3)):
        size = np.dtype(dtype).itemsize * count * width
        out[name] = np.frombuffer(buf, dtype, count * width, off).reshape(count, width)
        off += size
    if off != len(buf):
        raise ValueError(f"trailing bytes: {len(buf) - off}")
    return out


class EnvelopeError(ValueError):
    pass


def encode_frame(meta: dict, image: bytes, depth: bytes = b"", confidence: bytes = b"") -> bytes:
    mb = json.dumps(meta, separators=(",", ":")).encode()
    return b"DPF1" + b"".join(struct.pack("<I", len(x)) + x for x in (mb, image, depth, confidence))


def decode_frame(buf: bytes) -> tuple[dict, bytes, bytes, bytes]:
    if len(buf) < 20 or buf[:4] != b"DPF1":
        raise EnvelopeError("bad_magic")
    off = 4
    parts = []
    for limit in (MAX_META, MAX_IMAGE, MAX_DEPTH, MAX_DEPTH):
        if off + 4 > len(buf):
            raise EnvelopeError("truncated")
        (n,) = struct.unpack_from("<I", buf, off)
        off += 4
        if n > limit or off + n > len(buf):
            raise EnvelopeError("section_too_large_or_truncated")
        parts.append(bytes(buf[off:off + n]))
        off += n
    if off != len(buf):
        raise EnvelopeError("trailing_bytes")
    try:
        meta = json.loads(parts[0])
    except json.JSONDecodeError as exc:
        raise EnvelopeError("bad_meta_json") from exc
    return meta, parts[1], parts[2], parts[3]
