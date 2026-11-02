---
name: print-3d
description: Create, edit and verify local 3D-printable models with CadQuery, Blender and OpenSCAD. Use for dimensioned parts, STL/STEP/3MF files, procedural forms and mesh inspection. Preserve editable sources, check exported geometry and inspect previews. Does not provide neural image-to-3D generation or operate physical printers.
---

# Printable 3D models

Use [references/toolchain.md](references/toolchain.md) to discover and run local tools. Do not assume a particular operating system, executable path, printer, material or nozzle. Configuration stays in an ignored local file; no MCP server or paid API is required for this workflow.

## Select the tool

- **CadQuery:** dimensioned mechanical parts, mating features, holes, fillets and STEP output. Keep dimensions and fit tolerances explicit in an editable Python source. Read [CAD modeling and export](references/cadquery.md).
- **Blender:** procedural or organic forms, imported meshes and visual inspection. Preserve an editable `.blend` or a generation script. Surface color and texture do not create printable relief. Read [Blender context and export](references/blender.md).
- **OpenSCAD:** existing `.scad` designs and constructive solid geometry. Preserve the source format when it fits the requested change. Read [OpenSCAD parameters and Booleans](references/openscad.md).
- **trimesh + manifold3d:** mesh analysis, transformations and Boolean operations. Use a dedicated Python environment rather than changing dependencies of an existing project.

## Build and validate

Read the current project's instructions. Keep existing versions and editable sources. Put derived exports and previews in separate output directories; overwriting generated files requires an intentional `--overwrite`.

Use millimeters for CAD and numeric STL coordinates. STEP records units; glTF/GLB coordinates are in meters. An inspector reports axes as stored in the file: compare expected dimensions in that coordinate system, or explicitly transform the model first. In Blender with millimeter-valued coordinates, use `METRIC`, `scale_length=0.001` and STL export with `use_scene_unit=False`; confirm exported dimensions.

1. Build with explicit parameters. For CAD, verify `shape.isValid()`, solid count and the features that matter to the request. Reimport delivered STEP files and compare dimensions and volume.
2. Export using absolute tessellation tolerances. In CadQuery 2.8, use `shape.exportStl(path, tolerance=0.05, angularTolerance=0.1, relative=False)` as a starting point and refine for the smallest feature. `exporters.export(..., opt={"relative": False})` does **not** forward that option for STL. See [references/cadquery.md](references/cadquery.md).
3. Run `scripts/inspect_mesh.py` on the actual exported geometry, supplying expected dimensions and material-body count when known. It distinguishes surface shells from nested cavities. Review failures; do not reverse a cavity's normals, fill holes or discard components just to make a check pass. The inspector is conservative around intersecting or touching shells.
4. Render the actual exported STL using `scripts/render_preview.py`, then inspect the image. Use `--view front`, `top`, `bottom` or another supported view to expose hidden features. For other delivery formats, also inspect those files' units/transforms and, when necessary, render their imported geometry. A preview of a sibling STL does not validate a 3MF assembly. Use sections or individual parts when they resolve specific design uncertainties.
5. State the verified dimensions, units and any assumptions. A closed, oriented mesh does not by itself prove minimum wall thickness, support requirements, strength, fit, successful slicing or physical print quality. Read the inspector's `not_checked` output and preserve those limits in the result.

The launcher `scripts/run_3d.py` provides `doctor`, `python`, `blender`, `inspect`, `render` and `scad`. OpenSCAD warnings are fatal by default; use `--allow-warnings` only after understanding the warning.

When editing or reconstructing an existing mesh, retain the original and compare in the same coordinates and units without automatic alignment or rescaling. Bounds and volume alone cannot establish equivalence: check the holes, mating surfaces and sections that must be preserved. Use surface distances or Boolean differences when justified; report their method and units. Sampled distances are not an exact Hausdorff bound, and a failed Boolean is an uncomputed result, never zero difference.

## Printer projects and delivery

Read the user's current printer and material information from the task or project. Do not infer the active spool, bed state or a universally safe fit clearance.

For a critical fit, distinguish nominal dimensions from compensation and state whether clearance is diametral or per side. Reuse measured local calibration only with its printer/material/nozzle, orientation and slicer context; label assumptions separately. Offer a small fit coupon when physical calibration is missing and fit matters. Do not claim the coupon was printed or measured without evidence.

A generic 3MF contains geometry; a Bambu/other slicer project may also contain modifiers, negative volumes and profiles. Generic mesh inspection does not validate that project semantics. Verify the printable objects and inspect the actual slicer result when a sliced or printer-configured project is requested. Sending a print is a separate action that requires the user's instruction.

Deliver the requested model formats, editable source, a useful preview and a concise validation result. Do not promise faithful reconstruction from one image when generating a shape procedurally.
