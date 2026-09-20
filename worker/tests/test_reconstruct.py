"""Contract and rejection tests only. Synthetic bytes never prove reconstruction quality."""
import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from worker import reconstruct as worker


class WorkerContracts(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.settings = {"max_images": 24, "long_edge": 1600, "memory_mib": 1536, "disk_mib": 2048,
                         "stage_seconds": 900, "threads": 1, "gpu": False, "scale_m_per_unit": None,
                         "scale_reference": None, "openmvs_cuda_build": False}

    def tearDown(self):
        self.directory.cleanup()

    def test_virtual_memory_guard_requires_a_verified_kernel_ram_limit(self):
        with patch("pathlib.Path.read_text", return_value="max"):
            self.assertIsNone(worker.bounded_cgroup_memory())
        with patch("pathlib.Path.read_text", return_value=str(4 * 1024**3)):
            self.assertIsNone(worker.bounded_cgroup_memory())
        with patch("pathlib.Path.read_text", return_value=str(2 * 1024**3)):
            self.assertEqual(worker.bounded_cgroup_memory(), 2 * 1024**3)

    def photos(self):
        for number in range(3):
            (self.root / f"{number}.jpg").write_bytes(b"\xff\xd8\xff" + bytes([number]))
        return worker.input_manifest(self.root)

    def test_doctor_never_launches_processes(self):
        with patch("subprocess.Popen", side_effect=AssertionError("must not launch")):
            self.assertFalse(worker.doctor()["engines_executed"])

    def test_plan_never_launches_processes_or_writes_output(self):
        self.photos()
        output = self.root / "output"
        with patch("sys.argv", ["worker", "--plan", "--input", str(self.root), "--output", str(output)]), \
                patch("subprocess.Popen", side_effect=AssertionError("must not launch")), \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(worker.main(), 0)
        self.assertEqual(json.loads(stdout.getvalue())["state"], "planned_only")
        self.assertFalse(output.exists())

    def test_plan_uses_cpu_and_one_thread(self):
        stages = worker.plan_commands(self.root, self.settings)
        self.assertEqual(len(stages), 10)
        by_name = {stage["name"]: stage["command"] for stage in stages}
        for stage in ("features", "matching"):
            command = by_name[stage]
            flag = "--SiftExtraction.use_gpu" if stage == "features" else "--SiftMatching.use_gpu"
            self.assertEqual(command[command.index(flag) + 1], "0")
        for stage in ("import", "densification", "mesh", "refinement", "texture"):
            command = by_name[stage]
            self.assertEqual(command[command.index("--max-threads") + 1], "1")

    def test_cuda_build_explicitly_uses_cpu(self):
        self.settings["openmvs_cuda_build"] = True
        stages = worker.plan_commands(self.root, self.settings)
        for stage in stages[5:9]:
            command = stage["command"]
            self.assertEqual(command[command.index("--cuda-device") + 1], "-2")

    def test_identity_separates_restaurants_settings_and_input(self):
        frames = self.photos()
        original = worker.identity(frames, self.settings, "restaurant-a")
        self.assertEqual(original, worker.identity(frames, self.settings, "restaurant-a"))
        self.assertNotEqual(original, worker.identity(frames, self.settings, "restaurant-b"))
        self.assertNotEqual(original, worker.identity(frames, {**self.settings, "long_edge": 800}, "restaurant-a"))
        changed = [dict(frame) for frame in frames]
        changed[0]["sha256"] = "different"
        self.assertNotEqual(original, worker.identity(changed, self.settings, "restaurant-a"))

    def test_fake_images_duplicate_and_symlink_rejected(self):
        self.photos()
        (self.root / "2.jpg").write_text("not a photograph")
        with self.assertRaisesRegex(ValueError, "signature"):
            worker.input_manifest(self.root)
        (self.root / "2.jpg").write_bytes((self.root / "1.jpg").read_bytes())
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            worker.input_manifest(self.root)
        (self.root / "2.jpg").unlink()
        (self.root / "2.jpg").symlink_to(self.root / "1.jpg")
        with self.assertRaisesRegex(ValueError, "regular file"):
            worker.input_manifest(self.root)

    def test_too_many_views_are_not_silently_truncated(self):
        for number in range(25):
            (self.root / f"{number}.jpg").write_bytes(b"\xff\xd8\xff" + bytes([number]))
        with self.assertRaisesRegex(ValueError, "silently discarded"):
            worker.input_manifest(self.root)

    def test_missing_engine_fails_before_creating_output(self):
        output = self.root / "output"
        with patch.object(worker, "doctor", return_value={"tools": {"colmap": None}}), \
                patch("subprocess.Popen", side_effect=AssertionError("must not launch")):
            with self.assertRaisesRegex(ValueError, "Missing engines"):
                worker.run(self.root, output, [], self.settings, "restaurant-a")
        self.assertFalse(output.exists())

    def test_point_cloud_or_random_file_is_not_a_textured_glb(self):
        path = self.root / "model.glb"
        path.write_bytes(b"not a mesh" * 20)
        with self.assertRaisesRegex(ValueError, "header"):
            worker.validate_glb(path)
        # Valid outer framing, no mesh: the validator must still reject it.
        document = json.dumps({"asset": {"version": "2.0"}, "buffers": [{"byteLength": 4}]}).encode()
        document += b" " * (-len(document) % 4)
        body = struct.pack("<I4s", len(document), b"JSON") + document + struct.pack("<I4s", 4, b"BIN\0") + b"\0" * 4
        path.write_bytes(struct.pack("<4sII", b"glTF", 2, len(body) + 12) + body)
        with self.assertRaisesRegex(ValueError, "no mesh"):
            worker.validate_glb(path)

    def test_usdz_without_textures_or_with_unsafe_paths_is_rejected(self):
        path = self.root / "model.usdz"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("model.usda", "#usda 1.0\n")
        with self.assertRaisesRegex(ValueError, "no image textures"):
            worker.validate_usdz(path)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("../model.usda", "#usda 1.0\n")
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            worker.validate_usdz(path)

    def test_outputs_need_real_export_report(self):
        (self.root / "export-report.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "reimporting"):
            worker.validate_outputs(self.root)

    def test_manifest_does_not_imply_success(self):
        manifest = {"state": "failed", "quality_verified": False, "published": False,
                    "error": "missing actual geometry", "stages": []}
        worker.write_manifest(self.root, manifest)
        self.assertEqual(json.loads((self.root / "manifest.json").read_text()), manifest)
        self.assertFalse((self.root / "manifest.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
