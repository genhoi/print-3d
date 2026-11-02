"""Behavioral CAD/export checks: actual geometry, not source-text matching."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import cadquery as cq
import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bracket", ROOT / "examples" / "bracket.py")
bracket = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bracket)


class CadQueryExportTests(unittest.TestCase):
    def test_bracket_step_and_actual_mesh(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            report = bracket.export_bracket(output)
            step = cq.importers.importStep(str(output / "bracket.step")).val()
            self.assertTrue(step.isValid())
            self.assertEqual(len(step.Solids()), 1)
            np.testing.assert_allclose(bracket.dimensions(step), [60, 36, 32], atol=1e-6)
            self.assertAlmostEqual(step.Volume(), report["volume_mm3"], places=6)
            mesh = trimesh.load_mesh(output / "bracket.stl")
            self.assertTrue(mesh.is_watertight)
            self.assertTrue(mesh.is_winding_consistent)
            np.testing.assert_allclose(mesh.extents, [60, 36, 32], atol=0.05)
            self.assertLess(abs(mesh.volume / step.Volume() - 1), 0.002)
            # Check the intended voids in exported CAD, not just the outer dimensions.
            for x in (-20, 20):
                self.assertFalse(step.isInside(cq.Vector(x, -5, 2)))
                self.assertFalse(step.isInside(cq.Vector(x, 16, 21)))
            self.assertTrue(step.isInside(cq.Vector(0, 0, 2)))
            self.assertEqual(json.loads((output / "cad_checks.json").read_text())["verified_hole_count"], 4)

    def test_large_curve_absolute_tessellation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large_disk.stl"
            # A large radius exposes accidental relative deflection in CQ's exporter wrapper.
            shape = cq.Workplane("XY").circle(150).extrude(20).val()
            self.assertTrue(shape.exportStl(str(path), tolerance=0.01,
                                           angularTolerance=0.1, relative=False))
            mesh = trimesh.load_mesh(path)
            np.testing.assert_allclose(mesh.extents, [300, 300, 20], atol=0.05, rtol=0)
            self.assertTrue(mesh.is_volume)

    def test_existing_output_preserved_before_any_export(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            sentinel = output / "cad_checks.json"
            sentinel.write_text("preserve me")
            with self.assertRaises(FileExistsError):
                bracket.export_bracket(output)
            self.assertEqual(sentinel.read_text(), "preserve me")
            self.assertFalse((output / "bracket.stl").exists())
            self.assertFalse((output / "bracket.step").exists())


if __name__ == "__main__":
    unittest.main()
