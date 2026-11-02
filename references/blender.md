# Blender construction, export and inspection

Use this reference when building or changing a Blender model. The bundled renderer imports an actual exported STL into a separate preview scene; it does not edit the source model or verify Blender's original modifier stack.

## Context and evaluated geometry

Prefer `bpy.data` and `bmesh` for operations that do not need UI context. Import/export/render operators are appropriate when their context is explicit. Set Object Mode, clear stale selection, select the intended objects and set the active object before context-dependent operations; check `poll()` where needed. Do not assume that a background process has an editor area.

After changes, update the view layer before measuring transforms. For modifiers or Geometry Nodes, inspect evaluated geometry through the dependency graph, including generated instances when relevant. Release temporary meshes with `to_mesh_clear()`. Original `obj.data` and an unevaluated bounding box can omit the geometry that is actually exported. Check which viewport/render modifier settings the chosen exporter evaluates.

Account for `matrix_world`, parent transforms and nonuniform or negative scale. Blender rotations use radians. Apply transforms on a working copy only when needed; make shared mesh data independent before destructive edits that should affect one instance. Preserve the editable modifier stack and source scene.

## Export only printable objects

Maintain an explicit object list or named collection for printable geometry. Resolve collection children or generated instances deliberately; fail if the intended selection is empty. A preview ground plane, camera target or decorative support is not automatically part of the print. Record the exported objects alongside expected dimensions and body count.

For mesh objects in a scene where one numeric coordinate is one millimeter, this is the relevant STL export configuration in Blender 5.x:

```python
# printable_objects is an explicit, nonempty list assembled for this task.
if not printable_objects or any(obj.type != "MESH" for obj in printable_objects):
    raise ValueError("Expected explicit printable mesh objects")
if bpy.context.object and bpy.context.object.mode != "OBJECT":
    bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.object.select_all(action="DESELECT")
for obj in printable_objects:
    obj.select_set(True)
bpy.context.view_layer.objects.active = printable_objects[0]
bpy.context.view_layer.update()
# Before this call, reject a destination that would overwrite an existing
# source or unintentionally replace an export. Apply modifiers for this export
# only after checking that their evaluated result is the intended solid.
result = bpy.ops.wm.stl_export(
    filepath=str(stl_path),
    export_selected_objects=True,
    apply_modifiers=True,
    global_scale=1.0,
    use_scene_unit=False,
    forward_axis="Y",
    up_axis="Z",
)
if "FINISHED" not in result:
    raise RuntimeError("STL export did not finish")
```

This recipe assumes millimeter-valued coordinates. Do not apply it unchanged to a scene modeled numerically in meters. Verify the actual exported STL dimensions and body count using the inspector. For GLB, units and axis conventions differ; inspect that delivery separately rather than reusing an STL result.

## Views that answer a geometry question

`render_preview.py --view isometric` is the default. `front` looks from -Y, `back` from +Y, `right` from +X, `left` from -X, `top` from +Z and `bottom` from -Z, in the STL coordinate system. The lower view hides the ground so it cannot conceal the part. The JSON output records the camera framing. Each view auto-fits the model, so framing is not a size measurement.

Choose views that show the requested features. A side hole may need a front view; a recess may need a top view or a separate section. Inspect the rendered images, not merely the render exit status or pixel brightness. Keep triangulation visible in diagnostic previews: smooth shading, subdivision and remeshing can conceal defects or change the object being checked.

Primary references: [operator context](https://docs.blender.org/api/current/info_gotchas_operators.html), [evaluated dependency graph](https://docs.blender.org/api/current/bpy.types.Depsgraph.html), [STL exporter](https://docs.blender.org/api/current/bpy.ops.wm.html#bpy.ops.wm.stl_export).
