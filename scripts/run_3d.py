"""Run local CAD tools with explicit configuration or portable PATH discovery."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
CORE_PACKAGES = ("numpy", "trimesh", "manifold3d", "networkx", "lxml", "rtree")
OPTIONAL_PACKAGES = ("cadquery", "cadquery-ocp", "Pillow")
TOOL_NAMES = ("python", "blender", "openscad", "bambu_studio", "uv")


def load_config(filename=None):
    """Resolve only this invocation's tools; never change global settings."""
    selected = filename or os.environ.get("PRINT3D_TOOLS")
    implicit = HERE / "tools.local.json"
    path = Path(selected).expanduser().resolve() if selected else implicit if implicit.is_file() else None
    config = {
        "python": sys.executable,
        "blender": shutil.which("blender"),
        "openscad": shutil.which("openscad.com") or shutil.which("openscad"),
        "bambu_studio": shutil.which("bambu-studio"),
        "uv": shutil.which("uv"),
    }
    if path is not None:
        values = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(values, dict):
            raise ValueError("Tool configuration must be a JSON object")
        for key in TOOL_NAMES:
            if key not in values:
                continue
            value = values[key]
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"Tool '{key}' must be a nonempty executable path/name or null")
            if value is not None:
                value = os.path.expandvars(os.path.expanduser(value))
                candidate = Path(value)
                if not candidate.is_absolute() and ("/" in value or "\\" in value):
                    value = str(path.parent / candidate)
                else:
                    value = shutil.which(value) or value
            config[key] = value
    return config


def executable(config, key):
    value = config.get(key)
    if not value or not Path(value).is_file():
        raise ValueError(f"Tool '{key}' is not configured or missing: {value}")
    return value


def query_packages(python):
    names = list(CORE_PACKAGES + OPTIONAL_PACKAGES)
    code = """import importlib.metadata as m, json, sys
versions = {}
for name in json.loads(sys.argv[1]):
    try:
        versions[name] = m.version(name)
    except m.PackageNotFoundError:
        versions[name] = None
print(json.dumps(versions))
"""
    result = subprocess.run(
        [python, "-I", "-c", code, json.dumps(names)],
        capture_output=True, text=True, errors="replace", timeout=30,
    )
    if result.returncode:
        raise ValueError(f"Configured Python package query failed (exit {result.returncode}): {result.stderr.strip()}")
    versions = json.loads(result.stdout)
    if not isinstance(versions, dict) or any(name not in versions for name in names):
        raise ValueError("Configured Python returned an invalid package report")
    return versions


def doctor(config):
    report = {"tools": {}, "packages": {}, "required_packages": list(CORE_PACKAGES)}
    for key in TOOL_NAMES:
        path = config.get(key)
        exists = bool(path and Path(path).is_file())
        item = {"path": path, "exists": exists, "required": key == "python"}
        if key != "bambu_studio" and exists:
            try:
                result = subprocess.run([path, "--version"], capture_output=True, text=True, errors="replace", timeout=30)
                lines = (result.stdout + result.stderr).strip().splitlines()
                item.update(version=lines[0] if lines else "", exit_code=result.returncode)
            except (OSError, subprocess.TimeoutExpired) as exc:
                item["error"] = str(exc)
        report["tools"][key] = item
    python_ok = report["tools"]["python"].get("exit_code") == 0
    if python_ok:
        try:
            report["packages"] = query_packages(executable(config, "python"))
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            report["package_query_error"] = str(exc)
    report["ok"] = bool(python_ok and all(report["packages"].get(name) for name in CORE_PACKAGES))
    report["capabilities"] = {
        "mesh_inspection": report["ok"],
        "cadquery": bool(report["packages"].get("cadquery")),
        "blender": report["tools"]["blender"].get("exit_code") == 0,
        "openscad": report["tools"]["openscad"].get("exit_code") == 0,
    }
    return report


def same_file(first, second):
    if first.resolve() == second.resolve():
        return True
    return first.exists() and second.exists() and first.samefile(second)


def scad_arguments(args):
    """Guard explicitly named exports before OpenSCAD can open any files.

    Normalize long output aliases to -o, supported by older OpenSCAD releases.
    Wrapper switches are never passed to OpenSCAD.
    """
    overwrite = "--overwrite" in args
    allow_warnings = "--allow-warnings" in args
    args = [arg for arg in args if arg not in ("--overwrite", "--allow-warnings")]
    forwarded, output_paths, input_candidates = [], [], []
    index = 0
    while index < len(args):
        arg = args[index]
        output = None
        if arg in ("-o", "--o", "--output"):
            index += 1
            if index == len(args):
                raise ValueError(f"{arg} requires an output path")
            output = args[index]
        elif arg.startswith(("--o=", "--output=")):
            output = arg.split("=", 1)[1]
        elif arg.startswith("-o") and not arg.startswith("--"):
            output = arg[2:]
        if output is not None:
            if not output:
                raise ValueError("OpenSCAD output path must not be empty")
            forwarded.extend(("-o", output))
            if output != "-":
                output_paths.append(Path(output))
        else:
            forwarded.append(arg)
            try:
                if Path(arg).is_file():
                    input_candidates.append(Path(arg))
            except OSError:
                # Definitions and other option values need not be valid paths.
                pass
        index += 1
    for position, destination in enumerate(output_paths):
        if any(same_file(destination, source) for source in input_candidates):
            raise ValueError(f"OpenSCAD output must not overwrite an input file, even with --overwrite: {destination}")
        if destination.is_symlink():
            raise ValueError(f"OpenSCAD output must not be a symbolic link: {destination}")
        if any(same_file(destination, other) for other in output_paths[:position]):
            raise ValueError(f"OpenSCAD outputs must be different files: {destination}")
        if destination.exists():
            if not destination.is_file():
                raise ValueError(f"OpenSCAD output is not a regular file: {destination}")
            if not overwrite:
                raise FileExistsError(f"OpenSCAD output already exists: {destination}; choose a new path or pass --overwrite")
    if not forwarded:
        raise ValueError("scad requires export arguments, --help, or --version")
    if not allow_warnings and "--hardwarnings" not in forwarded:
        forwarded.insert(0, "--hardwarnings")
    return forwarded


def build_command(config, action, args):
    args = list(args)
    if action == "python":
        if not args:
            raise ValueError("python requires a script or explicit Python arguments")
        return [executable(config, "python"), *args]
    if action == "inspect":
        return [executable(config, "python"), str(HERE / "inspect_mesh.py"), *args]
    if action in ("blender", "render"):
        if action == "blender":
            if not args:
                raise ValueError("blender requires a Python script path")
            script, args = args[0], args[1:]
        else:
            script = str(HERE / "render_preview.py")
        return [executable(config, "blender"), "--background", "--factory-startup", "--python-exit-code", "1", "--python", script, "--", *args]
    if action == "scad":
        return [executable(config, "openscad"), *scad_arguments(args)]
    raise ValueError(f"Unknown action: {action}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Tool JSON; otherwise PRINT3D_TOOLS, tools.local.json, then PATH discovery")
    parser.add_argument("action", choices=("doctor", "python", "blender", "inspect", "render", "scad"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.action == "doctor":
        if args.arguments:
            raise ValueError("doctor takes no additional arguments")
        report = doctor(config)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    return subprocess.run(build_command(config, args.action, args.arguments)).returncode


def cli(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        return main(argv)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"3D tool error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
