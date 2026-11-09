#!/usr/bin/env python3
"""AimBot Warna - Robot Pembidik Sasaran + Tebak Warna + Audio.

Modifikasi dari poster workshop "Implementasi Object Detection pada Robot
Pembidik Sasaran" (Rizky Project): deteksi objek diganti deteksi WARNA, dan
setiap warna yang terdeteksi memicu suara audio yang berbeda.

Jalan cepat (cukup tekan Run, tanpa argumen apa pun):
    python python/main.py              # kamera default; tanpa kamera -> sumber sintetis
Tanpa hardware & tanpa kamera (headless):
    python python/main.py --synthetic --mock --headless --max-frames 90
Dengan webcam + Arduino:
    python python/main.py --port COM3
Lihat README.md untuk wiring, kalibrasi, dan protokol serial.
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------- bootstrap path
# PENTING: jangan mengandalkan "parents[N]" yang tetap. File ini boleh berada di
# <ROOT>/python/main.py (rilis asli) ATAU langsung di <ROOT>/main.py (folder
# rata hasil kopi), dan bisa dijalankan lewat terminal, IDLE (%Run), atau exec().
# Karena itu paket dicari lewat marker file, bukan posisi folder.
_MARKERS = ("audio/speaker.py", "vision/colors.py",
            "utils/paths.py", "hardware/serial_link.py")


def _candidate_dirs() -> list[Path]:
    sources = [globals().get("__file__"),
               sys.argv[0] if sys.argv else None,
               os.getcwd(),
               os.environ.get("AIMBOT_ROOT")]
    bases: list[Path] = []
    for item in sources:
        if not item:
            continue
        try:
            p = Path(item)
            p = p.resolve() if p.is_absolute() else (Path.cwd() / p).resolve()
            if p.is_file():
                p = p.parent
            bases.extend([p, p / "python", p.parent, p.parent / "python",
                          p.parent.parent, p.parent.parent / "python"])
        except (OSError, RuntimeError):
            continue
    return bases


def _bootstrap_paths() -> Path:
    """Temukan folder berisi paket proyek; tampilkan petunjuk jelas bila gagal."""
    checked: list[Path] = []
    for base in _candidate_dirs():
        if not base.is_dir() or base in checked:
            continue
        checked.append(base)
        if all((base / marker).is_file() for marker in _MARKERS):
            entry = str(base)
            if entry in sys.path:
                sys.path.remove(entry)
            sys.path.insert(0, entry)  # prioritas tertinggi, kalahkan modul 'audio' lain
            root = base
            for cand in (base, base.parent):
                if ((cand / "config" / "colors.json").is_file()
                        or (cand / "colors.json").is_file()):
                    root = cand
                    break
            os.environ["AIMBOT_ROOT"] = str(root)
            return base

    print("\n=== AimBot Warna: paket proyek tidak ditemukan ===", file=sys.stderr)
    print("main.py butuh folder audio/, vision/, hardware/, utils/ di dekatnya.",
          file=sys.stderr)
    print(f"File dijalankan : {globals().get('__file__', '(tidak diketahui)')}", file=sys.stderr)
    print(f"Folder kerja    : {os.getcwd()}", file=sys.stderr)
    print("Diperiksa       :", file=sys.stderr)
    for c in checked[:6]:
        print(f"  - {c}", file=sys.stderr)
    print("\nPerbaikan: salin SELURUH isi folder proyek (bukan hanya main.py),", file=sys.stderr)
    print("lalu jalankan dari folder tersebut:", file=sys.stderr)
    print("  python main.py --synthetic --mock --headless", file=sys.stderr)
    print("Atau dari rilis asli: python python/main.py --synthetic --mock", file=sys.stderr)
    raise SystemExit(2)


PKG_DIR = _bootstrap_paths()

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from audio.speaker import SoundEngine  # noqa: E402
from hardware.serial_link import SerialLink  # noqa: E402
from utils.logger import setup_logger  # noqa: E402
from utils.paths import COLORS_FILE, SETTINGS_FILE, load_json  # noqa: E402
from vision.color_detector import ColorDetector, ColorVoter  # noqa: E402
from vision.colors import ColorPalette  # noqa: E402
from vision.hud import draw_hud  # noqa: E402
from vision.tracker import Tracker  # noqa: E402
from vision.yolo_detector import YoloColorDetector  # noqa: E402


# --------------------------------------------------------------------- kamera virtual
class SyntheticCamera:
    """Sumber frame buatan: bola warna bergerak, ganti warna tiap 3 detik.

    Membuat proyek bisa didemo walau tidak ada webcam / belum rakit robot.
    """

    def __init__(self, palette: ColorPalette, width: int = 640, height: int = 480):
        self.palette = palette
        self.width, self.height = width, height
        self.t0 = time.monotonic()

    def isOpened(self) -> bool:
        return True

    def read(self):
        w, h, t = self.width, self.height, time.monotonic() - self.t0
        frame = np.full((h, w, 3), (246, 247, 250), dtype=np.uint8)
        for x in range(0, w, 40):
            cv2.line(frame, (x, 0), (x, h), (232, 235, 241), 1)
        for y in range(0, h, 40):
            cv2.line(frame, (0, y), (w, y), (232, 235, 241), 1)

        specs = self.palette.specs
        spec = specs[int(t // 3.0) % len(specs)]
        cx = int(w / 2 + math.sin(t * 0.85) * w * 0.28)
        cy = int(h / 2 + math.cos(t * 0.67) * h * 0.24)
        cv2.circle(frame, (cx, cy), 58, tuple(int(v) for v in spec.bgr), -1)
        cv2.circle(frame, (cx, cy), 58, (60, 60, 60), 2)
        cv2.putText(frame, "SUMBER SINTETIS - ganti warna tiap 3 detik", (14, h - 96),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (110, 120, 140), 1, cv2.LINE_AA)
        return True, frame

    def release(self) -> None:
        pass


def gui_available() -> bool:
    """True bila build OpenCV mendukung jendela (opencv-python vs -headless)."""
    try:
        cv2.namedWindow("__aimbot_probe__", cv2.WINDOW_NORMAL)
        cv2.destroyWindow("__aimbot_probe__")
        return True
    except Exception:
        return False


def open_source(args, settings, palette):
    """Buka kamera/video. Tanpa argumen apa pun tetap jalan (fallback sintetis).

    Bug yang dicegah: menjalankan `python main.py` / tekan Run di IDLE tanpa
    flag membuat args.camera == None, sehingga `int(None)` memicu TypeError.
    Sekarang index diambil dari config/settings.json, dan bila kamera tidak ada
    program otomatis memakai bola warna sintetis (bukan crash).
    """
    cam = settings.get("camera", {}) or {}
    width = int(cam.get("width", 640))
    height = int(cam.get("height", 480))

    if getattr(args, "synthetic", False):
        return SyntheticCamera(palette, width, height)

    camera_index = getattr(args, "camera", None)
    if camera_index is None:
        camera_index = cam.get("index", 0)
    source = args.source if getattr(args, "source", None) is not None else camera_index
    if isinstance(source, str) and source.lstrip("-").isdigit():
        source = int(source)
    if not isinstance(source, (int, str)):
        source = 0

    cap = None
    try:
        cap = cv2.VideoCapture(source)
    except Exception as exc:  # pragma: no cover - jarang, tergantung backend OpenCV
        logging.getLogger("aimbot").warning("cv2.VideoCapture gagal: %s", exc)
    if cap is not None and cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        return cap
    if cap is not None:
        try:
            cap.release()
        except Exception:
            pass

    logging.getLogger("aimbot").warning(
        "Kamera/sumber '%s' tidak tersedia -> otomatis pakai SUMBER SINTETIS. "
        "Gunakan --camera N untuk kamera lain, atau --synthetic untuk menegaskan.",
        source,
    )
    return SyntheticCamera(palette, width, height)


# --------------------------------------------------------------------- CLI
def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="AimBot Warna - deteksi warna + audio + bidikan servo (Python/OpenCV + Arduino)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Contoh:\n"
            "  python python/main.py                 # tanpa argumen: kamera, fallback sintetis\n"
            "  python python/main.py --synthetic --mock --headless --max-frames 90\n"
            "  python python/main.py --camera 0 --mock\n"
            "  python python/main.py --port COM3 --audio-mode both\n"
            "  python python/main.py --test-audio\n"
        ),
    )
    p.add_argument("--config", help="path settings.json (default: config/settings.json)")
    p.add_argument("--colors", help="path colors.json (default: config/colors.json)")
    p.add_argument("--camera", type=int, default=None,
                   help="index kamera (default: camera.index di settings.json, biasanya 0)")
    p.add_argument("--source", help="path file video/gambar sebagai pengganti kamera")
    p.add_argument("--synthetic", action="store_true", help="pakai bola warna buatan (tanpa kamera)")
    p.add_argument("--port", help="port serial Arduino, mis. COM3 atau /dev/ttyACM0")
    p.add_argument("--baud", type=int, help="baudrate (default 115200)")
    p.add_argument("--mock", action="store_true", help="paksa mode simulasi tanpa Arduino")
    p.add_argument("--no-audio", action="store_true", help="matikan audio PC")
    p.add_argument("--audio-mode", choices=["tones", "speech", "both", "off"],
                   help="nada / ucapan / keduanya / mati")
    p.add_argument("--test-audio", action="store_true", help="mainkan ke-12 warna lalu keluar")
    p.add_argument("--headless", action="store_true", help="tanpa jendela OpenCV (server/CI)")
    p.add_argument("--detector", choices=["color", "yolo"], default="color",
                   help="color = HSV (default); yolo = YOLO + warna di dalam box (opsional)")
    p.add_argument("--max-frames", type=int, default=0, help="hentikan setelah N frame (0 = tanpa batas)")
    p.add_argument("--log-level", default=None, help="DEBUG/INFO/WARNING")
    p.add_argument("--list-ports", action="store_true", help="tampilkan port serial lalu keluar")
    p.add_argument("--calibrate", metavar="KEY",
                   help="buka kalibrator HSV untuk warna tertentu lalu keluar (mis. merah)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    settings = load_json(args.config or SETTINGS_FILE, default={})
    settings.setdefault("camera", {})
    settings.setdefault("serial", {})
    settings.setdefault("audio", {})
    settings.setdefault("display", {})
    settings.setdefault("logging", {})

    if args.camera is not None:
        settings["camera"]["index"] = args.camera
    if args.port:
        settings["serial"]["port"] = args.port
    if args.baud:
        settings["serial"]["baud"] = args.baud
    if args.mock:
        settings["serial"]["mock"] = True
    if args.no_audio or args.audio_mode == "off":
        settings["audio"]["enabled"] = False
    if args.audio_mode and args.audio_mode != "off":
        settings["audio"]["mode"] = args.audio_mode
    if args.headless:
        settings["display"]["show"] = False

    log = setup_logger(args.log_level or settings["logging"].get("level", "INFO"),
                       settings["logging"].get("log_file"))

    if args.list_ports:
        ports = SerialLink.list_ports()
        print("Port serial terdeteksi:", ", ".join(ports) if ports else "(tidak ada)")
        return 0

    palette = ColorPalette.from_json(args.colors or COLORS_FILE)
    log.info("AimBot Warna siap | %d warna | %s", len(palette), palette.summary())

    if args.calibrate:
        from tools.calibrate_color import run as calibrate_run
        return calibrate_run(args.calibrate, settings["camera"].get("index", 0),
                             args.colors or COLORS_FILE)

    speaker = SoundEngine(settings, palette)
    if args.test_audio:
        if not speaker.enabled:
            log.warning("Audio dimatikan; lepas --no-audio untuk menguji")
            return 1
        speaker.test_all()
        return 0

    base_detector = ColorDetector(palette, settings)
    yolo = None
    if args.detector == "yolo":
        yolo = YoloColorDetector(base_detector, palette)
        log.info("Detector: YOLO (%s)", "aktif" if yolo.available else "fallback HSV")

    detection_cfg = settings.get("detection", {})
    voter = ColorVoter(int(detection_cfg.get("vote_window", 7)),
                       int(detection_cfg.get("min_votes", 4)))
    link = SerialLink(settings, palette)
    link.connect()
    cap = open_source(args, settings, palette)

    tracker: Tracker | None = None
    fps, last_t, frame_no = 0.0, time.perf_counter(), 0
    last_stable = 0
    show = bool(settings["display"].get("show", True)) and not args.headless
    if show and not gui_available():
        show = False
        log.warning(
            "Build OpenCV ini tidak mendukung jendela (opencv-python-headless) -> "
            "HUD otomatis dimatikan, program jalan headless. "
            "Gunakan demo/index.html untuk tampilan, atau pip install opencv-python."
        )

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                log.info("Sumber frame berakhir")
                break
            frame_no += 1
            if settings["camera"].get("flip_horizontal"):
                frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            if tracker is None:
                tracker = Tracker((w, h), settings)

            raw = yolo.detect(frame) if yolo else base_detector.detect(frame)
            gate = float(detection_cfg.get("confidence_threshold", 45.0))
            candidate = raw.color_id if raw.found and raw.confidence >= gate else 0
            stable = voter.vote(candidate)

            # --- FITUR UTAMA: audio sesuai warna (hanya saat warna berubah) ---
            if stable != last_stable:
                speaker.on_color(stable)
                if stable:
                    log.info("LOCK warna #%d -> %s", stable, palette.get(stable).name)
                else:
                    log.info("Warna hilang / mencari sasaran")
                last_stable = stable
            speaker.tick()

            cmd = tracker.update(raw, stable)
            link.send_target(cmd, force=(frame_no == 1))
            for line in link.read_lines():
                if line.startswith(("EVT", "LOG", "PONG")):
                    log.info("RX %s", line)

            now = time.perf_counter()
            dt = now - last_t
            last_t = now
            instant = 1.0 / dt if dt > 0 else 0.0
            fps = instant if frame_no == 1 else fps * 0.9 + instant * 0.1

            if show:
                try:
                    view = draw_hud(frame, raw, fps, cmd, palette,
                                    status=link.status, last_audio=speaker.last_audio) \
                        if settings["display"].get("hud", True) else frame
                    cv2.imshow(settings["display"].get("window_name", "AimBot Warna"), view)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), ord("Q"), 27):
                        break
                except cv2.error as exc:  # build headless / tidak ada display
                    show = False
                    log.warning("Jendela OpenCV gagal (%s) -> lanjut headless", exc)
            elif frame_no % 30 == 0:
                log.info("frame %4d | %-8s conf=%5.1f | err=(%+6.1f,%+6.1f) | %s",
                         frame_no, palette.get(stable).name, raw.confidence,
                         cmd.err_x, cmd.err_y, speaker.last_audio)

            if args.max_frames and frame_no >= args.max_frames:
                break
    except KeyboardInterrupt:
        log.info("Dihentikan pengguna")
    finally:
        link.close()
        cap.release()
        if show:
            try:
                cv2.destroyAllWindows()
            except cv2.error:
                pass
        log.info("Selesai | %d frame | rata-rata %.1f FPS", frame_no, fps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
