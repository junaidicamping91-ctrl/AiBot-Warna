"""Unit test pipeline AimBot Warna.

    python -m unittest discover -s tests -v
Tes deteksi memakai frame sintetis (tidak butuh kamera / Arduino).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "python")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from audio.tone_factory import concat_wav_bytes, generate_all  # noqa: E402
from hardware.serial_link import SerialLink  # noqa: E402
from utils.paths import COLORS_FILE, SETTINGS_FILE, load_json  # noqa: E402
from vision.color_detector import ColorDetector, ColorVoter  # noqa: E402
from vision.colors import ColorPalette, UNKNOWN  # noqa: E402
from vision.pid import PID, clamp  # noqa: E402
from vision.tracker import TargetCommand, Tracker  # noqa: E402

try:
    import cv2  # noqa: E402
    import numpy as np  # noqa: E402
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


class PaletteTests(unittest.TestCase):
    def setUp(self):
        self.palette = ColorPalette.from_json(COLORS_FILE)

    def test_full_palette_and_ids(self):
        """Mode FULL WARNA: 12 warna, ID 1-6 tetap kompatibel Arduino lama."""
        self.assertEqual(len(self.palette), 12)
        self.assertEqual([s.id for s in self.palette], list(range(1, 13)))
        self.assertEqual(self.palette.get(2).name, "HIJAU")
        self.assertEqual(self.palette.get(7).name, "CYAN")
        self.assertEqual(self.palette.get(12).name, "ABU")
        self.assertEqual(self.palette.get(99), UNKNOWN)
        self.assertEqual(self.palette.by_key("ungu").tone_hz, 784)

    def test_chromatic_neutral_groups(self):
        self.assertEqual(len(self.palette.chromatic), 9)
        self.assertEqual(len(self.palette.neutral), 3)
        self.assertEqual({s.group for s in self.palette.neutral}, {"netral"})
        self.assertEqual([s.id for s in self.palette.for_detection(False)],
                         list(range(1, 10)))
        self.assertEqual([s.id for s in self.palette.for_detection(True)],
                         list(range(1, 13)))

    def test_web_config_matches_palette(self):
        cfg = self.palette.as_web_config()
        self.assertEqual(len(cfg), 12)
        self.assertEqual(cfg[0]["name"], "MERAH")
        self.assertEqual(len(cfg[0]["hsv"]), 2, "merah wrap-around tetap 2 rentang")
        self.assertEqual(cfg[6]["tone_hz"], 880)

    def test_red_has_two_hsv_ranges(self):
        self.assertEqual(len(self.palette.get(1).hsv_ranges), 2,
                         "MERAH harus punya 2 rentang karena hue wrap-around")

    def test_unique_frequencies(self):
        freqs = [s.tone_hz for s in self.palette]
        self.assertEqual(len(freqs), len(set(freqs)), "tiap warna harus nada berbeda")
        self.assertEqual([s.beeps for s in self.palette][:6], [1, 2, 3, 4, 5, 6])


class PIDTests(unittest.TestCase):
    def test_proportional_and_clamp(self):
        pid = PID(kp=1.0, ki=0.0, kd=0.0, output_limit=100)
        self.assertAlmostEqual(pid.compute(0, -50, dt=0.1), 50.0, places=4)
        self.assertEqual(pid.compute(0, -999, dt=0.1), 100.0)

    def test_integral_anti_windup(self):
        pid = PID(kp=0.0, ki=2.0, kd=0.0, output_limit=100)
        for _ in range(500):
            out = pid.compute(0, -100, dt=0.1)
        self.assertLessEqual(out, 100.0)
        self.assertGreaterEqual(out, -100.0)

    def test_reset(self):
        pid = PID(kp=1, ki=1, kd=0)
        pid.compute(0, -50, dt=0.1)
        pid.reset()
        self.assertEqual(pid._integral, 0.0)

    def test_clamp(self):
        self.assertEqual(clamp(12, -5, 5), 5)
        self.assertEqual(clamp(-12, -5, 5), -5)


class VoterTests(unittest.TestCase):
    def test_majority_removes_flicker(self):
        v = ColorVoter(window=5, min_votes=3)
        for cid in (0, 1, 1, 0, 1, 1):
            v.vote(cid)
        self.assertEqual(v.stable, 1)

    def test_loss_of_color(self):
        v = ColorVoter(window=5, min_votes=3)
        for _ in range(5):
            v.vote(3)
        self.assertEqual(v.stable, 3)
        for _ in range(5):
            v.vote(0)
        self.assertEqual(v.stable, 0)

    def test_hysteresis_without_majority(self):
        v = ColorVoter(window=5, min_votes=5)
        for _ in range(5):
            v.vote(2)
        for cid in (1, 3, 4, 5, 6):  # tidak ada mayoritas
            v.vote(cid)
        self.assertEqual(v.stable, 2)


class SerialTests(unittest.TestCase):
    def test_protocol_format(self):
        cmd = TargetCommand(err_x=12.5, err_y=-3.0, color_id=1, confidence=97.2)
        self.assertEqual(cmd.to_serial(), "T,12.5,-3.0,1,97\n")

    def test_mock_link_emits_event_and_telemetry(self):
        palette = ColorPalette.from_json(COLORS_FILE)
        link = SerialLink({"serial": {"mock": True, "send_every_ms": 0}}, palette)
        self.assertTrue(link.connect())
        self.assertEqual(link.status, "MOCK")
        link.send_target(TargetCommand(color_id=3, confidence=88), force=True)
        link._last_telemetry = 0.0
        lines = link.read_lines()
        self.assertTrue(any(l.startswith("EVT,COLOR,3,BIRU") for l in lines))
        self.assertTrue(any(l.startswith("POS,") for l in lines))


@unittest.skipUnless(HAS_CV2, "opencv-python belum terpasang")
class DetectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.palette = ColorPalette.from_json(COLORS_FILE)
        cls.detector = ColorDetector(cls.palette, load_json(SETTINGS_FILE, {}))

    # (52,58,68) BGR -> S~60: bukan netral (S<=45) dan bukan kromatik (S>=80).
    BG = (52, 58, 68)

    def _frame_with(self, bgr, radius=48, pos=(160, 120)):
        frame = np.full((240, 320, 3), self.BG, dtype=np.uint8)
        cv2.circle(frame, pos, radius, tuple(int(v) for v in bgr), -1)
        return frame

    def test_all_chromatic_colors(self):
        """detect() tetap mengembalikan SATU warna dominan (kompatibel main.py)."""
        for spec in self.palette.chromatic:
            with self.subTest(warna=spec.name):
                det = self.detector.detect(self._frame_with(spec.bgr))
                self.assertEqual(det.color_id, spec.id)
                self.assertTrue(det.found)
                self.assertGreaterEqual(det.confidence, 45)
                self.assertAlmostEqual(det.centroid[0], 160, delta=3)
                self.assertAlmostEqual(det.centroid[1], 120, delta=3)

    def test_full_palette_detect_all(self):
        """Mode FULL WARNA mengenali 12 warna termasuk putih/hitam/abu."""
        detector = ColorDetector(self.palette, load_json(SETTINGS_FILE, {}),
                                 include_neutral=True)
        for spec in self.palette:
            with self.subTest(warna=spec.name):
                found = detector.detect_all(self._frame_with(spec.bgr))
                self.assertIn(spec.id, [d.color_id for d in found])

    def test_multi_color_simultaneous(self):
        """Beberapa warna berbeda dalam SATU frame harus semuanya muncul."""
        detector = ColorDetector(self.palette, load_json(SETTINGS_FILE, {}),
                                 include_neutral=True)
        frame = np.full((240, 320, 3), self.BG, dtype=np.uint8)
        wanted = [1, 2, 3, 4, 7, 8, 10, 11]
        positions = [(60, 60), (160, 60), (260, 60), (60, 180),
                     (160, 180), (260, 180), (110, 120), (220, 120)]
        for cid, pos in zip(wanted, positions):
            cv2.circle(frame, pos, 30,
                       tuple(int(v) for v in self.palette.get(cid).bgr), -1)
        found = detector.detect_all(frame)
        ids = [d.color_id for d in found]
        for cid in wanted:
            self.assertIn(cid, ids, f"warna id {cid} hilang dari multi-deteksi")
        self.assertEqual(len(ids), len(set(ids)), "piksel tidak boleh dihitung 2x")

    def test_neutral_excluded_by_default(self):
        """Bidikan Arduino tidak boleh 'mengunci' dinding abu-abu."""
        frame = self._frame_with(self.palette.get(12).bgr)
        self.assertEqual(self.detector.detect(frame).color_id, 0)
        found = self.detector.detect_all(frame, include_neutral=True)
        self.assertIn(12, [d.color_id for d in found])

    def test_blank_frame_no_color(self):
        frame = np.full((240, 320, 3), (128, 128, 128), dtype=np.uint8)
        det = self.detector.detect(frame)
        self.assertFalse(det.found)
        self.assertEqual(det.color_id, 0)

    def test_red_hue_wraparound(self):
        for hue in (3, 176):
            with self.subTest(hue=hue):
                hsv = np.zeros((240, 320, 3), dtype=np.uint8)
                hsv[:] = (hue, 220, 230)
                frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
                det = self.detector.detect(frame)
                self.assertEqual(det.color_id, 1)

    def test_error_from_center(self):
        frame = np.full((240, 320, 3), (40, 40, 40), dtype=np.uint8)
        cv2.circle(frame, (280, 60), 40, (234, 107, 47), -1)  # kanan-atas
        det = self.detector.detect(frame)
        ex, ey = det.error_from_center()
        self.assertGreater(ex, 40)
        self.assertLess(ey, -20)

    def test_yolo_fallback(self):
        from vision.yolo_detector import YoloColorDetector
        yolo = YoloColorDetector(self.detector, self.palette, model_name="__tidak_ada__.pt")
        if not yolo.available:
            det = yolo.detect(self._frame_with(self.palette.get(2).bgr))
            self.assertEqual(det.color_id, 2)


@unittest.skipUnless(HAS_CV2, "opencv-python belum terpasang")
class TrackerTests(unittest.TestCase):
    def test_tracker_centers_and_serializes(self):
        palette = ColorPalette.from_json(COLORS_FILE)
        detector = ColorDetector(palette, load_json(SETTINGS_FILE, {}))
        frame = np.full((240, 320, 3), (40, 40, 40), dtype=np.uint8)
        cv2.circle(frame, (240, 120), 48, (45, 60, 230), -1)
        det = detector.detect(frame)
        tracker = Tracker((320, 240), {})
        cmd = tracker.update(det, 1, dt=1 / 30)
        self.assertGreater(cmd.err_x, 0)
        self.assertEqual(cmd.color_id, 1)
        self.assertTrue(20 <= cmd.pan <= 160)
        self.assertTrue(cmd.to_serial().startswith("T,"))

    def test_lost_target_recenters(self):
        from vision.color_detector import Detection
        tracker = Tracker((320, 240), {})
        tracker.pan = 140
        for _ in range(50):
            cmd = tracker.update(Detection(frame_size=(320, 240)), 0)
        self.assertAlmostEqual(cmd.pan, 90, delta=2)


class AudioAssetTests(unittest.TestCase):
    def test_generate_wav_files(self):
        palette = ColorPalette.from_json(COLORS_FILE)
        with tempfile.TemporaryDirectory() as tmp:
            made = generate_all(Path(tmp), palette, overwrite=True)
            names = {p.name for p in made}
            self.assertIn("merah.wav", names)
            self.assertIn("ungu.wav", names)
            self.assertIn("startup.wav", names)
            with wave.open(str(Path(tmp) / "merah.wav"), "rb") as w:
                self.assertEqual(w.getnchannels(), 1)
                self.assertEqual(w.getframerate(), 22050)
                self.assertGreater(w.getnframes(), 1000)
            with wave.open(str(Path(tmp) / "ungu.wav"), "rb") as w:
                self.assertGreater(w.getnframes(),
                                   wave.open(str(Path(tmp) / "merah.wav"), "rb").getnframes())
            self.assertTrue((Path(tmp) / "cyan.wav").is_file())
            self.assertTrue((Path(tmp) / "abu.wav").is_file())

    def test_concat_wav_bytes_for_multi_color_audio(self):
        """Beberapa nada warna disatukan jadi satu WAV untuk st.audio."""
        import io
        palette = ColorPalette.from_json(COLORS_FILE)
        with tempfile.TemporaryDirectory() as tmp:
            generate_all(Path(tmp), palette, overwrite=True)
            paths = [Path(tmp) / f"{palette.get(cid).key}.wav" for cid in (1, 2, 3)]
            data = concat_wav_bytes(paths)
            self.assertTrue(data.startswith(b"RIFF"))
            with wave.open(io.BytesIO(data), "rb") as w:
                self.assertEqual(w.getnchannels(), 1)
                self.assertEqual(w.getframerate(), 22050)
                total = 0
                for p in paths:
                    with wave.open(str(p), "rb") as src:
                        total += src.getnframes()
                self.assertGreater(w.getnframes(), total)
        self.assertEqual(concat_wav_bytes([]), b"")


if __name__ == "__main__":
    unittest.main(verbosity=2)
