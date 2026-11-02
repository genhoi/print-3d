"""Portable routing and diagnostics, with optional real OpenSCAD regression."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import venv

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("run_3d_under_test", SCRIPTS / "run_3d.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def config(self, name, **values):
        path = self.root / name
        path.write_text(json.dumps(values), encoding="utf-8")
        return path

    def test_explicit_config_takes_priority_and_relative_paths_are_local(self):
        env_config = self.config("env.json", python="missing-python")
        explicit = self.config("explicit.json", python=sys.executable, blender="./bin/blender", openscad=None)
        with mock.patch.dict(os.environ, {"PRINT3D_TOOLS": str(env_config)}):
            values = runner.load_config(explicit)
        self.assertEqual(values["python"], sys.executable)
        # Windows CI may expose TEMP with an 8.3 alias (RUNNER~1); compare the
        # resolved destination, as the config loader resolves its base path.
        self.assertEqual(Path(values["blender"]).resolve(), (self.root / "bin" / "blender").resolve())
        self.assertIsNone(values["openscad"])

    def test_environment_then_local_config_and_discovery(self):
        local = self.config("tools.local.json", python=sys.executable, blender=None)
        with mock.patch.object(runner, "HERE", self.root), mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(runner.load_config()["blender"])
            local.unlink()
            self.assertEqual(runner.load_config()["python"], sys.executable)
            env_config = self.config("env.json", python=sys.executable, openscad=None)
            with mock.patch.dict(os.environ, {"PRINT3D_TOOLS": str(env_config)}):
                self.assertIsNone(runner.load_config()["openscad"])

    def test_bad_config_reports_error_without_traceback(self):
        for contents in ("{", "[]", '{"python": 42}'):
            path = self.root / "invalid.json"
            path.write_text(contents)
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                code = runner.cli(["--config", str(path), "doctor"])
            self.assertEqual(code, 2)
            self.assertIn("3D tool error:", error.getvalue())
            self.assertNotIn("Traceback", error.getvalue())

    def test_doctor_queries_configured_python_not_callers_packages(self):
        isolated = self.root / "empty-venv"
        venv.EnvBuilder(with_pip=False).create(isolated)
        python = isolated / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        configuration = {key: None for key in runner.TOOL_NAMES}
        configuration["python"] = str(python)
        report = runner.doctor(configuration)
        self.assertEqual(report["tools"]["python"]["exit_code"], 0)
        self.assertIsNone(report["packages"]["trimesh"])
        self.assertFalse(report["ok"])
        self.assertEqual(report["tools"]["python"]["path"], str(python))

    def test_optional_tools_do_not_make_healthy_python_fail(self):
        configuration = {key: None for key in runner.TOOL_NAMES}
        configuration["python"] = sys.executable
        versions = {name: "test-installed" for name in runner.CORE_PACKAGES}
        with mock.patch.object(runner, "query_packages", return_value=versions):
            report = runner.doctor(configuration)
        self.assertTrue(report["ok"])
        self.assertFalse(report["capabilities"]["blender"])
        self.assertFalse(report["capabilities"]["openscad"])
        self.assertFalse(report["tools"]["blender"]["required"])

    def test_scad_is_strict_by_default_with_explicit_opt_out(self):
        config = {"openscad": sys.executable}
        self.assertEqual(runner.build_command(config, "scad", ["-o", "out.stl", "part.scad"]),
                         [sys.executable, "--hardwarnings", "-o", "out.stl", "part.scad"])
        self.assertEqual(runner.build_command(config, "scad", ["--allow-warnings", "-o", "out.stl", "part.scad"]),
                         [sys.executable, "-o", "out.stl", "part.scad"])

    def test_scad_existing_output_refused_before_process_launch_for_all_forms(self):
        source = self.root / "part.scad"
        source.write_text("cube(10);")
        target = self.root / "part.stl"
        target.write_bytes(b"previous export")
        config = self.config("tools.json", openscad=sys.executable)
        forms = (["-o", str(target)], ["--output", str(target)],
                 ["--output=" + str(target)], ["--o=" + str(target)], ["-o" + str(target)])
        for flags in forms:
            with self.subTest(flags=flags), mock.patch.object(runner.subprocess, "run") as run:
                with self.assertRaises(FileExistsError):
                    runner.main(["--config", str(config), "scad", *flags, str(source)])
                run.assert_not_called()
            self.assertEqual(target.read_bytes(), b"previous export")
            self.assertEqual(source.read_text(), "cube(10);")
        command = runner.build_command({"openscad": sys.executable}, "scad",
                                       ["--overwrite", "--output", str(target), str(source)])
        self.assertNotIn("--overwrite", command)
        self.assertEqual(command[-3:], ["-o", str(target), str(source)])

    def test_scad_overwrite_cannot_replace_input_or_hardlink(self):
        source = self.root / "source.scad"
        source.write_bytes(b"cube(10);")
        with self.assertRaisesRegex(ValueError, "input file"):
            runner.scad_arguments(["--overwrite", "-o", str(source), str(source)])
        target = self.root / "source-alias.stl"
        try:
            os.link(source, target)
        except OSError as exc:
            self.skipTest(f"Hardlinks unavailable: {exc}")
        with self.assertRaisesRegex(ValueError, "input file"):
            runner.scad_arguments(["--overwrite", "-o", str(target), str(source)])
        self.assertEqual(source.read_bytes(), b"cube(10);")

    def test_scad_symlink_output_is_rejected_even_with_overwrite(self):
        source = self.root / "part.scad"
        source.write_text("cube(10);")
        target = self.root / "link.stl"
        try:
            target.symlink_to(self.root / "missing.stl")
        except OSError as exc:
            self.skipTest(f"Symlinks unavailable: {exc}")
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            runner.scad_arguments(["--overwrite", "-o", str(target), str(source)])
        self.assertFalse((self.root / "missing.stl").exists())

    def test_scad_stdout_and_multiple_outputs_have_safe_semantics(self):
        self.assertEqual(runner.scad_arguments(["--allow-warnings", "--output=-", "part.scad"]),
                         ["-o", "-", "part.scad"])
        destination = str(self.root / "same.stl")
        with self.assertRaisesRegex(ValueError, "different files"):
            runner.scad_arguments(["--overwrite", "-o", destination, "--output=" + destination, "part.scad"])
        for arguments in (["-o"], ["--output="]):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                runner.scad_arguments(arguments)

    def test_child_failure_exit_code_is_preserved(self):
        config = self.config("tools.json", python=sys.executable)
        self.assertEqual(runner.main(["--config", str(config), "python", "-c", "raise SystemExit(7)"]), 7)

    def test_missing_optional_tool_only_blocks_its_action(self):
        with self.assertRaisesRegex(ValueError, "blender.*missing"):
            runner.build_command({"blender": None}, "render", [])


@unittest.skipUnless(os.environ.get("PRINT3D_TEST_OPENSCAD"), "Set PRINT3D_TEST_OPENSCAD for real OpenSCAD checks")
class OpenScadIntegrationTests(unittest.TestCase):
    def test_existing_export_requires_overwrite_and_source_is_preserved(self):
        import trimesh
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "part.scad"
            source.write_text("cube([10, 20, 30]);\n")
            original = source.read_bytes()
            config = root / "tools.json"
            config.write_text(json.dumps({"openscad": os.environ["PRINT3D_TEST_OPENSCAD"]}))
            target = root / "part.stl"
            target.write_bytes(b"preserve this existing export")
            prefix = [sys.executable, str(SCRIPTS / "run_3d.py"), "--config", str(config), "scad"]
            rejected = subprocess.run([*prefix, "--output=" + str(target), str(source)], capture_output=True, timeout=60)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(target.read_bytes(), b"preserve this existing export")
            exported = subprocess.run([*prefix, "--overwrite", "--output", str(target), str(source)], capture_output=True, timeout=60)
            self.assertEqual(exported.returncode, 0, exported.stderr.decode(errors="replace"))
            mesh = trimesh.load_mesh(target)
            self.assertEqual(mesh.extents.tolist(), [10.0, 20.0, 30.0])
            self.assertTrue(mesh.is_volume)
            attacked = subprocess.run([*prefix, "--overwrite", "-o", str(source), str(source)], capture_output=True, timeout=60)
            self.assertNotEqual(attacked.returncode, 0)
            self.assertEqual(source.read_bytes(), original)

    def test_unknown_module_fails_strict_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "typo.scad"
            source.write_text("cube(10); typo_module();\n")
            config = root / "tools.json"
            config.write_text(json.dumps({"openscad": os.environ["PRINT3D_TEST_OPENSCAD"]}))
            target = root / "part.stl"
            prefix = [sys.executable, str(SCRIPTS / "run_3d.py"), "--config", str(config), "scad"]
            strict = subprocess.run([*prefix, "-o", str(target), str(source)], capture_output=True, timeout=60)
            self.assertNotEqual(strict.returncode, 0)
            self.assertFalse(target.exists())
            allowed = subprocess.run([*prefix, "--allow-warnings", "-o", str(target), str(source)], capture_output=True, timeout=60)
            self.assertEqual(allowed.returncode, 0, allowed.stderr.decode(errors="replace"))
            self.assertTrue(target.is_file())


if __name__ == "__main__":
    unittest.main()
