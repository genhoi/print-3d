# CadQuery modeling and export

Keep dimensional CAD as editable Python source and export STEP when a solid representation is useful. STEP preserves geometry, not the procedural history of a CadQuery script. The examples below are checked with CadQuery 2.8.

## Place and select features deliberately

A Workplane has a local coordinate system and a stack of selected objects. After selecting a face, create a workplane before sketching. Its default `centerOption="ProjectedOrigin"` projects the previous origin onto that face; it does not necessarily choose the face center. Specify `centerOption` when positioning matters and express feature coordinates relative to that chosen origin.

Check selection cardinality before applying a feature. `faces(">Z")` selects by the greatest face-center coordinate; `faces("|Z")` matches planar faces whose normals are parallel to Z, including both ends of a box. Sorted index selections can change after fillets or other features. Tags can retain an earlier Workplane selection, but do not assume they remap an old face onto changed topology.

This plate starts at the global origin. Its hole coordinates are local to the top face's bounding-box center, so changing width or depth retains the specified edge inset:

```python
import math
import cadquery as cq


def build_plate(width=40.0, depth=24.0, thickness=4.0,
                hole_diameter=4.0, inset=6.0):
    values = (width, depth, thickness, hole_diameter, inset)
    if not all(math.isfinite(v) and v > 0 for v in values):
        raise ValueError("Dimensions must be finite and positive")
    if inset <= hole_diameter / 2 or min(width, depth) <= 2 * inset + hole_diameter:
        raise ValueError("Holes must remain separate and inside the plate")
    base = cq.Workplane("XY").box(
        width, depth, thickness, centered=(False, False, False))
    top = base.faces(">Z")
    if top.size() != 1:
        raise ValueError("Expected one top face")
    centers = [(x, y) for x in (-width / 2 + inset, width / 2 - inset)
               for y in (-depth / 2 + inset, depth / 2 - inset)]
    return (top.workplane(centerOption="CenterOfBoundBox")
            .pushPoints(centers).hole(hole_diameter))


model = build_plate()
```

`tests/test_cadquery_patterns.py` runs this exact example and checks hole locations, diameters, through-depth, volume and a changed parameter set. It also checks the documented selector behavior. These are geometry checks, not a claim about printer accuracy or fit.

`Workplane.translate()` is valid and moves its geometry in global coordinates. A Workplane and a Shape are different API objects; convert intentionally when passing geometry to a Shape-based operation. `.val()` returns the first stack item, which can itself be a compound. Inspect both the stack and `model.solids().size()` before exporting. For multiple printable bodies, use `model.solids().vals()` and export them separately or explicitly construct a `cq.Compound.makeCompound(bodies)`; do not silently discard later stack items.

## Export and reimport

In CadQuery 2.8 the STL branch of `cq.exporters.export` uses `Shape.exportStl`'s default relative deflection. Passing `opt={"relative": False}` to that wrapper does not change it. Set the option on the shape directly:

```python
if model.solids().size() != 1:
    raise ValueError("This export expects exactly one solid")
shape = model.solids().val()
assert shape.isValid()
ok = shape.exportStl(
    str(stl_path),
    tolerance=0.05,        # absolute linear deflection in model mm
    angularTolerance=0.1, # radians
    relative=False,
)
if not ok:
    raise RuntimeError("STL export failed")
cq.exporters.export(shape, str(step_path))
```

Use a fresh shape when comparing tessellation settings: a CAD kernel may cache an existing triangulation. Reduce deflection for small features or large curves when the output dimensions need closer agreement. A surface deflection bound does not guarantee that an axis-aligned bounding box matches the CAD dimensions within that same bound: extrema can fall between mesh vertices. Verify both CAD dimensions and actual export bounds instead of relaxing a failed dimensional test blindly.

Reimport delivered STEP files and compare validity, solid count, bounds and volume. Preserve cavities' boundary orientation. The runnable `examples/bracket.py` includes STEP round-trip and export checks; the mesh inspector checks the delivered mesh separately.
