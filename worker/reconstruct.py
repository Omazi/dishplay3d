#!/usr/bin/env python3
"""Opt-in local reconstruction; never called by a menu request or a Vercel function."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = Path(__file__).resolve().parent
PINS = json.loads((HERE / "toolchain.json").read_text())
TOOLS = ("colmap", "InterfaceCOLMAP", "DensifyPointCloud", "ReconstructMesh", "RefineMesh", "TextureMesh", "blender")
MIB = 1024 * 1024
ENGINE_ID = "legacy-photogrammetry-v1"
# Both script execution and unittest package import are supported.
if __package__:
    from .video import extract_video, validate_container, VideoError
    from .engines import ENGINES, engine_for
else:
    from video import extract_video, validate_container, VideoError
    from engines import ENGINES, engine_for


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(MIB), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def memory_available() -> int | None:
    try:
        match = re.search(r"^MemAvailable:\s+(\d+) kB", Path("/proc/meminfo").read_text(), re.M)
        return int(match[1]) * 1024 if match else None
    except OSError:
        return None


def doctor() -> dict:
    """Presence check only: no engine processes, imports, downloads or image decoding."""
    try:
        pillow = importlib.metadata.version("Pillow")
    except importlib.metadata.PackageNotFoundError:
        pillow = None
    return {
        "tools": {name: shutil.which(name) for name in TOOLS},
        "pillow_installed": pillow,
        "video_tools": {name: shutil.which(name) for name in ("ffmpeg", "ffprobe")},
        "required_versions": {key: PINS[key] for key in ("colmap", "openmvs", "blender", "pillow")},
        "available_memory_mib": round(memory_available() / MIB) if memory_available() else None,
        "run_supported_platform": sys.platform == "linux",
        "engines_executed": False,
        "reconstruction_verified": False,
    }


def input_manifest(source: Path, max_images: int = 24, allow_duplicates: bool = False) -> list[dict]:
    if not 3 <= max_images <= 40:
        raise ValueError("max-images must be between 3 and 40; default is 24")
    if not source.is_dir():
        raise ValueError("Input must be a local directory of JPEG/PNG photos")
    paths = sorted(path for path in source.iterdir() if path.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not 3 <= len(paths) <= max_images:
        raise ValueError(f"Found {len(paths)} photos; provide 3–{max_images}. No views are silently discarded.")
    frames, total = [], 0
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Photo must be a regular file: {path.name}")
        size = path.stat().st_size
        if not 0 < size <= 25 * MIB:
            raise ValueError(f"Photo exceeds the 25 MiB limit or is empty: {path.name}")
        total += size
        if total > 400 * MIB:
            raise ValueError("Input exceeds the 400 MiB total limit")
        with path.open("rb") as stream:
            magic = stream.read(8)
        if not (magic.startswith(b"\xff\xd8\xff") or magic == b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"Not a JPEG/PNG signature: {path.name}")
        frames.append({"name": path.name, "bytes": size, "sha256": digest(path)})
    if not allow_duplicates and len({frame["sha256"] for frame in frames}) != len(frames):
        raise ValueError("Duplicate photos detected; use distinct views")
    return frames


def settings_from(args: argparse.Namespace) -> dict:
    if not 320 <= args.long_edge <= 1600:
        raise ValueError("long-edge must be between 320 and 1600 pixels")
    if not 512 <= args.memory_mib <= 2048:
        raise ValueError("memory-mib must be between 512 and 2048")
    if not 30 <= args.stage_seconds <= 1800:
        raise ValueError("stage-seconds must be between 30 and 1800")
    if not 256 <= args.disk_mib <= 4096:
        raise ValueError("disk-mib must be between 256 and 4096")
    if args.scale_m_per_unit is not None and (not math.isfinite(args.scale_m_per_unit) or not 0 < args.scale_m_per_unit <= 1000):
        raise ValueError("scale-m-per-unit must be a finite positive number no greater than 1000")
    if bool(args.scale_reference) != (args.scale_m_per_unit is not None):
        raise ValueError("Supply scale-m-per-unit and scale-reference together, or neither")
    if not 3 <= args.max_images <= 40:
        raise ValueError("max-images must be between 3 and 40")
    return {"max_images": args.max_images, "long_edge": args.long_edge, "memory_mib": args.memory_mib,
            "disk_mib": args.disk_mib, "stage_seconds": args.stage_seconds, "threads": 1, "gpu": False,
            "scale_m_per_unit": args.scale_m_per_unit, "scale_reference": args.scale_reference,
            "openmvs_cuda_build": args.openmvs_cuda_build}


def identity(frames: list[dict], settings: dict, restaurant: str) -> str:
    payload = {"schema": 1, "restaurant": restaurant, "inputs": frames, "settings": settings, "engines": PINS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def plan_commands(output: Path, settings: dict) -> list[dict]:
    def stage(name, *command):
        return {"name": name, "command": [str(item) for item in command]}

    db, images, sparse, dense = (output / name for name in ("database.db", "images", "sparse", "dense"))
    common = ["--max-threads", "1"]
    # CUDA options exist only in CUDA-enabled builds. Their explicit CPU mode is -2.
    cpu = ["--cuda-device", "-2"] if settings["openmvs_cuda_build"] else []
    return [
        stage("features", "colmap", "feature_extractor", "--database_path", db, "--image_path", images,
              "--ImageReader.camera_model", "SIMPLE_RADIAL", "--SiftExtraction.use_gpu", "0",
              "--SiftExtraction.num_threads", "1", "--SiftExtraction.max_image_size", settings["long_edge"],
              "--SiftExtraction.max_num_features", "4096"),
        stage("matching", "colmap", "exhaustive_matcher", "--database_path", db,
              "--SiftMatching.use_gpu", "0", "--SiftMatching.num_threads", "1"),
        stage("calibration", "colmap", "mapper", "--database_path", db, "--image_path", images,
              "--output_path", sparse, "--Mapper.num_threads", "1", "--Mapper.multiple_models", "0"),
        stage("undistort", "colmap", "image_undistorter", "--image_path", images,
              "--input_path", sparse / "0", "--output_path", dense, "--output_type", "COLMAP",
              "--max_image_size", settings["long_edge"]),
        stage("import", "InterfaceCOLMAP", "-i", dense, "-o", output / "scene.mvs",
              "--image-folder", dense / "images", *common),
        stage("densification", "DensifyPointCloud", "-i", output / "scene.mvs", "-o", output / "dense.mvs",
              "--resolution-level", "1", "--max-resolution", "1600", "--min-resolution", "320", *common, *cpu),
        stage("mesh", "ReconstructMesh", "-i", output / "dense.mvs", "-p", output / "dense.ply",
              "-o", output / "mesh.mvs", *common, *cpu),
        # OpenMVS's default interface archive keeps cameras in dense.mvs and
        # exports geometry separately. Mesh stages do not create mesh.mvs.
        stage("refinement", "RefineMesh", "-i", output / "dense.mvs", "-m", output / "mesh.ply",
              "-o", output / "refined.mvs",
              "--resolution-level", "1", *common, *cpu),
        stage("texture", "TextureMesh", "-i", output / "dense.mvs", "-m", output / "refined.ply",
              "-o", output / "textured.mvs",
              "--export-type", "glb", "--max-texture-size", "2048", *common, *cpu),
        stage("exports", "blender", "--background", "--factory-startup", "--threads", "1",
              "--python-exit-code", "1", "--python", HERE / "export_blender.py", "--",
              output / "textured.glb", output / "model.glb", output / "model.usdz",
              settings["scale_m_per_unit"] or 1),
    ]


def validate_glb(path: Path) -> dict:
    """Conservative structural check, not visual or metric quality certification."""
    if not 20 <= path.stat().st_size <= 64 * MIB:
        raise ValueError("GLB missing, empty or above 64 MiB")
    blob = path.read_bytes()
    magic, version, length = struct.unpack_from("<4sII", blob)
    if (magic, version, length) != (b"glTF", 2, len(blob)):
        raise ValueError("Invalid GLB header")
    offset, chunks = 12, []
    while offset < len(blob):
        if offset + 8 > len(blob):
            raise ValueError("Truncated GLB chunk")
        size, kind = struct.unpack_from("<I4s", blob, offset)
        offset += 8
        if size % 4 or offset + size > len(blob):
            raise ValueError("Invalid GLB chunk length")
        chunks.append((kind, blob[offset:offset + size]))
        offset += size
    if len(chunks) != 2 or chunks[0][0] != b"JSON" or chunks[1][0] != b"BIN\x00":
        raise ValueError("Expected embedded JSON and BIN chunks")
    document = json.loads(chunks[0][1])
    binary = chunks[1][1]
    buffers = document.get("buffers", [])
    if len(buffers) != 1 or "uri" in buffers[0] or not 0 < buffers[0].get("byteLength", 0) <= len(binary):
        raise ValueError("GLB must contain its binary data")
    views = document.get("bufferViews", [])
    for view in views:
        if view.get("buffer", 0) != 0 or view.get("byteOffset", 0) < 0 or view.get("byteLength", 0) <= 0:
            raise ValueError("Invalid GLB buffer view")
        if view.get("byteOffset", 0) + view["byteLength"] > buffers[0]["byteLength"]:
            raise ValueError("GLB buffer view exceeds binary data")
    primitives = [primitive for mesh in document.get("meshes", []) for primitive in mesh.get("primitives", [])]
    if not primitives:
        raise ValueError("GLB contains no mesh")

    def reference(items, index):
        if not isinstance(index, int) or index < 0 or index >= len(items):
            raise ValueError("GLB reference outside its array")
        return items[index]

    def accessor_data(index, expected_type):
        accessor = reference(document["accessors"], index)
        if accessor.get("type") != expected_type or accessor.get("count", 0) <= 0 or "sparse" in accessor:
            raise ValueError("Unsupported or empty GLB accessor")
        formats = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
        components = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}
        fmt = "<" + formats[accessor["componentType"]] * components[expected_type]
        width = struct.calcsize(fmt)
        view = reference(views, accessor["bufferView"])
        offset = accessor.get("byteOffset", 0)
        stride = view.get("byteStride", width)
        if offset < 0 or stride < width or offset + (accessor["count"] - 1) * stride + width > view["byteLength"]:
            raise ValueError("GLB accessor exceeds its buffer view")
        start = view.get("byteOffset", 0) + offset
        return accessor, (struct.unpack_from(fmt, binary, start + item * stride) for item in range(accessor["count"]))

    try:
        for primitive in primitives:
            if primitive.get("mode", 4) != 4 or "TEXCOORD_0" not in primitive["attributes"]:
                raise ValueError("GLB requires triangles with UV coordinates")
            accessor, positions = accessor_data(primitive["attributes"]["POSITION"], "VEC3")
            if accessor["count"] < 3 or accessor["componentType"] != 5126:
                raise ValueError("GLB contains no usable geometry")
            first, varied = None, False
            for position in positions:
                if not all(math.isfinite(value) for value in position):
                    raise ValueError("GLB contains non-finite positions")
                if first is None:
                    first = position
                varied |= position != first
            if not varied:
                raise ValueError("GLB mesh has no spatial extent")
            uv, _ = accessor_data(primitive["attributes"]["TEXCOORD_0"], "VEC2")
            if uv["count"] != accessor["count"]:
                raise ValueError("UV count differs from vertex count")
            if "indices" in primitive:
                indices, values = accessor_data(primitive["indices"], "SCALAR")
                if indices["componentType"] not in (5121, 5123, 5125) or indices["count"] % 3:
                    raise ValueError("Invalid triangle index data")
                if any(index[0] >= accessor["count"] for index in values):
                    raise ValueError("Triangle index outside vertex data")
            elif accessor["count"] % 3:
                raise ValueError("Incomplete non-indexed triangles")
            material = reference(document["materials"], primitive["material"])
            texture = reference(document["textures"], material["pbrMetallicRoughness"]["baseColorTexture"]["index"])
            image = reference(document["images"], texture["source"])
            image_view = reference(views, image["bufferView"])
            start = image_view.get("byteOffset", 0)
            signature = binary[start:start + 8]
            if image.get("mimeType") not in ("image/png", "image/jpeg") or "uri" in image:
                raise ValueError("Texture must be an embedded PNG/JPEG")
            if not (signature == b"\x89PNG\r\n\x1a\n" or signature.startswith(b"\xff\xd8\xff")):
                raise ValueError("Texture data has an invalid signature")
    except (KeyError, IndexError, TypeError, struct.error) as error:
        raise ValueError("Missing or invalid GLB geometry/material/texture references") from error
    return {"mesh_primitives": len(primitives), "embedded_textures": True, "visual_review": "required"}


def validate_usdz(path: Path) -> dict:
    if not 20 <= path.stat().st_size <= 128 * MIB:
        raise ValueError("USDZ missing, empty or above 128 MiB")
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if not members or Path(members[0].filename).suffix.lower() not in (".usd", ".usda", ".usdc"):
            raise ValueError("USDZ must start with a USD scene")
        total, textures = 0, 0
        for member in members:
            parts = Path(member.filename)
            if parts.is_absolute() or ".." in parts.parts or "\\" in member.filename or member.compress_type != zipfile.ZIP_STORED:
                raise ValueError("Unsafe path or compressed USDZ entry")
            total += member.file_size
            if total > 128 * MIB:
                raise ValueError("USDZ expanded size exceeds limit")
            with archive.open(member) as stream:
                signature = stream.read(8)
            if member is members[0] and not (signature.startswith(b"#usda") or signature == b"PXR-USDC"):
                raise ValueError("Invalid USD root signature")
            if parts.suffix.lower() in (".png", ".jpg", ".jpeg"):
                if not (signature == b"\x89PNG\r\n\x1a\n" or signature.startswith(b"\xff\xd8\xff")):
                    raise ValueError("Invalid USDZ texture signature")
                textures += 1
        if not textures:
            raise ValueError("USDZ contains no image textures")
    return {"packaged_textures": textures, "quick_look_review": "required"}


def validate_outputs(output: Path) -> dict:
    report = json.loads((output / "export-report.json").read_text())
    if report.get("roundtrip_textures_verified") != ["glb", "usdz"]:
        raise ValueError("Blender did not verify textured exports by reimporting both formats")
    result = {"glb": validate_glb(output / "model.glb"), "usdz": validate_usdz(output / "model.usdz")}
    for kind in ("glb", "usdz"):
        path = output / f"model.{kind}"
        result[kind].update({"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)})
    return result


def write_manifest(output: Path, manifest: dict):
    temporary = output / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(output / "manifest.json")


@contextlib.contextmanager
def task_lock():
    import fcntl
    path = Path(tempfile.gettempdir()) / f"dishplay-worker-{os.getuid()}.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Another reconstruction is running for this user") from error
        yield


def resource_guard(output: Path, settings: dict):
    used = sum(path.stat().st_size for path in output.rglob("*") if path.is_file() and not path.is_symlink())
    if used > settings["disk_mib"] * MIB or shutil.disk_usage(output).free < 1024 * MIB:
        raise ValueError("Disk limit reached; intermediates and originals are preserved")
    available = memory_available()
    if available is not None and available < 512 * MIB:
        raise ValueError("Available memory fell below 512 MiB; stopped to protect the laptop")


def arm_parent_death(expected_parent_pid: int, death_signal: int = signal.SIGTERM):
    """Stop this Linux process if its supervising parent disappears.

    prctl does not report a parent that died before the call, so checking the
    expected PID after arming is essential. This protects direct children;
    deployment-level cgroups are still needed to contain arbitrary descendants.
    """
    if sys.platform != "linux" or expected_parent_pid <= 0:
        raise ValueError("Parent supervision requires Linux and a positive parent PID")
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(1, int(death_signal), 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    if os.getppid() != expected_parent_pid:
        os.kill(os.getpid(), death_signal)
        raise RuntimeError("Supervising parent changed before startup")


def bounded_cgroup_memory() -> int | None:
    for filename in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            value = int(Path(filename).read_text().strip())
            if 0 < value <= 2048 * MIB:
                return value
        except (OSError, ValueError):
            pass
    return None


def process_limits(settings: dict, parent_pid: int):
    # Engine processes start a separate session; do not let that detach them
    # from Python when it is killed without a chance to run normal cleanup.
    arm_parent_death(parent_pid, signal.SIGKILL)
    import resource
    os.nice(10)
    # Native engines reserve much more virtual address space than resident RAM.
    # Skip the virtual-address guard only with a verified <=2 GiB kernel cgroup RAM limit.
    # The Node supervisor still measures resident memory and stops under host pressure.
    if bounded_cgroup_memory() is None:
        resource.setrlimit(resource.RLIMIT_AS, (settings["memory_mib"] * MIB,) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (512 * MIB,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (settings["stage_seconds"],) * 2)


def environment() -> dict:
    env = os.environ.copy()
    env.update({"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                "NUMEXPR_NUM_THREADS": "1", "CUDA_VISIBLE_DEVICES": "-1", "QT_QPA_PLATFORM": "offscreen"})
    return env


def execute_stage(stage: dict, output: Path, settings: dict) -> dict:
    start = time.monotonic()
    record = {**stage, "state": "running", "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    log = output / f"{stage['name']}.log"
    parent_pid = os.getpid()
    with contextlib.ExitStack() as stack:
        stream = stack.enter_context(log.open("wb"))
        stdout = stack.enter_context((output / stage["stdout_file"]).open("wb")) if stage.get("stdout_file") else stream
        process = subprocess.Popen(stage["command"], cwd=output, stdout=stdout, stderr=stream,
                                   env=environment(), start_new_session=True,
                                   preexec_fn=lambda: process_limits(settings, parent_pid))
        try:
            while process.poll() is None:
                if time.monotonic() - start > settings["stage_seconds"]:
                    raise ValueError(f"Stage timeout: {stage['name']}")
                resource_guard(output, settings)
                time.sleep(1)
            if process.returncode != 0:
                raise ValueError(f"Stage {stage['name']} exited {process.returncode}; inspect {log.name}")
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
    record.update({"state": "completed", "seconds": round(time.monotonic() - start, 3), "exit_code": process.returncode})
    return record


def verify_versions(settings: dict, output: Path) -> dict:
    versions = {}
    parent_pid = os.getpid()
    for tool in TOOLS:
        version = PINS["colmap" if tool == "colmap" else "blender" if tool == "blender" else "openmvs"]
        command = [tool, "--version" if tool == "blender" else "-h"]
        log = output / f"version-{tool}.log"
        with log.open("wb") as stream:
            process = subprocess.Popen(command, cwd=output, env=environment(), stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True,
                                       preexec_fn=lambda: process_limits(settings, parent_pid))
            try:
                process.wait(timeout=10)
            except BaseException:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise
        text = log.read_text(errors="replace")
        if not re.search(rf"(?<![\d.])v?{re.escape(version)}(?![\d.])", text):
            raise ValueError(f"{tool} must match pinned {version}; inspect {log.name}")
        if tool in ("DensifyPointCloud", "ReconstructMesh", "RefineMesh", "TextureMesh"):
            if ("cuda-device" in text) != settings["openmvs_cuda_build"]:
                raise ValueError("OpenMVS CUDA build differs from plan; explicitly set --openmvs-cuda-build when applicable")
        versions[tool] = {"version": version, "binary_sha256": digest(Path(shutil.which(tool))), "help_log": log.name}
    return versions


def prepare_images(source: Path, output: Path, frames: list[dict], settings: dict) -> list[dict]:
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 24_000_000
    prepared = []
    for index, frame in enumerate(frames):
        original = source / frame["name"]
        if original.is_symlink() or digest(original) != frame["sha256"]:
            raise ValueError("An input changed after manifest creation; start a new task")
        with Image.open(original, formats=("JPEG", "PNG")) as raw:
            if raw.width * raw.height > 24_000_000 or getattr(raw, "n_frames", 1) != 1:
                raise ValueError(f"Use still images under 24 megapixels: {frame['name']}")
            photo = ImageOps.exif_transpose(raw)
            photo.thumbnail((settings["long_edge"], settings["long_edge"]))
            target = output / "images" / f"{index:04d}.jpg"
            photo.convert("RGB").save(target, quality=92)
            prepared.append({"original_sha256": frame["sha256"], "file": str(target.relative_to(output)),
                             "width": photo.width, "height": photo.height, "sha256": digest(target)})
        resource_guard(output, settings)
    return prepared


def run(source: Path, output: Path, frames: list[dict], settings: dict, restaurant: str, *, video=False, capture_manifest=None, prepare_only=False):
    checks = doctor()
    missing = [name for name, path in checks["tools"].items() if not path]
    if missing and not prepare_only:
        raise ValueError("Missing engines: " + ", ".join(missing) + ". Nothing was installed or launched.")
    if sys.platform != "linux":
        raise ValueError("This bounded runner requires Linux resource limits; plan/doctor work elsewhere")
    if not prepare_only and checks["pillow_installed"] != PINS["pillow"]:
        raise ValueError(f"Run needs Pillow {PINS['pillow']}; install worker/requirements.txt in an isolated environment")
    available = memory_available()
    if available is None or available < (settings["memory_mib"] + 1024) * MIB:
        raise ValueError("Insufficient available RAM: require the configured memory cap plus 1024 MiB headroom")
    if output.exists() or source == output or source in output.parents:
        raise ValueError("Output must be a new directory outside the original photo directory")
    with task_lock():
        output.mkdir(parents=True, mode=0o700)
        for name in ("images", "sparse", "dense"):
            (output / name).mkdir()
        manifest = {"schema": 1, "job_id": identity(frames, settings, restaurant), "restaurant": restaurant,
                    "state": "preflight", "engine_id": ENGINE_ID, "engine_versions": PINS, "inputs": frames, "settings": settings, "stages": [],
                    "originals_preserved": True, "published": False, "physical_device_tests": [],
                    "scale_verified": False, "quality_verified": False}
        started = time.monotonic()
        write_manifest(output, manifest)
        try:
            resource_guard(output, settings)
            if capture_manifest:
                if capture_manifest.is_symlink() or capture_manifest.stat().st_size > MIB:
                    raise ValueError("Invalid capture metadata sidecar")
                manifest["source_capture_manifest_sha256"] = digest(capture_manifest)
                capture = json.loads(capture_manifest.read_text())
                (output / "input").mkdir(exist_ok=True)
                shutil.copyfile(capture_manifest, output / "input" / "capture_manifest.json")
                # Raw camera metadata remains in its ORIGINAL pixel/orientation coordinates.
                # No implicit calibration is fabricated or fed to the unchanged legacy engine.
                (output / "input" / "camera_metadata.json").write_text(json.dumps({
                    "capture": capture.get("captureMetadata", {}), "frames": capture.get("frames", []),
                    "appliedToLegacyGeometry": False}, indent=2))
            if video:
                manifest["active_stage"] = "video_ingestion"
                write_manifest(output, manifest)
                expected = capture.get("manifest", {}).get("video", {}).get("sha256") if capture_manifest else None
                source, frames, extracted = extract_video(source, output, settings, execute_stage, expected)
                manifest["inputs"] = frames
                manifest["video_ingestion"] = extracted
                manifest["job_id"] = identity([{"sourceVideo": extracted["sourceVideo"], "captureMetadataHash": manifest.get("source_capture_manifest_sha256"), "extractor": extracted["extractor"], "tools": extracted["tools"]}, *frames], settings, restaurant)
            if prepare_only:
                manifest["state"] = "prepared_only"
                manifest["reconstruction_verified"] = False
                return
            manifest["engine_binaries"] = verify_versions(settings, output)
            manifest["prepared_images"] = prepare_images(source, output, frames, settings)
            for stage in plan_commands(output, settings):
                manifest["state"] = "running"
                manifest["active_stage"] = stage["name"]
                write_manifest(output, manifest)
                manifest["stages"].append(execute_stage(stage, output, settings))
                write_manifest(output, manifest)
            manifest["outputs"] = validate_outputs(output)
            manifest["state"] = "ready_for_review"
            manifest["required_reviews"] = ["dish fidelity and bowl interior", "orientation and measured scale",
                                             "GLB on Android", "USDZ Quick Look on iPhone"]
        except BaseException as error:
            manifest["state"] = "cancelled" if isinstance(error, KeyboardInterrupt) else "failed"
            manifest["error"] = str(error) or type(error).__name__
            manifest["error_code"] = getattr(error, "code", "ENGINE_FAILED")
            if "active_stage" in manifest:
                manifest["stages"].append({"name": manifest["active_stage"], "state": manifest["state"], "error": manifest["error"]})
            raise
        finally:
            manifest["elapsed_seconds"] = round(time.monotonic() - started, 3)
            import resource
            manifest["child_peak_rss_kib"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
            manifest.pop("active_stage", None)
            write_manifest(output, manifest)


def main() -> int:
    # The queue supervisor cancels with SIGTERM. Raising an interruption lets the
    # current stage terminate its separate engine process group and persist state.
    def interrupt(_signum, _frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, interrupt)
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=False)
    mode.add_argument("--doctor", action="store_true")
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--prepare-video", action="store_true", help="Validate/decode only; does not claim a reconstructed model")
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--input", type=Path)
    source_group.add_argument("--video", type=Path)
    parser.add_argument("--capture-manifest", type=Path)
    parser.add_argument("--engine", choices=list(ENGINES), default=ENGINE_ID)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--restaurant", default="local-private")
    parser.add_argument("--supervisor-pid", type=int,
                        help="Linux parent PID whose death cancels this supervised --run")
    parser.add_argument("--max-images", type=int, default=24)
    parser.add_argument("--long-edge", type=int, default=1600)
    parser.add_argument("--memory-mib", type=int, default=1536)
    parser.add_argument("--disk-mib", type=int, default=2048)
    parser.add_argument("--stage-seconds", type=int, default=900)
    parser.add_argument("--scale-m-per-unit", type=float)
    parser.add_argument("--scale-reference")
    parser.add_argument("--openmvs-cuda-build", action="store_true", help="Use CPU mode -2 in a CUDA-enabled OpenMVS build")
    args = parser.parse_args()
    try:
        if args.supervisor_pid is not None:
            if not args.run:
                parser.error("--supervisor-pid is only valid with --run")
            arm_parent_death(args.supervisor_pid)
        if args.doctor:
            print(json.dumps(doctor(), indent=2))
            return 0
        if (args.input is None and args.video is None) or args.output is None:
            parser.error("--input or --video, plus --output are required")
        if args.prepare_video and not args.video:
            parser.error("--prepare-video requires --video")
        source_arg = args.video or args.input
        if source_arg.is_symlink():
            raise ValueError("Input cannot be a symbolic link")
        source, output = source_arg.resolve(), args.output.resolve()
        engine = engine_for(args.engine)
        if engine.versions != PINS:
            raise ValueError("Engine registry and toolchain pins differ")
        settings = settings_from(args)
        capture = None
        if args.capture_manifest:
            if args.capture_manifest.is_symlink() or args.capture_manifest.stat().st_size > MIB:
                raise ValueError("Invalid capture metadata sidecar")
            capture = json.loads(args.capture_manifest.read_text())
        ordered = bool(capture and capture.get("manifest", {}).get("schema") == 2)
        frames = [] if args.video else input_manifest(source, args.max_images, allow_duplicates=ordered)
        if ordered and not args.video:
            supplied = capture.get("frames", [])
            if len(supplied) != len(frames) or any(a["sha256"] != b.get("sha256") for a,b in zip(frames,supplied)):
                raise ValueError("Ordered image inputs differ from capture manifest")
            frames = [{**frame, "frameIndex":meta["frameIndex"], "timestampMs":meta["timestampMs"],
                       "width":meta["width"], "height":meta["height"], "metadata":meta.get("metadata", {})}
                      for frame,meta in zip(frames,supplied)]
        source_video_identity = validate_container(source) if args.video and args.plan else None
        if args.plan:
            print(json.dumps({"state": "planned_only", "engines_executed": False,
                              "job_id": identity([source_video_identity] if source_video_identity else frames, settings, args.restaurant), "inputs": frames,
                              "engine_id":args.engine, "video":str(source) if args.video else None,
                              "videoValidation":"pending_decode" if args.video else None,
                              "settings": settings, "commands": plan_commands(output, settings)}, indent=2))
        else:
            run(source, output, frames, settings, args.restaurant, video=bool(args.video),
                capture_manifest=args.capture_manifest, prepare_only=args.prepare_video)
            print(f"{'Video prepared; no reconstruction performed' if args.prepare_video else 'Exports ready for human review'}: {output / 'manifest.json'}")
        return 0
    except (ValueError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(f"Reconstruction stopped: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Cancelled. Original photos and intermediates are preserved.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
