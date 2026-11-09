"""Regression test: paket Streamlit / HP / deploy GitHub tetap lengkap & jalan.

Mencegah kasus yang sering terjadi saat pindah ke Streamlit Community Cloud:
file requirements tertukar (OpenCV butuh libGL), config.toml menimpa port cloud,
atau aplikasi error saat dibuka tanpa kamera (mode Simulasi).
"""
from __future__ import annotations

import json
import py_compile
import re
import shutil
import subprocess
import sys
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


def _asset(nested: str, flat: str) -> Path:
    """Cari aset di layout asli (web/...) maupun layout folder rata."""
    p = ROOT / nested
    return p if p.is_file() else ROOT / flat


def _realtime_html() -> Path:
    return _asset("web/realtime.html", "realtime.html")


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
                    "assets/sounds/merah.wav", "assets/sounds/cyan.wav"):
            self.assertTrue((ROOT / rel).is_file(), f"{rel} hilang")
        self.assertTrue(demo.is_file(), "demo/index.html atau index.html hilang")
        self.assertTrue(_realtime_html().is_file(), "web/realtime.html hilang")
        self.assertTrue((ROOT / "tests" / "realtime_js_harness.js").is_file())
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("requirements-streamlit.txt", ci)
        self.assertIn("unittest discover", ci)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("share.streamlit.io", readme)
        self.assertIn("## 13. Streamlit", readme)
        self.assertIn("Kamera Realtime", readme)
        self.assertIn("12 warna", readme)
        app = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("Kamera Realtime", app)
        self.assertIn("detect_all", app)
        self.assertIn("as_web_config", app)


class StreamlitRuntimeTests(unittest.TestCase):
    def _app(self, timeout=90):
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError as exc:  # pragma: no cover - lingkungan tanpa Streamlit
            self.skipTest(f"Streamlit belum terpasang: {exc}")
        return AppTest.from_file(str(ROOT / "streamlit_app.py"),
                                 default_timeout=timeout).run()

    def test_realtime_is_default_and_embeds_camera_component(self):
        """Mode bawaan HARUS kamera realtime (bukan sekadar foto)."""
        at = self._app()
        self.assertEqual(list(at.exception), [], "aplikasi Streamlit error saat run")
        self.assertEqual([t.value for t in at.title], ["AimBot Warna"])
        self.assertEqual(list(at.radio)[0].value, "Kamera Realtime")
        self.assertGreaterEqual(len(list(at.get("iframe"))), 1,
                                "komponen kamera realtime tidak tampil")

    def test_simulasi_detects_color_and_triggers_audio(self):
        """Tanpa kamera & tanpa Arduino: Simulasi tetap deteksi + audio."""
        at = self._app()
        at.radio[0].set_value("Simulasi").run()
        self.assertEqual(list(at.exception), [])
        metrics = {m.label: m.value for m in at.metric}
        self.assertEqual(metrics["Jumlah warna"], "1")
        self.assertEqual(metrics["Dominan"], "MERAH")

        hijau = next(b for b in at.button if b.label == "HIJAU")
        at2 = hijau.click().run()
        self.assertEqual(list(at2.exception), [], "klik warna menyebabkan error")
        self.assertEqual({m.label: m.value for m in at2.metric}["Dominan"], "HIJAU")
        self.assertGreaterEqual(len(list(at2.get("audio"))), 1)

    def test_all_colors_detected_simultaneously(self):
        """Tombol 'Semua warna sekaligus' harus menghasilkan 12 deteksi."""
        at = self._app()
        at.radio[0].set_value("Simulasi").run()
        btn = next(b for b in at.button if b.label == "Semua warna sekaligus")
        at2 = btn.click().run()
        self.assertEqual(list(at2.exception), [])
        metrics = {m.label: m.value for m in at2.metric}
        self.assertEqual(metrics["Jumlah warna"], "12")
        self.assertGreaterEqual(len(list(at2.get("audio"))), 1)


class RealtimeComponentTests(unittest.TestCase):
    def test_html_has_camera_and_multi_color_pipeline(self):
        html = _realtime_html().read_text(encoding="utf-8")
        for token in ("__CONFIG__", "getUserMedia", "detectFrame", "colorIndex",
                      "connected", "speechSynthesis", "AudioContext",
                      "__aimbotTest", "vote_frames"):
            self.assertIn(token, html, f"komponen realtime kehilangan {token}")

    def test_node_harness_detects_all_twelve_colors(self):
        """Jalankan algoritma JS asli pada frame berisi 12 warna sekaligus."""
        node = shutil.which("node")
        if not node:  # pragma: no cover - CI tanpa Node
            self.skipTest("Node.js tidak tersedia")
        harness = ROOT / "tests" / "realtime_js_harness.js"
        sys.path.insert(0, str(PKG))
        sys.path.insert(0, str(ROOT))
        from utils.paths import COLORS_FILE, SETTINGS_FILE, load_json
        from vision.colors import ColorPalette

        palette = ColorPalette.from_json(COLORS_FILE)
        det = load_json(SETTINGS_FILE, {}).get("detection", {})
        cfg = {
            "colors": palette.as_web_config(),
            "min_area_ratio": float(det.get("min_area_ratio", 0.005)),
            "confidence_threshold": float(det.get("confidence_threshold", 45.0)),
            "confidence_ref_ratio": float(det.get("confidence_ref_ratio", 0.15)),
            "vote_frames": 3,
            "sound_mode": "keduanya",
            "include_neutral": True,
            "facing": "environment",
            "max_fps": 20,
        }
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "rt.json"
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
            proc = subprocess.run(
                [node, str(harness), str(_realtime_html()), str(cfg_path)],
                capture_output=True, text=True, timeout=60,
            )
        self.assertEqual(proc.returncode, 0,
                         f"harness JS gagal:\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("12/12", proc.stdout)
        self.assertIn("OK", proc.stdout)


if __name__ == "__main__":
    unittest.main()
