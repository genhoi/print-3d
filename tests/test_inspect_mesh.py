"""Regression checks for real exports, nested shells, units and output safety."""
import argparse
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import trimesh

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inspect_mesh.py"
SPEC = importlib.util.spec_from_file_location("mesh_inspector", SCRIPT)
inspector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspector)


def box(size, center=(0, 0, 0), inverse=False):
    result = trimesh.creation.box(extents=[size] * 3 if np.isscalar(size) else size)
    result.apply_translation(center)
    if inverse:
        result.invert()
    return result


class InspectMeshTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="print3d-inspect-")
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def export(self, mesh, name="model.stl"):
        path = self.root / name
        mesh.export(path)
        return path

    def inspect(self, path, expected_components=1, expected_extents=None, **overrides):
        options = dict(path=path, output=None, overwrite=False, expected_components=expected_components,
                       expect_extents=expected_extents, extent_tolerance=0.05, units=None)
        options.update(overrides)
        return inspector.inspect(argparse.Namespace(**options))

    def cli(self, path, *arguments):
        completed = subprocess.run([sys.executable, str(SCRIPT), str(path), *map(str, arguments)],
                                   capture_output=True, text=True, encoding="utf-8", timeout=60)
        return completed, json.loads(completed.stdout)

    def gltf_primitive_scene(self, suffix, mode):
        scene = trimesh.Scene()
        scene.add_geometry(box(0.01), geom_name="regular")
        scene.add_geometry(box((0.02, 0.01, 0.01)), geom_name="other",
                           transform=trimesh.transformations.translation_matrix((0.03, 0, 0)))

        def set_mode(document):
            other = next(mesh for mesh in document["meshes"] if mesh["name"] == "other")
            original = other["primitives"][0]
            accessor = document["accessors"][original["indices"]]
            item_size = {5121: 1, 5123: 2, 5125: 4}[accessor["componentType"]]
            other["primitives"] = []
            # Three-index fans and strips represent exactly the same triangle
            # as TRIANGLES, so every generated fixture remains a closed box.
            for face in range(accessor["count"] // 3):
                triangle = dict(accessor, count=3,
                                byteOffset=accessor.get("byteOffset", 0) + face * 3 * item_size)
                triangle.pop("min", None)
                triangle.pop("max", None)
                document["accessors"].append(triangle)
                other["primitives"].append(dict(original, mode=mode,
                                                 indices=len(document["accessors"]) - 1))

        path = self.root / f"primitive-mode-{mode}{suffix}"
        if suffix == ".glb":
            path.write_bytes(trimesh.exchange.gltf.export_glb(scene, tree_postprocessor=set_mode))
        else:
            exports = trimesh.exchange.gltf.export_gltf(scene, embed_buffers=True, tree_postprocessor=set_mode)
            path.write_bytes(next(value for name, value in exports.items() if name.endswith(".gltf")))
        return path

    def assert_passed(self, report):
        self.assertTrue(report["passed"], report.get("errors"))

    def test_closed_cavity_is_one_material_body(self):
        path = self.export(trimesh.util.concatenate([box(20), box(10, inverse=True)]))
        report = self.inspect(path, expected_extents=[20, 20, 20])
        self.assert_passed(report)
        self.assertEqual((report["material_bodies"], report["surface_shells"], report["internal_voids"]), (1, 2, 1))
        self.assertAlmostEqual(report["signed_volume_mm3"], 7000)
        self.assertAlmostEqual(report["bodies"][0]["material_volume_mm3"], 7000)
        self.assertEqual(sorted(s["nesting_depth"] for s in report["shells"]), [0, 1])

    def test_nested_material_island_is_another_body(self):
        path = self.export(trimesh.util.concatenate([box(20), box(10, inverse=True), box(4)]))
        report = self.inspect(path, expected_components=2)
        self.assert_passed(report)
        self.assertEqual((report["material_bodies"], report["surface_shells"], report["internal_voids"]), (2, 3, 1))
        self.assertAlmostEqual(sum(b["material_volume_mm3"] for b in report["bodies"]), 7064)
        self.assertEqual(sorted(s["nesting_depth"] for s in report["shells"]), [0, 1, 2])

    def test_disjoint_bodies_and_expected_count(self):
        path = self.export(trimesh.util.concatenate([box(10), box(6, center=(20, 0, 0))]))
        self.assert_passed(self.inspect(path, expected_components=2))
        report = self.inspect(path)
        self.assertFalse(report["passed"])
        self.assertTrue(any("Expected 1 material bodies, found 2" in e for e in report["errors"]))

    def test_inverted_independent_shell_is_rejected(self):
        self.assertFalse(self.inspect(self.export(box(10, inverse=True)))["passed"])
        path = self.export(trimesh.util.concatenate([box(20), box(4, center=(30, 0, 0), inverse=True)]), "mixed.stl")
        report = self.inspect(path, expected_components=2)
        self.assertFalse(report["passed"])
        self.assertTrue(any("must be oriented outward" in e for e in report["errors"]))

    def test_positive_nested_shell_is_not_a_cavity(self):
        path = self.export(trimesh.util.concatenate([box(20), box(10)]))
        report = self.inspect(path)
        self.assertFalse(report["passed"])
        self.assertTrue(any("inward toward the void" in e for e in report["errors"]))

    def test_touching_internal_and_external_surfaces_are_rejected(self):
        models = [
            trimesh.util.concatenate([box(20), box(10, center=(5, 0, 0), inverse=True)]),
            trimesh.util.concatenate([box(10), box(10, center=(10, 2, 0))]),
        ]
        for index, model in enumerate(models):
            with self.subTest(index=index):
                report = self.inspect(self.export(model, f"contact{index}.stl"), expected_components=2)
                self.assertFalse(report["passed"])
                self.assertTrue(any("touch" in e or "intersect" in e or "watertight" in e for e in report["errors"]), report["errors"])

    def test_partial_overlaps_are_rejected(self):
        path = self.export(trimesh.util.concatenate([box(10), box(10, center=(5, 0, 0))]))
        report = self.inspect(path, expected_components=2)
        self.assertFalse(report["passed"])
        self.assertTrue(any("partially overlap" in e for e in report["errors"]))

    def test_concave_containment_is_not_decided_by_vertices(self):
        outer = trimesh.boolean.difference([box(20), box((2, 25, 10), center=(0, 0, 5))], engine="manifold")
        inner = box((16, 16, 8), center=(0, 0, 3), inverse=True)
        self.assertTrue(outer.contains(inner.vertices).all())
        report = self.inspect(self.export(trimesh.util.concatenate([outer, inner])))
        self.assertFalse(report["passed"])
        self.assertTrue(any("partially overlap" in e for e in report["errors"]))

    def test_correct_cavity_in_concave_body(self):
        outer = trimesh.boolean.difference([box(20), box((2, 25, 10), center=(0, 0, 5))], engine="manifold")
        inner = box(3, center=(5, 0, -4), inverse=True)
        self.assert_passed(self.inspect(self.export(trimesh.util.concatenate([outer, inner]))))

    def test_empty_degenerate_and_open_meshes_fail(self):
        empty = self.root / "empty.stl"
        empty.write_text("solid empty\nendsolid empty\n", encoding="ascii")
        result, report = self.cli(empty)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(report["passed"])
        damaged = box(10)
        damaged.update_faces(np.arange(len(damaged.faces)) != 0)
        self.assertFalse(self.inspect(self.export(damaged, "open.stl"))["passed"])
        model = box(10)
        model.faces = np.vstack([model.faces, [0, 0, 1]])
        report = self.inspect(self.export(model, "degenerate.stl"))
        self.assertFalse(report["passed"])
        self.assertGreater(report["degenerate_faces"], 0)

    def test_nonfinite_tolerance_is_a_structured_error(self):
        path = self.export(box(10))
        for value in ("inf", "nan", "-inf"):
            for expected in ([], ["--expect-extents", "10", "10", "10"]):
                with self.subTest(value=value, expected=bool(expected)):
                    result, report = self.cli(path, f"--extent-tolerance={value}", *expected)
                    self.assertEqual(result.returncode, 1)
                    self.assertFalse(report["passed"])
                    self.assertIn("finite and nonnegative", report["errors"][0])
                    self.assertNotIn("Traceback", result.stderr)

    def test_existing_report_requires_explicit_overwrite(self):
        path = self.export(box(10))
        target = self.root / "checks.json"
        target.write_text("KEEP", encoding="utf-8")
        result, report = self.cli(path, "--output", target)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(target.read_text(), "KEEP")
        self.assertIn("already exists", report["errors"][0])
        result, report = self.cli(path, "--output", target, "--overwrite")
        self.assertEqual(result.returncode, 0)
        self.assert_passed(report)
        self.assert_passed(json.loads(target.read_text()))

    def test_input_and_hardlink_are_never_report_targets(self):
        path = self.export(box(10))
        original = path.read_bytes()
        targets = [path]
        alias = self.root / "alias.json"
        try:
            os.link(path, alias)
            targets.append(alias)
        except OSError:
            pass
        for target in targets:
            result, report = self.cli(path, "--output", target, "--overwrite")
            self.assertEqual(result.returncode, 1)
            self.assertIn("source mesh", report["errors"][0])
            self.assertEqual(path.read_bytes(), original)

    def test_glb_instances_transforms_and_metres(self):
        scene = trimesh.Scene()
        geometry = box((0.01, 0.02, 0.03))
        scene.add_geometry(geometry, geom_name="part", node_name="first")
        transform = np.eye(4)
        transform[0, 0] = -1
        transform[0, 3] = 0.04
        scene.graph.update(frame_to="second", geometry="part", matrix=transform)
        path = self.root / "instances.glb"
        path.write_bytes(scene.export(file_type="glb"))
        report = self.inspect(path, expected_components=2, expected_extents=[50, 20, 30])
        self.assert_passed(report)
        self.assertEqual(report["scale_to_mm"], 1000)
        self.assertEqual(report["scene_instances"], 2)

    def test_glb_visual_seams_do_not_split_a_solid(self):
        original = box((0.01, 0.02, 0.03))
        vertices = original.vertices[original.faces].reshape((-1, 3))
        # Every triangle has its own vertices and UV coordinates, as a textured
        # export can legitimately have. Geometry must weld across these seams.
        split = trimesh.Trimesh(vertices=vertices, faces=np.arange(len(vertices)).reshape((-1, 3)), process=False)
        split.visual = trimesh.visual.TextureVisuals(uv=np.arange(len(vertices) * 2).reshape((-1, 2)) / 100)
        path = self.root / "seams.glb"
        path.write_bytes(trimesh.Scene(split).export(file_type="glb"))
        report = self.inspect(path, expected_extents=[10, 20, 30])
        self.assert_passed(report)
        self.assertEqual(report["vertices_before_weld"], 36)
        self.assertEqual(report["vertices"], 8)

    def test_gltf_triangle_fans_fail_instead_of_silently_losing_geometry(self):
        for suffix in (".gltf", ".glb"):
            with self.subTest(suffix=suffix):
                # The regular cube alone matches the default body count, so
                # silently dropping the fan cube would produce a false pass.
                result, report = self.cli(self.gltf_primitive_scene(suffix, mode=6))
                self.assertEqual(result.returncode, 1)
                self.assertFalse(report["passed"])
                self.assertIn("Unsupported glTF primitive mode 6", report["errors"][0])
                self.assertNotIn("Traceback", result.stderr)

    def test_gltf_triangles_and_strips_keep_all_bodies(self):
        for suffix in (".gltf", ".glb"):
            for mode in (4, 5):
                with self.subTest(suffix=suffix, mode=mode):
                    path = self.gltf_primitive_scene(suffix, mode)
                    report = self.inspect(path, expected_components=2, expected_extents=[45, 10, 10])
                    self.assert_passed(report)
                    self.assertAlmostEqual(report["signed_volume_mm3"], 3000, places=3)

    def test_gltf_gpu_instances_fail_instead_of_silently_losing_geometry(self):
        scene = trimesh.Scene(box(0.01))

        def add_instances(document):
            translations = np.asarray(((0, 0, 0), (0.03, 0, 0)), dtype="<f4").tobytes()
            document["buffers"].append({
                "byteLength": len(translations),
                "uri": "data:application/octet-stream;base64," + base64.b64encode(translations).decode("ascii"),
            })
            document["bufferViews"].append({"buffer": len(document["buffers"]) - 1,
                                             "byteLength": len(translations)})
            document["accessors"].append({"bufferView": len(document["bufferViews"]) - 1,
                                           "componentType": 5126, "count": 2, "type": "VEC3"})
            node = next(node for node in document["nodes"] if "mesh" in node)
            node["extensions"] = {"EXT_mesh_gpu_instancing": {
                "attributes": {"TRANSLATION": len(document["accessors"]) - 1}
            }}
            document["extensionsUsed"] = ["EXT_mesh_gpu_instancing"]
            document["extensionsRequired"] = ["EXT_mesh_gpu_instancing"]

        for suffix in (".gltf", ".glb"):
            with self.subTest(suffix=suffix):
                path = self.root / f"gpu-instances{suffix}"
                if suffix == ".glb":
                    path.write_bytes(trimesh.exchange.gltf.export_glb(scene, tree_postprocessor=add_instances))
                else:
                    exports = trimesh.exchange.gltf.export_gltf(scene, embed_buffers=True)
                    document = json.loads(next(value for name, value in exports.items() if name.endswith(".gltf")))
                    add_instances(document)
                    path.write_text(json.dumps(document), encoding="utf-8")
                result, report = self.cli(path)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(report["passed"])
                self.assertIn("Unsupported glTF node extension EXT_mesh_gpu_instancing", report["errors"][0])
                self.assertNotIn("Traceback", result.stderr)

    def test_3mf_declared_units_are_converted_once(self):
        blob = trimesh.Scene(box((1, 2, 3))).export(file_type="3mf")
        for unit, factor in (("millimeter", 1), ("inch", 25.4)):
            with self.subTest(unit=unit):
                path = self.root / f"units-{unit}.3mf"
                with zipfile.ZipFile(io.BytesIO(blob)) as source, zipfile.ZipFile(path, "w") as target:
                    for member in source.infolist():
                        content = source.read(member.filename)
                        if member.filename.endswith(".model"):
                            model = ET.fromstring(content)
                            model.set("unit", unit)
                            content = ET.tostring(model, encoding="utf-8", xml_declaration=True)
                        target.writestr(member, content)
                report = self.inspect(path, expected_extents=[factor, 2 * factor, 3 * factor])
                self.assert_passed(report)
                self.assertEqual(report["scale_to_mm"], factor)

    def test_3mf_body_name_collisions_preserve_original_geometry(self):
        scene = trimesh.Scene()
        scene.add_geometry(box(10), geom_name="Body1", node_name="Bracket(1)")
        scene.add_geometry(box((20, 10, 10)), geom_name="Body2", node_name="Bracket(2)",
                           transform=trimesh.transformations.translation_matrix((30, 0, 0)))
        blob = scene.export(file_type="3mf")
        path = self.root / "named-assembly.3mf"
        # Build real parent/component objects. The 3MF loader's optional
        # SolidWorks renamer strips the (instance) suffix from these parents,
        # causing both differently sized Body children to become "Bracket".
        with zipfile.ZipFile(io.BytesIO(blob)) as source, zipfile.ZipFile(path, "w") as target:
            for member in source.infolist():
                content = source.read(member.filename)
                if member.filename.endswith(".model"):
                    model = ET.fromstring(content)
                    ns = "{" + model.tag.split("}")[0].lstrip("{") + "}"
                    resources = model.find(ns + "resources")
                    build = model.find(ns + "build")
                    objects = {obj.get("name"): obj for obj in resources.findall(ns + "object")}
                    for index, (body_name, parent_name) in enumerate(
                        (("Body1", "Bracket(1)"), ("Body2", "Bracket(2)")), start=3
                    ):
                        child = objects[body_name]
                        parent = ET.SubElement(resources, ns + "object", id=str(index),
                                               type="model", name=parent_name)
                        components = ET.SubElement(parent, ns + "components")
                        ET.SubElement(components, ns + "component", objectid=child.get("id"))
                        for item in build.findall(ns + "item"):
                            if item.get("objectid") == child.get("id"):
                                item.set("objectid", parent.get("id"))
                    content = ET.tostring(model, encoding="utf-8", xml_declaration=True)
                target.writestr(member, content)
        report = self.inspect(path, expected_components=2, expected_extents=[45, 10, 10])
        self.assert_passed(report)
        self.assertEqual(report["scene_instances"], 2)
        self.assertAlmostEqual(report["signed_volume_mm3"], 3000)
        self.assertEqual(sorted(round(body["material_volume_mm3"]) for body in report["bodies"]), [1000, 2000])


if __name__ == "__main__":
    unittest.main()
