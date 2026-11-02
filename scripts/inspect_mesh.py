"""Inspect an exported mesh without repairing it or changing its source file."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import struct
import sys

import manifold3d
import numpy as np
import trimesh


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="STL, OBJ, 3MF, GLB, or glTF")
    parser.add_argument("--output", type=Path, help="Write the JSON report here")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing an existing report, never the input mesh")
    parser.add_argument("--expect-extents", type=float, nargs=3, metavar=("X", "Y", "Z"))
    parser.add_argument("--extent-tolerance", type=float, default=0.05, help="Finite absolute tolerance in mm (default 0.05)")
    parser.add_argument("--expected-components", type=int, default=1, help="Expected material bodies, not surface shells (default 1); a closed cavity is not another body")
    parser.add_argument("--units", choices=("mm", "cm", "m", "in"), help="Override input coordinate units; GLB/glTF otherwise use metres, STL/OBJ mm, 3MF its declared units")
    return parser.parse_args()


def mesh_summary(mesh):
    volume = float(mesh.volume)
    return {
        "vertices": len(mesh.vertices),
        "triangles": len(mesh.faces),
        "bounds_mm": mesh.bounds.tolist(),
        "extents_mm": mesh.extents.tolist(),
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "signed_volume_mm3": volume,
        "positive_volume": volume > 0,
    }


def checked_manifold(shape, description):
    if shape.status() != manifold3d.Error.NoError:
        raise ValueError(f"Cannot classify {description}: manifold3d returned {shape.status()}")
    return shape


def validate_gltf_primitives(path):
    """Reject confirmed geometry features the mesh loader would silently omit.

    This reads only the JSON document, not the mesh buffers. Both supported
    modes describe triangles; points, lines and triangle fans are unsupported.
    """
    if path.suffix.lower() == ".glb":
        with path.open("rb") as handle:
            header = handle.read(20)
            if len(header) != 20:
                raise ValueError("GLB header is incomplete")
            magic, version, total_length, json_length, chunk_type = struct.unpack("<4sIII4s", header)
            if magic != b"glTF" or version != 2 or chunk_type != b"JSON":
                raise ValueError("Expected a GLB 2.0 file with a leading JSON chunk")
            if json_length > total_length - 20:
                raise ValueError("GLB JSON chunk exceeds the declared file length")
            content = handle.read(json_length)
            if len(content) != json_length:
                raise ValueError("GLB JSON chunk is incomplete")
        document = json.loads(content)
    else:
        document = json.loads(path.read_bytes())
    for node_index, node in enumerate(document.get("nodes", [])):
        if "EXT_mesh_gpu_instancing" in node.get("extensions", {}):
            raise ValueError(
                f"Unsupported glTF node extension EXT_mesh_gpu_instancing on node {node_index}; "
                "convert GPU instances to ordinary mesh nodes before inspection"
            )
    for mesh_index, mesh in enumerate(document.get("meshes", [])):
        for primitive_index, primitive in enumerate(mesh.get("primitives", [])):
            mode = primitive.get("mode", 4)
            if mode not in (4, 5):
                raise ValueError(
                    f"Unsupported glTF primitive mode {mode} in mesh {mesh_index}, primitive {primitive_index}; "
                    "only TRIANGLES (4) and TRIANGLE_STRIP (5) are supported"
                )


def classify_shells(shells, report):
    """Classify whole shell volumes, then enforce alternating nesting orientation.

    Boolean containment avoids a single-point or vertex-only inclusion heuristic.
    A conservative clearance test rejects touching/near-touching boundaries.
    This is not a general test for self-intersections inside an individual shell.
    """
    shell_info = [dict(index=i + 1, **mesh_summary(shell)) for i, shell in enumerate(shells)]
    report["surface_shells"] = len(shells)
    report["shells"] = shell_info
    for info in shell_info:
        if not (info["watertight"] and info["winding_consistent"]):
            raise ValueError(f"Surface shell {info['index']} is not closed and consistently wound")
        if not math.isfinite(info["signed_volume_mm3"]) or info["signed_volume_mm3"] == 0:
            raise ValueError(f"Surface shell {info['index']} has zero or non-finite signed volume")

    # Normalize Boolean operands to make precision less dependent on units and
    # offsets. Mesh64 retains doubles; orientation is checked separately below.
    scale = max(float(np.max(shell.extents)) for shell in shells)
    origin = (np.min([s.bounds[0] for s in shells], axis=0) + np.max([s.bounds[1] for s in shells], axis=0)) / 2
    clearance_mm = max(1e-6, scale * 1e-7)
    clearance = clearance_mm / scale
    report["shell_classification_tolerance_mm"] = clearance_mm
    shapes = []
    for i, shell in enumerate(shells):
        faces = shell.faces if shell.volume > 0 else shell.faces[:, ::-1]
        raw = manifold3d.Mesh64(
            np.ascontiguousarray((shell.vertices - origin) / scale, dtype=np.float64),
            np.ascontiguousarray(faces, dtype=np.uint64),
        )
        shape = checked_manifold(manifold3d.Manifold(raw), f"surface shell {i + 1}")
        if shape.is_empty() or not math.isfinite(shape.volume()) or shape.volume() <= 0:
            raise ValueError(f"Cannot classify surface shell {i + 1} as a finite filled volume")
        shapes.append(shape)

    containers = [set() for _ in shells]
    eroded = {}
    erosion_kernel = manifold3d.Manifold.cube((2 * clearance,) * 3, center=True)
    for i, left in enumerate(shapes):
        for j in range(i + 1, len(shapes)):
            # AABB separation is only a broad phase, never a containment test.
            a, b = shells[i].bounds, shells[j].bounds
            if np.any(a[1] < b[0] - clearance_mm) or np.any(b[1] < a[0] - clearance_mm):
                continue
            right = shapes[j]
            label = f"shells {i + 1} and {j + 1}"
            intersection = checked_manifold(left ^ right, label)
            if intersection.is_empty():
                gap = left.min_gap(right, 2 * clearance)
                if not math.isfinite(gap) or gap <= clearance:
                    raise ValueError(f"Surface {label} touch or are too close to classify")
                continue
            left_remainder = checked_manifold(left - right, label)
            right_remainder = checked_manifold(right - left, label)
            if left_remainder.is_empty() and right_remainder.is_empty():
                raise ValueError(f"Surface {label} are coincident")
            if left_remainder.is_empty():
                inner, outer = i, j
            elif right_remainder.is_empty():
                inner, outer = j, i
            else:
                raise ValueError(f"Surface {label} intersect or partially overlap")
            # Containment alone includes contact. Erode the container by a small
            # cube and require the entire inner solid to remain contained. Cache
            # per container; failure/ambiguity is an error, not a guessed parent.
            if outer not in eroded:
                eroded[outer] = checked_manifold(shapes[outer].minkowski_difference(erosion_kernel), f"clearance of shell {outer + 1}")
                if eroded[outer].is_empty() or eroded[outer].volume() >= shapes[outer].volume():
                    raise ValueError(f"Cannot establish a reliable interior clearance for shell {outer + 1}")
            clearance_remainder = checked_manifold(shapes[inner] - eroded[outer], label)
            if not clearance_remainder.is_empty():
                raise ValueError(f"Surface {label} touch or lie within the classification tolerance")
            containers[inner].add(outer)

    for i, info in enumerate(shell_info):
        depth = len(containers[i])
        parent = min(containers[i], key=lambda k: abs(shell_info[k]["signed_volume_mm3"])) if containers[i] else None
        role = "body" if depth % 2 == 0 else "void"
        info.update(nesting_depth=depth, parent_shell=None if parent is None else parent + 1, role=role)
        expected_positive = role == "body"
        if info["positive_volume"] != expected_positive:
            expected = "outward (positive volume)" if expected_positive else "inward toward the void (negative volume)"
            report["errors"].append(f"Surface shell {i + 1} at nesting depth {depth} must be oriented {expected}")
    bodies = []
    for info in shell_info:
        if info["role"] == "body":
            holes = [s for s in shell_info if s["parent_shell"] == info["index"] and s["role"] == "void"]
            bodies.append({
                "index": len(bodies) + 1,
                "outer_shell": info["index"],
                "void_shells": [s["index"] for s in holes],
                "material_volume_mm3": abs(info["signed_volume_mm3"]) - sum(abs(s["signed_volume_mm3"]) for s in holes),
            })
    report.update(material_bodies=len(bodies), internal_voids=sum(s["role"] == "void" for s in shell_info), bodies=bodies)


def inspect(args):
    report = {
        "source": str(args.path.resolve()),
        "schema_version": 2,
        "trimesh_version": trimesh.__version__,
        "passed": False,
        "errors": [],
        "expected_components": args.expected_components,
        "expected_components_kind": "material_bodies",
        "not_checked": ["minimum wall thickness", "self intersections within an individual surface shell", "overhangs and supports", "mechanical strength", "fit after printing", "slicer toolpaths", "3MF application-specific object roles"],
    }
    if args.expected_components < 1:
        raise ValueError("expected-components must be positive")
    if not math.isfinite(args.extent_tolerance) or args.extent_tolerance < 0:
        raise ValueError("extent-tolerance must be finite and nonnegative")
    if args.expect_extents is not None and (not np.isfinite(args.expect_extents).all() or min(args.expect_extents) <= 0):
        raise ValueError("Expected extents must contain three finite positive dimensions")
    suffix = args.path.suffix.lower()
    if suffix in {".glb", ".gltf"}:
        validate_gltf_primitives(args.path)
    # 3MF's separate postprocessor renames SolidWorks-style body children.
    # Name collisions can silently replace distinct meshes, even with
    # process=False. Inspection must retain every original geometry object.
    loaded = trimesh.load(args.path, process=False, postprocess=False)
    if args.units:
        units, basis = args.units, "explicit CLI override"
    elif suffix in {".glb", ".gltf"}:
        units, basis = "m", "glTF specification: native coordinates in metres"
    elif suffix == ".3mf":
        units, basis = loaded.metadata.get("units", "mm"), "3MF declared units (default millimetres)"
    else:
        units, basis = "mm", "assumed millimetres for unitless input; use --units to override"
    scale = float(trimesh.units.unit_conversion(units, "mm"))
    report.update(input_units=units, units_basis=basis, scale_to_mm=scale, coordinate_axes="source axes; no reorientation")
    if isinstance(loaded, trimesh.Scene):
        report["scene_instances"] = len(loaded.graph.nodes_geometry)
        mesh = loaded.to_mesh()
    elif isinstance(loaded, trimesh.Trimesh):
        mesh = loaded.copy()
    else:
        raise ValueError("Input does not contain a triangle mesh")
    if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        report["errors"].append("Mesh is empty")
        return report
    if not np.isfinite(mesh.vertices).all():
        report["errors"].append("Vertex coordinates contain NaN or infinity")
        return report
    if np.any(mesh.faces < 0) or np.any(mesh.faces >= len(mesh.vertices)):
        report["errors"].append("Faces reference invalid vertex indices")
        return report
    mesh.apply_scale(scale)
    if not np.isfinite(mesh.vertices).all():
        report["errors"].append("Coordinates became non-finite during unit conversion")
        return report
    raw_vertices = len(mesh.vertices)
    # Ignore visual seams and weld matching positions in memory. Never repair
    # holes, remove faces or modify the source file during inspection.
    mesh.merge_vertices(merge_tex=True, merge_norm=True)
    mesh.remove_unreferenced_vertices()
    report["vertices_before_weld"] = raw_vertices
    report["degenerate_faces"] = int((~mesh.nondegenerate_faces()).sum())
    sorted_faces = np.sort(mesh.faces, axis=1)
    report["duplicate_faces"] = int(len(sorted_faces) - len(np.unique(sorted_faces, axis=0)))
    report.update(mesh_summary(mesh))
    errors = report["errors"]
    if not report["watertight"]:
        errors.append("Mesh is not watertight")
    if not report["winding_consistent"]:
        errors.append("Face winding is inconsistent")
    if not report["positive_volume"]:
        errors.append("Signed mesh volume is not positive")
    if report["degenerate_faces"]:
        errors.append(f"Found {report['degenerate_faces']} degenerate faces")
    if report["duplicate_faces"]:
        errors.append(f"Found {report['duplicate_faces']} duplicate faces")
    if not errors:
        try:
            classify_shells(list(mesh.split(only_watertight=False, repair=False)), report)
        except ValueError as exc:
            errors.append(str(exc))
        if "material_bodies" in report and report["material_bodies"] != args.expected_components:
            errors.append(f"Expected {args.expected_components} material bodies, found {report['material_bodies']}")
    if args.expect_extents is not None:
        delta = np.abs(mesh.extents - np.asarray(args.expect_extents))
        report.update(expected_extents_mm=args.expect_extents, extent_tolerance_mm=args.extent_tolerance, extent_error_mm=delta.tolist())
        if not np.all(delta <= args.extent_tolerance):
            errors.append("Bounding-box dimensions exceed the requested tolerance")
    report["passed"] = not errors
    return report


def validate_output(args):
    if not args.output:
        return
    source, target = args.path, args.output
    if target.resolve() == source.resolve() or (target.exists() and source.exists() and target.samefile(source)):
        raise ValueError("Report output must not overwrite the source mesh")
    if target.exists() and not args.overwrite:
        raise FileExistsError("Report already exists; choose another path or use --overwrite")


def error_report(args, exc):
    return {"source": str(args.path.resolve()), "passed": False, "errors": [f"{type(exc).__name__}: {exc}"]}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    try:
        validate_output(args)
    except (ValueError, OSError) as exc:
        print(json.dumps(error_report(args, exc), ensure_ascii=False))
        return 1
    try:
        report = inspect(args)
        text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    except Exception as exc:
        report = error_report(args, exc)
        text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation also closes the accidental overwrite race when
            # --overwrite is absent. The source/hardlink guard applies always.
            with args.output.open("w" if args.overwrite else "x", encoding="utf-8") as handle:
                handle.write(text + "\n")
        except OSError as exc:
            report = error_report(args, exc)
            text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
