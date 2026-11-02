"""Execute the documented CAD pattern and inspect its resulting features."""
from __future__ import annotations

import math
from pathlib import Path
import re
import unittest

import cadquery as cq

REFERENCE = Path(__file__).resolve().parents[1] / "references" / "cadquery.md"
example = re.search(r"```python\n(.*?)\n```", REFERENCE.read_text(encoding="utf-8"), re.S)
if example is None:
    raise RuntimeError("Missing executable CadQuery reference example")
namespace = {}
exec(compile(example.group(1), str(REFERENCE), "exec"), namespace)
build_plate = namespace["build_plate"]


class CadQueryPatternTests(unittest.TestCase):
    def test_parameters_preserve_hole_positions_and_through_depth(self):
        for width, depth, thickness, diameter, inset in (
                (40, 24, 4, 4, 6), (58, 34, 6, 5, 8)):
            with self.subTest(width=width, depth=depth):
                model = build_plate(width, depth, thickness, diameter, inset)
                self.assertEqual(model.solids().size(), 1)
                shape = model.solids().val()
                self.assertTrue(shape.isValid())
                box = shape.BoundingBox()
                for actual, expected in zip((box.xlen, box.ylen, box.zlen),
                                            (width, depth, thickness)):
                    self.assertAlmostEqual(actual, expected, places=6)
                self.assertAlmostEqual(shape.Volume(),
                    width * depth * thickness - math.pi * diameter ** 2 * thickness,
                    places=6)
                walls = [f for f in shape.Faces() if f.geomType() == "CYLINDER"]
                self.assertEqual(len(walls), 4)
                measured_centers = []
                for face in walls:
                    bounds = face.BoundingBox()
                    self.assertAlmostEqual(bounds.xlen, diameter, places=6)
                    self.assertAlmostEqual(bounds.ylen, diameter, places=6)
                    self.assertAlmostEqual(bounds.zlen, thickness, places=6)
                    measured_centers.append(((bounds.xmin + bounds.xmax) / 2,
                                             (bounds.ymin + bounds.ymax) / 2))
                for x in (inset, width - inset):
                    for y in (inset, depth - inset):
                        self.assertTrue(any(math.hypot(cx - x, cy - y) < 1e-6
                                            for cx, cy in measured_centers))
                        for z in (0.1, thickness / 2, thickness - 0.1):
                            self.assertFalse(shape.isInside(cq.Vector(x, y, z)))
                            self.assertTrue(shape.isInside(cq.Vector(
                                x + diameter / 2 + 0.1, y, z)))

    def test_selector_cardinality_and_global_translation(self):
        box = cq.Workplane("XY").box(10, 12, 4)
        self.assertEqual(box.faces(">Z").size(), 1)
        self.assertEqual(box.faces("|Z").size(), 2)
        moved = box.translate((5, 7, 9)).val().Center()
        for actual, expected in zip(moved.toTuple(), (5, 7, 9)):
            self.assertAlmostEqual(actual, expected, places=6)

    def test_val_does_not_collect_a_multi_item_stack(self):
        bodies = (cq.Workplane("XY").pushPoints([(-10, 0), (10, 0)])
                  .box(4, 4, 4, combine=False))
        self.assertEqual(len(bodies.vals()), 2)
        self.assertEqual(bodies.solids().size(), 2)
        self.assertAlmostEqual(bodies.val().Volume(), 64)
        compound = cq.Compound.makeCompound(bodies.solids().vals())
        self.assertEqual(len(compound.Solids()), 2)
        self.assertAlmostEqual(compound.Volume(), 128)

    def test_invalid_hole_layout_is_rejected(self):
        with self.assertRaises(ValueError):
            build_plate(depth=14, hole_diameter=4, inset=6)


if __name__ == "__main__":
    unittest.main()
