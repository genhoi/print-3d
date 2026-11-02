# print-3d

An agent skill for creating and checking local 3D-printable models with **CadQuery, Blender and OpenSCAD**. It keeps editable sources, verifies exported geometry, and produces previews of the actual meshes.

[Русский](README.ru.md) · [Skill instructions](SKILL.md)

## What is included

- A `SKILL.md` workflow for dimensional CAD, procedural forms and print preparation.
- A mesh inspector for STL, OBJ, GLB/glTF and generic 3MF, with units, transforms, body/cavity orientation and dimension checks.
- A Blender STL preview renderer that protects existing outputs.
- A configurable launcher and toolchain diagnostic, plus regression tests and a CadQuery example.

This is a local modeling workflow, not a trained image-to-3D model or a printer-control service. Geometry checks do not prove strength, minimum wall thickness, slicer settings or physical print quality. The JSON report lists checks that were not performed.

## Install

Clone into your agent's skills directory, or copy this repository there. For Codex:

```sh
git clone https://github.com/genhoi/print-3d.git ~/.codex/skills/print-3d
cd ~/.codex/skills/print-3d
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-cad.txt
.venv/bin/python scripts/run_3d.py doctor
```

On Windows, use `python -m venv .venv` and `.venv\Scripts\python.exe` for the subsequent commands. Python 3.12 is the tested version. For mesh inspection without CAD generation, install `requirements.txt` instead.

Install [Blender](https://www.blender.org/download/) and/or [OpenSCAD](https://openscad.org/downloads.html) for the workflows you use. They are optional for mesh inspection and CadQuery. Put their executables on PATH, or copy `scripts/tools.example.json` to the ignored `scripts/tools.local.json` and set the executable paths. Configuration can also be supplied with `--config` or `PRINT3D_TOOLS`; see [toolchain reference](references/toolchain.md).

For other SKILL.md-compatible agents, use their documented skill location. The helper scripts can also be used directly without an agent. Invoke the installed skill with `$print-3d` where supported, or ask your agent to use it.

## Try it

With the dedicated environment active:

```sh
python examples/bracket.py --output-dir outputs/bracket
python scripts/run_3d.py inspect outputs/bracket/bracket.stl --expect-extents 60 36 32 --output outputs/bracket/mesh.json
python scripts/run_3d.py render --input outputs/bracket/bracket.stl --output outputs/bracket/preview/model.png
python scripts/run_3d.py render --input outputs/bracket/bracket.stl --output outputs/bracket/preview/front.png --view front
```

The bundled inspector, renderer and examples preserve existing outputs unless you explicitly pass `--overwrite`. The OpenSCAD wrapper protects explicit `-o` outputs; use fresh directories for auxiliary files or animation. Put preview scenes in a separate directory from editable source scenes. OpenSCAD runs use `--hardwarnings` by default; `--allow-warnings` opts out.

The inspector reports coordinates in millimeters and preserves file axes. `--expected-components` counts material bodies: an enclosed cavity is an internal shell, not an extra part. Close, intersecting or ambiguous shells are treated conservatively. See [SKILL.md](SKILL.md) and the report's limitations before calling a model print-ready.

## Tests

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Core and CAD regression tests run in CI on Linux and Windows. Set `PRINT3D_TEST_BLENDER` and `PRINT3D_TEST_OPENSCAD` to executable paths to enable real application tests; they are skipped when those variables are absent. Tests use temporary directories and do not send print jobs. The first release was exercised with Python 3.12, CadQuery 2.8, trimesh 5.2, manifold3d 3.5.4, Blender 5.2.3 LTS and OpenSCAD 2021.01.

## Related skills

We reviewed [cadquery-llm-skill](https://github.com/jmwright/cadquery-llm-skill), [openscad-skill](https://github.com/swh/openscad-skill), [blender-kit](https://github.com/someamount2190/blender-kit), [blender-web-3d-skill](https://github.com/czlonkowski/blender-web-3d-skill) and [openscad_claude_skill](https://github.com/andreahaku/openscad_claude_skill). The [comparison and resulting changes, in Russian](docs/skill-comparison.ru.md) link to the reviewed revisions and explain which approaches we adopted or rejected. This package contains original implementations; it does not vendor those projects or claim a comparative modeling benchmark.

Local paths, machine configuration, review transcripts, model outputs and credentials are not included. License: [MIT](LICENSE).
