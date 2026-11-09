"""Regression test: paket Streamlit / HP / deploy GitHub tetap lengkap & jalan.

Mencegah kasus yang sering terjadi saat pindah ke Streamlit Community Cloud:
file requirements tertukar (OpenCV butuh libGL), config.toml menimpa port cloud,
atau aplikasi error saat dibuka tanpa kamera (mode Simulasi).
"""
from __future__ import annotations

import py_compile
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Layout asli punya python/main.py; layout rata (C:\Robot tebak warna) tidak.
PKG = ROOT / "python" if (ROOT / "python" / "main.py").is_file() else ROOT

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    tomllib = None  # type: ignore[assignment]


def _requirements(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


class DeployFileTests(unittest.TestCase):
    def test_entry_points_compile(self):
        """Semua entry point harus bebas syntax error."""
        with tempfile.TemporaryDirectory() as tmp:
            targets = [ROOT / "streamlit_app.py", ROOT / "run_streamlit.py",
                       ROOT / "run.py", PKG / "main.py"]
            for path in targets:
                self.assertTrue(path.is_file(), f"{path} hilang")
                py_compile.compile(str(path),
                                   cfile=str(Path(tmp) / (path.name + "c")),
                                   doraise=True)

    def test_local_requirements_include_streamlit(self):
        text = _requirements("requirements.txt")
        self.assertRegex(text, r"(?m)^streamlit>=1\.33")
        self.assertRegex(text, r"(?m)^pillow>=")
        self.assertRegex(text, r"(?m)^opencv-python>=4\.8")
        self.assertRegex(text, r"(?m)^numpy>=")

    def test_cloud_requirements_use_headless_opencv(self):
        """Cloud TIDAK boleh memakai opencv-python (butuh libGL/Qt)."""
        text = _requirements("requirements-streamlit.txt")
        self.assertRegex(text, r"(?m)^opencv-python-headless>=4\.8")
        self.assertNotRegex(text, r"(?m)^opencv-python>=")
        self.assertRegex(text, r"(?m)^streamlit>=")
        self.assertRegex(text, r"(?m)^pillow>=")

    def test_streamlit_config_is_light_and_does_not_override_port(self):
        path = ROOT / ".streamlit" / "config.toml"
        self.assertTrue(path.is_file(), ".streamlit/config.toml hilang")
        text = path.read_text(encoding="utf-8")
        self.assertIn('base = "light"', text)
        self.assertIn("headless = true", text)
        # Cloud menentukan port sendiri; config tidak boleh menguncinya.
        self.assertIsNone(re.search(r"(?m)^\s*(address|port)\s*=", text))
        if tomllib is not None:
            with path.open("rb") as fh:
                cfg = tomllib.load(fh)
            self.assertEqual(cfg["theme"]["base"], "light")
            self.assertTrue(cfg["server"]["headless"])
            self.assertIn("maxUploadSize", cfg["server"])

    def test_github_deploy_assets_present_and_documented(self):
        demo = ROOT / "demo" / "index.html"
        if not demo.is_file():
            demo = ROOT / "index.html"          # layout rata
        for rel in ("packages.txt", ".github/workflows/ci.yml",
                    "assets/sounds/merah.wav"):
            self.assertTrue((ROOT / rel).is_file(), f"{rel} hilang")
        self.assertTrue(demo.is_file(), "demo/index.html atau index.html hilang")
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("requirements-streamlit.txt", ci)
        self.assertIn("unittest discover", ci)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("share.streamlit.io", readme)
        self.assertIn("## 13. Streamlit", readme)


class StreamlitRuntimeTests(unittest.TestCase):
    def test_app_runs_and_color_change_triggers_audio(self):
        """Tanpa kamera & tanpa Arduino: Simulasi harus langsung deteksi + audio."""
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError as exc:  # pragma: no cover - lingkungan tanpa Streamlit
            self.skipTest(f"Streamlit belum terpasang: {exc}")

        at = AppTest.from_file(str(ROOT / "streamlit_app.py"),
                               default_timeout=60).run()
        self.assertEqual(list(at.exception), [], "aplikasi Streamlit error saat run")
        self.assertEqual([t.value for t in at.title], ["AimBot Warna"])
        self.assertEqual(list(at.radio)[0].value, "Simulasi")
        self.assertEqual(list(at.metric)[0].value, "MERAH")

        hijau = next(b for b in at.button if b.label == "HIJAU")
        at2 = hijau.click().run()
        self.assertEqual(list(at2.exception), [], "klik warna menyebabkan error")
        # Satu klik = satu burst frame, jadi warna & audio langsung berubah.
        self.assertEqual(list(at2.metric)[0].value, "HIJAU")
        self.assertGreaterEqual(len(list(at2.get("audio"))), 1)


if __name__ == "__main__":
    unittest.main()
