"""Regression test: proyek tetap jalan walau dipindah / foldernya diratakan.

Kasus nyata yang dicegah: main.py dikopi sendirian ke C:\\Robot tebak warna\\
lalu dijalankan dari IDLE -> ModuleNotFoundError: No module named 'audio.speaker'.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "python" if (ROOT / "python" / "main.py").is_file() else ROOT
for _p in (str(ROOT), str(PKG)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def source_file(name: str) -> Path:
    """Cari config/<name> (layout asli) atau <name> di root (layout rata)."""
    nested = ROOT / "config" / name
    return nested if nested.is_file() else ROOT / name


class PathLayoutTests(unittest.TestCase):
    def test_nested_layout(self):
        import utils.paths as paths
        self.assertEqual(paths.ROOT.resolve(), ROOT.resolve())
        self.assertTrue(paths.COLORS_FILE.is_file())
        self.assertTrue(paths.SETTINGS_FILE.is_file())
        self.assertTrue(paths.SOUND_DIR.is_dir())

    def test_flat_layout_root_detection(self):
        """paths.py yang ditaruh di ROOT/utils/ harus menemukan ROOT, bukan parent ROOT."""
        with tempfile.TemporaryDirectory() as tmp:
            flat = Path(tmp) / "Robot tebak warna"
            (flat / "utils").mkdir(parents=True)
            shutil.copy2(PKG / "utils" / "paths.py", flat / "utils" / "paths.py")
            shutil.copy2(source_file("colors.json"), flat / "colors.json")
            shutil.copy2(source_file("settings.json"), flat / "settings.json")

            env_backup = os.environ.pop("AIMBOT_ROOT", None)
            try:
                spec = importlib.util.spec_from_file_location(
                    "flat_paths_under_test", flat / "utils" / "paths.py")
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                self.assertEqual(mod.ROOT.resolve(), flat.resolve())
                self.assertEqual(mod.CONFIG_DIR.resolve(), flat.resolve())
                self.assertEqual(mod.COLORS_FILE.name, "colors.json")
                self.assertTrue(mod.COLORS_FILE.is_file())
            finally:
                if env_backup is not None:
                    os.environ["AIMBOT_ROOT"] = env_backup


class RunFromAnywhereTests(unittest.TestCase):
    """Salin seluruh isi ke folder rata, lalu jalankan dari folder LAIN."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.flat = Path(cls.tmp.name) / "Robot tebak warna"
        cls.flat.mkdir()
        for name in ("audio", "vision", "hardware", "utils", "tools"):
            shutil.copytree(PKG / name, cls.flat / name,
                            ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(PKG / "main.py", cls.flat / "main.py")
        shutil.copy2(source_file("colors.json"), cls.flat / "colors.json")
        shutil.copy2(source_file("settings.json"), cls.flat / "settings.json")
        (cls.flat / "assets" / "sounds").mkdir(parents=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _run(self, cwd: Path, *extra: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.pop("AIMBOT_ROOT", None)
        return subprocess.run(
            [sys.executable, str(self.flat / "main.py"),
             "--synthetic", "--mock", "--headless", "--no-audio",
             "--max-frames", "8", *extra],
            cwd=str(cwd), env=env, capture_output=True, text=True, timeout=90,
        )

    def test_flat_folder_from_itself(self):
        r = self._run(self.flat)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Selesai", r.stdout)

    def test_flat_folder_from_other_cwd(self):
        r = self._run(Path(tempfile.gettempdir()))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("AimBot Warna siap", r.stdout)

    def test_idle_style_relative_file(self):
        """IDLE %Run memakai __file__ relatif; bootstrap harus tetap menemukan paket."""
        script = (
            "import runpy, sys; "
            f"sys.argv=[{str(self.flat / 'main.py')!r}, '--synthetic', '--mock', "
            "'--headless', '--no-audio', '--max-frames', '5']; "
            f"runpy.run_path({str(self.flat / 'main.py')!r}, run_name='__main__')"
        )
        env = dict(os.environ)
        env.pop("AIMBOT_ROOT", None)
        r = subprocess.run([sys.executable, "-c", script],
                           cwd=str(self.flat), env=env,
                           capture_output=True, text=True, timeout=90)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Selesai", r.stdout)

    def test_missing_packages_gives_clear_message(self):
        """main.py kopi sendirian harus memberi petunjuk, bukan traceback mentah."""
        with tempfile.TemporaryDirectory() as tmp:
            lonely = Path(tmp)
            shutil.copy2(PKG / "main.py", lonely / "main.py")
            env = dict(os.environ)
            env.pop("AIMBOT_ROOT", None)
            r = subprocess.run([sys.executable, str(lonely / "main.py")],
                               cwd=str(lonely), env=env,
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 2)
            self.assertIn("paket proyek tidak ditemukan", r.stderr)
            self.assertIn("audio/", r.stderr)


class NoArgumentTests(unittest.TestCase):
    """Dijalankan tanpa flag sama sekali tidak boleh TypeError: int(None)."""

    class _StubCam:
        def __init__(self, opened):
            self._opened = opened
            self.released = False

        def isOpened(self):
            return self._opened

        def set(self, *_args):
            return True

        def release(self):
            self.released = True

    def _args(self, **kw):
        base = dict(synthetic=False, source=None, camera=None)
        base.update(kw)
        return Namespace(**base)

    def test_no_args_uses_config_index_and_falls_back(self):
        import main
        from vision.colors import ColorPalette
        settings = {"camera": {"index": 0, "width": 320, "height": 240}}
        stub = self._StubCam(False)
        with patch.object(main.cv2, "VideoCapture", return_value=stub) as vc:
            src = main.open_source(self._args(), settings, ColorPalette.from_json())
        vc.assert_called_once_with(0)
        self.assertIsInstance(src, main.SyntheticCamera)
        self.assertTrue(stub.released)
        self.assertEqual((src.width, src.height), (320, 240))

    def test_no_camera_key_in_settings(self):
        import main
        from vision.colors import ColorPalette
        stub = self._StubCam(False)
        with patch.object(main.cv2, "VideoCapture", return_value=stub) as vc:
            src = main.open_source(self._args(), {}, ColorPalette.from_json())
        vc.assert_called_once_with(0)
        self.assertIsInstance(src, main.SyntheticCamera)

    def test_gui_probe_never_raises(self):
        import main
        self.assertIsInstance(main.gui_available(), bool)

    def test_explicit_camera_wins(self):
        import main
        from vision.colors import ColorPalette
        stub = self._StubCam(True)
        with patch.object(main.cv2, "VideoCapture", return_value=stub) as vc:
            src = main.open_source(self._args(camera=2),
                                   {"camera": {"index": 0}}, ColorPalette.from_json())
        vc.assert_called_once_with(2)
        self.assertIs(src, stub)


if __name__ == "__main__":
    unittest.main(verbosity=2)
