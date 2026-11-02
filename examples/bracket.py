"""Editable 60 x 36 x 32 mm bracket; a toolchain example, not load-rated hardware."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cadquery as cq

WIDTH, DEPTH, HEIGHT, WALL = 60.0, 36.0, 32.0, 4.0
HOLE_DIAMETER = 4.5
LINEAR_DEFLECTION = 0.05  # mm; absolute, not relative to edge size
ANGULAR_DEFLECTION = 0.1  # radians


def build_bracket() -> cq.Shape:
    base = cq.Workplane("XY").box(WIDTH, DEPTH, WALL, centered=(True, True, False))
    upright = (
        cq.Workplane("XY")
        .box(WIDTH, WALL, HEIGHT - WALL, centered=(True, True, False))
        .translate((0, DEPTH / 2 - WALL / 2, WALL))
    )
    part = base.union(upright).edges("|Z").fillet(1.0)
    for x in (-20.0, 20.0):
        base_hole = cq.Solid.makeCylinder(
            HOLE_DIAMETER / 2, WALL + 2, cq.Vector(x, -5, -1), cq.Vector(0, 0, 1)
        )
        wall_hole = cq.Solid.makeCylinder(
            HOLE_DIAMETER / 2, WALL + 2,
            cq.Vector(x, DEPTH / 2 - WALL - 1, 21), cq.Vector(0, 1, 0),
        )
        part = part.cut(base_hole).cut(wall_hole)
    return part.val()


def dimensions(shape: cq.Shape) -> list[float]:
    box = shape.BoundingBox()
    return [box.xlen, box.ylen, box.zlen]


def check_shape(shape: cq.Shape) -> None:
    if not shape.isValid() or len(shape.Solids()) != 1:
        raise ValueError("Expected one valid CAD solid")
    if any(not math.isclose(a, b, abs_tol=1e-6) for a, b in
           zip(dimensions(shape), (WIDTH, DEPTH, HEIGHT))):
        raise ValueError("Unexpected bracket dimensions")


def export_bracket(output_dir: Path, *, overwrite: bool = False) -> dict:
    output_dir = output_dir.resolve()
    targets = [output_dir / name for name in
               ("bracket.step", "bracket.stl", "cad_checks.json")]
    # Check all destinations before writing any artifact. Reject aliases to this source.
    source = Path(__file__).resolve()
    for target in targets:
        if target.resolve() == source or (target.exists() and target.samefile(source)):
            raise ValueError("An export destination aliases the editable source")
        if target.is_symlink():
            raise ValueError(f"Export destination is a symlink: {target}")
        if target.exists() and (not overwrite or not target.is_file()):
            raise FileExistsError(f"Refusing to replace {target}; use --overwrite for generated files")
    shape = build_bracket()
    check_shape(shape)
    # Capture analytic CAD bounds before tessellation populates OCCT's mesh cache;
    # later fast bounding boxes may include triangulation deflection margins.
    cad_extents = dimensions(shape)
    hole_faces = [face for face in shape.Faces()
                  if face.geomType() == "CYLINDER" and math.isclose(
                      face._geomAdaptor().Cylinder().Radius(), HOLE_DIAMETER / 2,
                      abs_tol=1e-6)]
    if len(hole_faces) != 4:
        raise ValueError("Expected four cylindrical hole walls")
    output_dir.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(shape, str(targets[0]))
    if not shape.exportStl(str(targets[1]), tolerance=LINEAR_DEFLECTION,
                           angularTolerance=ANGULAR_DEFLECTION, relative=False):
        raise RuntimeError("STL export failed")
    roundtrip = cq.importers.importStep(str(targets[0])).val()
    check_shape(roundtrip)
    if not math.isclose(shape.Volume(), roundtrip.Volume(), rel_tol=1e-8):
        raise ValueError("STEP round trip changed the volume")
    report = {
        "cad_valid": True, "solid_count": 1, "units": "mm",
        "extents_mm": cad_extents, "volume_mm3": shape.Volume(),
        "hole_diameter_mm": HOLE_DIAMETER, "verified_hole_count": len(hole_faces),
        "step_roundtrip_valid": True, "step_volume_mm3": roundtrip.Volume(),
        "linear_tessellation_tolerance_mm": LINEAR_DEFLECTION,
        "angular_tessellation_tolerance_radians": ANGULAR_DEFLECTION,
        "relative_tessellation": False,
        "scope": "Toolchain demonstration; not load-rated, sliced or physically printed.",
    }
    targets[2].write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(export_bracket(args.output_dir, overwrite=args.overwrite), indent=2))
    except (ValueError, FileExistsError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
