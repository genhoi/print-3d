# OpenSCAD modeling

Preserve an existing project's OpenSCAD style and dependencies. Use plain OpenSCAD when it suffices. BOSL2 can help with anchors, rounded shapes and attachments, but is optional: verify the required library and include search path before using it. A successful OpenSCAD version check does not verify library availability.

## Parameters and coordinates

Keep user-facing dimensions at the top with Customizer groups and ranges. Put derived values and implementation settings in `[Hidden]`; parameter changes should recompute dependent geometry. Use `assert()` for constraints that prevent invalid dimensions, intersecting holes or vanishing walls. Echo nominal dimensions and feature locations so they can be compared with the exported mesh.

Choose a coordinate convention explicitly. In plain OpenSCAD use `center=true` or `center=false` intentionally; do not assume that a BOSL2 primitive has the same default anchor. Keep the finished part's intended base at Z=0 when that suits the selected print orientation.

Extend Boolean cutters a small distance beyond both surfaces to avoid coincident faces. This numerical `epsilon` is not a fit allowance and must not change the specified hole diameter or mating surface. Define functional clearances separately, state whether they apply to a diameter or each side, and use measured project information when available. No universal clearance or wall thickness is assumed here.

## Curves and checks

`$fa` bounds angular fragment size and `$fs` controls fragment size in model units when `$fn=0`; a positive `$fn` overrides them. Set resolution for the smallest relevant feature, then measure the exported polygons. A nominal circular hole becomes a polygon, so its available clearance can be smaller than the nominal diameter. Neither a high facet count nor a smooth preview proves fit.

`examples/parametric_plate.scad` is a 40 x 24 x 4 mm plate with four nominal 4 mm through-holes, centered 6 mm from the neighboring edges. It has no external library dependency. For a fresh output location:

```sh
python scripts/run_3d.py scad -o outputs/plate.stl examples/parametric_plate.scad
python scripts/run_3d.py inspect outputs/plate.stl --expect-extents 40 24 4 --expected-components 1 --output outputs/plate-mesh.json
python scripts/run_3d.py render --input outputs/plate.stl --output outputs/plate.png
```

Create the output directory first. The launcher protects explicit `-o` outputs; replacing a generated export requires `--overwrite`. Use a fresh directory for animation or auxiliary outputs, which this guard does not enumerate. The launcher treats warnings as errors. An AST/syntax check is not a replacement for exporting the final geometry. After export, inspect topology and dimensions, check critical holes or sections, and examine the actual mesh preview. Override source parameters with separate arguments such as `-D 'width=58' -D 'depth=34'`; repeat the checks with the changed expected dimensions.
