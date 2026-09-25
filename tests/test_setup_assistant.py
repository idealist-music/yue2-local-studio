"""GPU/network-free installer checks using only temporary directories."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import setup_assistant as setup


class RecordingInstaller(setup.Installer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.commands = []
        self.fail_once = False

    def confirm(self, *args):
        return True

    def execute(self, command, *, cwd=None):
        self.commands.append((command, cwd))
        if self.fail_once:
            self.fail_once = False
            raise subprocess.CalledProcessError(1, command)


class SetupAssistantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio-setup-")
        self.root = Path(self.temp.name)
        self.app = self.root / "app"
        self.app.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def model(self, path, *, merged=False):
        path.mkdir(parents=True)
        (path / "config.json").write_text(json.dumps({"weights_format": "merged" if merged else "adapter"}))
        (path / "model.safetensors").write_bytes(b"test only")

    def test_doctor_does_not_create_or_change_files(self):
        config = self.app / "config.local.json"
        config.write_text('{"python":"/missing/venv/bin/python","model":"m-a-p/YuE2-3B"}')
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
        with patch.object(setup, "ffmpeg_probe", return_value={"path": "/usr/bin/ffmpeg", "on_path": None,
                                                                "version": None, "libraries": None, "ok": False}):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                result = setup.report(self.app, config)
        after = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
        self.assertEqual(before, after)
        self.assertFalse(result["normal"])
        self.assertIn("MISSING", output.getvalue())

    def test_existing_yue_checkout_venv_and_models_are_reused(self):
        external = self.root / "external"
        yue = external / "YuE"
        helper = yue / "skills/yue2-music/scripts/abc_tools.py"
        helper.parent.mkdir(parents=True)
        helper.write_text("# test helper\n")
        (yue / "pyproject.toml").write_text('[project]\nname="yue2-infer"\n')
        python = yue / "venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text("test")
        self.model(external / "YuE2-3B")
        self.model(external / "YuE2-Vae")
        config = self.app / "config.local.json"
        config.write_text(json.dumps({"python": str(python), "model": str(external / "YuE2-3B"),
                                      "vae": str(external / "YuE2-Vae")}))
        installer = RecordingInstaller(self.app, config, external)
        def no_confirmation(*args):
            raise AssertionError("existing environment must not be changed")
        installer.confirm = no_confirmation
        with patch.object(setup, "python_probe", return_value={"python": [3, 10, 12], "packages": {"yue2-infer": "0.1.6"}}):
            self.assertEqual(installer.yue_stage(), python)
        self.assertEqual(installer.commands, [])
        self.assertEqual(installer.proposals["abc_tools"], str(helper))
        self.assertEqual(installer.proposals["model"], str(external / "YuE2-3B"))

    def test_clone_uses_only_official_yue_source_and_external_destination(self):
        external = self.root / "external"
        installer = RecordingInstaller(self.app, external=external)
        def fake_clone(command, *, cwd=None):
            installer.commands.append((command, cwd))
            candidate = Path(command[-1])
            (candidate / "skills/yue2-music/scripts").mkdir(parents=True)
            (candidate / "pyproject.toml").write_text("[project]\n")
            (candidate / "skills/yue2-music/scripts/abc_tools.py").write_text("# test\n")
        installer.execute = fake_clone
        # The test does not install packages or download models.
        def choose(source, target, size, action):
            return "git clone" in action
        installer.confirm = choose
        with patch.object(setup.shutil, "which", return_value="/usr/bin/git"):
            self.assertIsNone(installer.yue_stage())
        command, _ = installer.commands[0]
        self.assertEqual(command[:3], ["git", "clone", "--depth"])
        self.assertEqual(command[-2], setup.YUE_URL)
        self.assertTrue((external / "YuE" / "skills/yue2-music/scripts/abc_tools.py").exists())

    def test_existing_sheet_model_and_separate_venv_are_reused(self):
        external = self.root / "external"
        model = external / "SheetSage2-standalone"
        self.model(model, merged=True)
        source = external / "SheetSage2"
        source.mkdir()
        (source / "__init__.py").write_text("")
        (source / "modeling_sheetsage2.py").write_text("# test\n")
        python = external / "sheet-venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text("test")
        yue_python = external / "YuE/venv/bin/python"
        config = self.app / "config.local.json"
        config.write_text(json.dumps({"python": str(yue_python), "sheetsage_python": str(python),
                                      "sheetsage_model": str(model)}))
        installer = RecordingInstaller(self.app, config, external)
        installer.confirm = lambda *args: (_ for _ in ()).throw(AssertionError("unexpected installation"))
        with patch.object(setup, "python_probe", return_value={"python": [3, 10, 12], "packages": {}}), \
             patch.object(setup, "sheet_import_probe", return_value=(True, "OK")):
            self.assertEqual(installer.sheet_stage(), python)
        self.assertEqual(installer.commands, [])
        self.assertEqual(installer.proposals["sheetsage_model"], str(model))

    def test_interrupted_download_resumes_without_removing_partial_files(self):
        installer = RecordingInstaller(self.app, external=self.root / "external")
        target = installer.external / "SheetSage2"
        target.mkdir(parents=True)
        (target / "config.json").write_text("{}")
        hf = installer.external / "venv/bin/hf"
        installer.fail_once = True
        with self.assertRaises(RuntimeError):
            installer.download(hf, setup.SHEET_REPO, setup.SHEET_REV, target, "0.25 GiB")
        self.assertTrue((target / "config.json").exists())
        def finish_download(command, *, cwd=None):
            installer.commands.append((command, cwd))
            (target / "model.safetensors").write_bytes(b"test only")
        installer.execute = finish_download
        self.assertTrue(installer.download(hf, setup.SHEET_REPO, setup.SHEET_REV, target, "0.25 GiB"))
        self.assertEqual(len(installer.commands), 2)
        self.assertTrue((target / "config.json").exists())

    def test_incomplete_venv_can_resume_after_confirmation(self):
        installer = RecordingInstaller(self.app, external=self.root / "external")
        venv = installer.external / "yue-venv"
        venv.mkdir(parents=True)
        (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
        def complete_venv(command, *, cwd=None):
            installer.commands.append((command, cwd))
            (venv / "bin").mkdir()
            (venv / "bin/python").write_text("test")
        installer.execute = complete_venv
        with patch.object(setup.shutil, "which", return_value="/usr/bin/python3"):
            self.assertEqual(installer.venv(venv, "python3", "test"), venv / "bin/python")
            self.assertEqual(installer.venv(venv, "python3", "test"), venv / "bin/python")
        self.assertEqual(len(installer.commands), 1)

    def test_existing_config_is_preserved(self):
        config = self.app / "config.local.json"
        original = '{"python":"/my/existing/python","port":7860}\n'
        config.write_text(original)
        installer = RecordingInstaller(self.app, config, self.root / "external")
        installer.proposals["python"] = "/suggested/python"
        with contextlib.redirect_stdout(io.StringIO()):
            installer.config_stage()
        self.assertEqual(config.read_text(), original)

    def test_exact_revision_in_existing_hf_cache_is_reused(self):
        cache = self.root / "hf-cache"
        model = cache / "models--m-a-p--YuE2-3B" / "snapshots" / setup.YUE_MODEL[1]
        self.model(model)
        with patch.dict(os.environ, {"HUGGINGFACE_HUB_CACHE": str(cache)}):
            self.assertTrue(setup.yue_model_ready(setup.YUE_MODEL[0], *setup.YUE_MODEL))
            self.assertFalse(setup.yue_model_ready(setup.YUE_MODEL[0], setup.YUE_MODEL[0], "wrong-revision"))

    def test_out_of_range_anyio_is_not_reused(self):
        self.assertTrue(setup.version_below("4.9.0", (4, 10)))
        self.assertFalse(setup.version_below("4.10.0", (4, 10)))
        self.assertFalse(setup.version_below("unreadable", (4, 10)))

    def test_cuda_local_versions_match_official_package_pins(self):
        self.assertTrue(setup.matches_pin("2.8.0+cu126", "2.8.0"))
        self.assertTrue(setup.matches_pin("2.10.0+cu128", "2.10.0"))
        self.assertFalse(setup.matches_pin("2.7.0+cu126", "2.8.0"))

    def test_system_destinations_are_refused(self):
        with self.assertRaises(RuntimeError):
            setup.Installer(self.app, external=Path("/usr/local/yue-test"))
        with self.assertRaises(RuntimeError):
            setup.protect_write_target(Path("/etc/yue-test.json"))
        self.assertEqual(setup.protect_write_target(self.root / "external"), self.root / "external")


if __name__ == "__main__":
    unittest.main()
