"""Run inside Blender to render an STL in millimetres without changing its file.

blender --background --factory-startup --python-exit-code 1 --python render_preview.py -- --input part.stl --output part.png
"""

import argparse
import json
import sys
from pathlib import Path

VIEW_DIRECTIONS = {
    "isometric": (1.45, -1.8, 1.25),
    "front": (0, -3, 0),
    "back": (0, 3, 0),
    "left": (-3, 0, 0),
    "right": (3, 0, 0),
    "top": (0, 0, 3),
    "bottom": (0, 0, -3),
}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="STL coordinates are interpreted as millimetres")
    parser.add_argument("--output", type=Path, required=True, help="PNG preview")
    parser.add_argument("--blend-output", type=Path, help="Optional editable preview scene")
    parser.add_argument("--resolution", type=int, default=1000)
    parser.add_argument("--view", choices=tuple(VIEW_DIRECTIONS), default="isometric", help="Orthographic view; front looks from -Y, top from +Z")
    parser.add_argument("--overwrite", action="store_true", help="Explicitly replace existing preview outputs; never the input STL")
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(argv)


def same_file(first, second):
    """Recognize lexical aliases, symlinks, and existing hard links."""
    if first.resolve() == second.resolve():
        return True
    return first.exists() and second.exists() and first.samefile(second)


def validate_paths(args):
    """Preflight all outputs before importing Blender or modifying the scene."""
    if args.input.suffix.lower() != ".stl":
        raise ValueError("This preview helper accepts STL files with millimetre coordinates")
    if not args.input.is_file():
        raise FileNotFoundError(args.input)
    if args.output.suffix.lower() != ".png":
        raise ValueError("Preview output must have a .png extension")
    if args.blend_output and args.blend_output.suffix.lower() != ".blend":
        raise ValueError("Scene output must have a .blend extension")
    outputs = [args.output] + ([args.blend_output] if args.blend_output else [])
    for destination in outputs:
        if same_file(destination, args.input):
            raise ValueError("Outputs must not overwrite the source STL, even with --overwrite")
        if destination.is_symlink():
            raise ValueError(f"Preview output must not be a symbolic link: {destination}")
        if destination.exists():
            if not destination.is_file():
                raise ValueError(f"Preview output is not a regular file: {destination}")
            if not args.overwrite:
                raise FileExistsError(f"Preview output already exists: {destination}; choose a new path or pass --overwrite")
    if len(outputs) == 2 and same_file(outputs[0], outputs[1]):
        raise ValueError("PNG and Blender outputs must be different files")
    if not 128 <= args.resolution <= 4096:
        raise ValueError("Resolution must be between 128 and 4096")


def main(argv=None):
    args = parse_args(argv)
    validate_paths(args)
    import bpy
    from mathutils import Vector

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "MILLIMETERS"
    scene.unit_settings.scale_length = 0.001
    bpy.ops.wm.stl_import(filepath=str(args.input.resolve()), global_scale=1.0, use_scene_unit=False, forward_axis="Y", up_axis="Z")
    models = [obj for obj in bpy.context.selected_objects if obj.type == "MESH"]
    if not models or not any(len(obj.data.polygons) for obj in models):
        raise ValueError("The input contains no mesh faces")
    bpy.context.view_layer.update()
    corners = [obj.matrix_world @ Vector(v) for obj in models for v in obj.bound_box]
    minimum = Vector(tuple(min(p[i] for p in corners) for i in range(3)))
    maximum = Vector(tuple(max(p[i] for p in corners) for i in range(3)))
    extent = maximum - minimum
    span = max(extent)
    if span <= 0:
        raise ValueError("The input has zero-sized bounds")
    center = (minimum + maximum) / 2

    model_material = bpy.data.materials.new("Preview - blue grey")
    model_material.diffuse_color = (0.17, 0.39, 0.48, 1)
    for obj in models:
        obj.data.materials.clear()
        obj.data.materials.append(model_material)
        obj.color = model_material.diffuse_color
        # Keep the original triangulation and flat normals visible. No remeshing,
        # subdivision, smoothing, or boolean modifiers are applied.

    bpy.ops.mesh.primitive_plane_add(size=span * 200, location=(center.x, center.y, minimum.z - span * 0.006))
    ground = bpy.context.object
    ground.name = "Preview Ground (not part of STL)"
    # A floor below the part would completely obscure its underside.
    ground.hide_render = args.view == "bottom"
    ground_material = bpy.data.materials.new("Preview - warm background")
    ground_material.diffuse_color = (0.82, 0.84, 0.85, 1)
    ground.data.materials.append(ground_material)

    bpy.ops.object.camera_add(location=center + Vector(VIEW_DIRECTIONS[args.view]) * span)
    camera = bpy.context.object
    camera.name = "Preview Camera"
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type = "ORTHO"
    camera.data.clip_start = max(span * 0.001, 0.0001)
    camera.data.clip_end = span * 1000
    rotation_inverse = camera.rotation_euler.to_matrix().transposed()
    projected = [rotation_inverse @ (point - center) for point in corners]
    width = max(v.x for v in projected) - min(v.x for v in projected)
    height = max(v.y for v in projected) - min(v.y for v in projected)
    camera.data.ortho_scale = max(width, height) * 1.28
    scene.camera = camera

    # Workbench gives a deterministic studio preview without GPU ray-tracing,
    # material downloads, or dependence on physical light energy at mm scale.
    scene.render.engine = "BLENDER_WORKBENCH"
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.studiolight_rotate_z = 0.5
    shading.color_type = "MATERIAL"
    shading.show_shadows = True
    shading.show_cavity = True
    shading.cavity_type = "BOTH"
    shading.curvature_ridge_factor = 1.2
    shading.curvature_valley_factor = 1.0
    shading.show_specular_highlight = True
    shading.show_object_outline = False
    shading.background_type = "WORLD"
    scene.world.color = (0.82, 0.84, 0.85)
    scene.display.render_aa = "16"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    scene.render.resolution_x = args.resolution
    scene.render.resolution_y = args.resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    args.output.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(args.output.resolve())
    bpy.ops.object.select_all(action="DESELECT")
    for obj in models:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = models[0]
    if args.blend_output:
        args.blend_output.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(args.blend_output.resolve()))
    bpy.ops.render.render(write_still=True)
    print(json.dumps({
        "preview": str(args.output.resolve()), "source_extents_mm": list(extent),
        "scene_scale_length": 0.001, "engine": scene.render.engine, "view": args.view,
        "camera_location": list(camera.location), "camera_target": list(center),
        "ortho_scale": camera.data.ortho_scale,
    }))


if __name__ == "__main__":
    main()
