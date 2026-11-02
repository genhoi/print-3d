"""Guard original files before Blender starts; optional actual render/export test."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("preview_under_test", SCRIPTS / "render_preview.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class PreviewPathTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.source = self.root / "source.stl"
        self.source.write_bytes(b"source geometry must survive")
        self.output = self.root / "preview.png"
        self.blend = self.root / "preview.blend"

    def arguments(self, *extra):
        return preview.parse_args(["--input", str(self.source), "--output", str(self.output), "--blend-output", str(self.blend), *extra])

    def test_new_paths_are_allowed_without_blender_import(self):
        preview.validate_paths(self.arguments())
        self.assertFalse(self.output.exists())
        self.assertFalse(self.blend.exists())

    def test_existing_png_or_editable_blend_rejected_before_scene_change(self):
        for existing in (self.output, self.blend):
            existing.write_bytes(b"precious editable content")
            with self.assertRaises(FileExistsError):
                preview.main(["--input", str(self.source), "--output", str(self.output), "--blend-output", str(self.blend)])
            self.assertEqual(existing.read_bytes(), b"precious editable content")
            self.assertEqual(self.source.read_bytes(), b"source geometry must survive")
            existing.unlink()

    def test_explicit_overwrite_allows_existing_regular_outputs(self):
        self.output.write_bytes(b"old preview")
        self.blend.write_bytes(b"old preview scene")
        preview.validate_paths(self.arguments("--overwrite"))
        self.assertEqual(self.source.read_bytes(), b"source geometry must survive")

    def test_overwrite_still_protects_source_hardlink(self):
        try:
            os.link(self.source, self.output)
        except OSError as exc:
            self.skipTest(f"Hardlinks unavailable: {exc}")
        with self.assertRaisesRegex(ValueError, "source STL"):
            preview.validate_paths(self.arguments("--overwrite"))
        self.assertEqual(self.source.read_bytes(), b"source geometry must survive")

    def test_reject_nonregular_output_and_aliasing_outputs(self):
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, "not a regular file"):
            preview.validate_paths(self.arguments("--overwrite"))
        self.output.rmdir()
        self.output.write_bytes(b"old preview")
        try:
            os.link(self.output, self.blend)
        except OSError as exc:
            self.skipTest(f"Hardlinks unavailable: {exc}")
        with self.assertRaisesRegex(ValueError, "different files"):
            preview.validate_paths(self.arguments("--overwrite"))


@unittest.skipUnless(os.environ.get("PRINT3D_TEST_BLENDER"), "Set PRINT3D_TEST_BLENDER for real Blender checks")
class BlenderIntegrationTests(unittest.TestCase):
    def test_front_top_bottom_show_model_and_save_matching_camera(self):
        import numpy as np
        import trimesh
        from PIL import Image

        artifact_root = os.environ.get("PRINT3D_TEST_ARTIFACT_DIR")
        if artifact_root:
            Path(artifact_root).mkdir(parents=True, exist_ok=True)
            root = Path(tempfile.mkdtemp(prefix="views-", dir=artifact_root))
        else:
            temporary = tempfile.TemporaryDirectory()
            self.addCleanup(temporary.cleanup)
            root = Path(temporary.name)
        base = trimesh.creation.box(extents=(30, 20, 6))
        base.apply_translation((0, 0, 3))
        tower = trimesh.creation.box(extents=(10, 20, 24))
        tower.apply_translation((-10, 0, 18))
        source = root / "asymmetric.stl"
        trimesh.boolean.union([base, tower], engine="manifold").export(source)
        original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        reports = {}
        for view in ("front", "top", "bottom"):
            png, blend = root / f"{view}.png", root / f"{view}.blend"
            command = [os.environ["PRINT3D_TEST_BLENDER"], "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(SCRIPTS / "render_preview.py"), "--", "--input", str(source), "--output", str(png), "--blend-output", str(blend), "--resolution", "256", "--view", view]
            result = subprocess.run(command, capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            report = next(json.loads(line) for line in result.stdout.decode(errors="replace").splitlines() if line.startswith('{"preview":'))
            reports[view] = report
            self.assertEqual(report["view"], view)
            self.assertEqual(report["source_extents_mm"], [30, 20, 30])
            self.assertAlmostEqual(report["ortho_scale"], 38.4, places=4)
            self.assertEqual(report["camera_target"], [0, 0, 15])
            with Image.open(png) as image:
                pixels = np.asarray(image.convert("RGB"), dtype=float)
            blue_model = (pixels[:, :, 2] > pixels[:, :, 0] * 1.15) & (pixels[:, :, 1] > pixels[:, :, 0] * 1.15)
            self.assertGreater(blue_model.mean(), 0.05, f"{view}: model hidden or missing")
            self.assertLess(blue_model.mean(), 0.85, f"{view}: model crops the frame")
        self.assertNotEqual((root / "front.png").read_bytes(), (root / "top.png").read_bytes())
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash)

        # Read saved .blend files in Blender to check actual scene state, not
        # merely the requested flags or reported values.
        probe = root / "verify_saved_scenes.py"
        probe.write_text('''import bpy, json, sys
from pathlib import Path
from mathutils import Vector
root = Path(sys.argv[sys.argv.index("--") + 1])
directions = {"front": (0, -1, 0), "top": (0, 0, 1), "bottom": (0, 0, -1)}
for view, direction in directions.items():
    bpy.ops.wm.open_mainfile(filepath=str(root / (view + ".blend")))
    scene = bpy.context.scene
    camera = scene.camera
    target = Vector((0, 0, 15))
    assert camera.data.type == "ORTHO"
    assert (camera.location - target).normalized().dot(Vector(direction)) > 0.99999
    forward = camera.matrix_world.to_quaternion() @ Vector((0, 0, -1))
    assert forward.normalized().dot((target - camera.location).normalized()) > 0.99999
    assert abs(camera.data.ortho_scale - 38.4) < 0.0001
    ground = bpy.data.objects["Preview Ground (not part of STL)"]
    assert ground.hide_render == (view == "bottom")
    models = [obj for obj in scene.objects if obj.type == "MESH" and obj != ground]
    assert len(models) == 1 and len(models[0].data.polygons) > 0
    assert abs(scene.unit_settings.scale_length - 0.001) < 1e-8
print(json.dumps({"saved_scenes_verified": list(directions)}))
''', encoding="utf-8")
        verified = subprocess.run([os.environ["PRINT3D_TEST_BLENDER"], "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(probe), "--", str(root)], capture_output=True, timeout=90)
        self.assertEqual(verified.returncode, 0, verified.stdout.decode(errors="replace") + verified.stderr.decode(errors="replace"))
        (root / "views.json").write_text(json.dumps({"source_sha256": original_hash, "renders": reports}, indent=2), encoding="utf-8")

    def test_render_and_explicit_overwrite_preserve_mesh(self):
        import trimesh
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "cube.stl"
            trimesh.creation.box(extents=(10, 20, 30)).export(source)
            original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            png, blend = root / "preview.png", root / "preview.blend"
            command = [os.environ["PRINT3D_TEST_BLENDER"], "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(SCRIPTS / "render_preview.py"), "--", "--input", str(source), "--output", str(png), "--blend-output", str(blend), "--resolution", "256"]
            first = subprocess.run(command, capture_output=True, timeout=90)
            self.assertEqual(first.returncode, 0, first.stderr.decode(errors="replace"))
            hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (png, blend)]
            rejected = subprocess.run(command, capture_output=True, timeout=90)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(hashes, [hashlib.sha256(path.read_bytes()).hexdigest() for path in (png, blend)])
            replaced = subprocess.run([*command, "--overwrite"], capture_output=True, timeout=90)
            self.assertEqual(replaced.returncode, 0, replaced.stderr.decode(errors="replace"))
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash)
            self.assertGreater(png.stat().st_size, 100)
            self.assertGreater(blend.stat().st_size, 100)


if __name__ == "__main__":
    unittest.main()
