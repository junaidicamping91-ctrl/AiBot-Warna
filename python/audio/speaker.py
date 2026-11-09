"""FITUR MODIFIKASI: robot memberi SUARA AUDIO sesuai warna yang terdeteksi.

Tiga lapisan umpan balik:
  1. Nada  -> file WAV unik per warna (frekuensi + jumlah beep berbeda)
  2. Ucapan -> TTS Bahasa Indonesia "Warna terdeteksi, merah"
  3. Buzzer & RGB LED -> dijalankan board Arduino (lihat file .ino)

Pemicuan HANYA saat warna stabil BERUBAH, dengan cooldown, supaya suara tidak
berulang setiap frame (30x/detik).
"""
from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path

from utils.paths import ROOT, ensure_sound_dir
from vision.colors import ColorPalette

from .tone_factory import generate_all

log = logging.getLogger("aimbot")
IS_WINDOWS = platform.system() == "Windows"


class SoundEngine:
    def __init__(self, settings: dict | None = None, palette: ColorPalette | None = None):
        cfg = (settings or {}).get("audio", settings or {})
        self.enabled = bool(cfg.get("enabled", True))
        self.mode = (cfg.get("mode") or "both").lower() if self.enabled else "off"
        self.cooldown = float(cfg.get("cooldown_s", 1.2))
        self.template = cfg.get("speak_template", "Warna terdeteksi, {warna}")
        self.lang = cfg.get("speak_lang", "id-ID")
        self.palette = palette or ColorPalette.from_json()
        configured = Path(cfg.get("sounds_dir", "assets/sounds"))
        self.sound_dir = configured if configured.is_absolute() else ROOT / configured

        self._last_id = 0
        self._last_play = 0.0
        self._pending: int | None = None
        self._warned = False
        self.last_audio = "-"

        if self.enabled:
            ensure_sound_dir()
            created = generate_all(self.sound_dir, self.palette,
                                   volume=float(cfg.get("volume", 0.6)))
            if created:
                log.info("Audio: %d file WAV dibuat di %s", len(created), self.sound_dir)
            log.info("Audio aktif | mode=%s | cooldown=%.1fs | %s",
                     self.mode, self.cooldown, self.palette.summary())

    # ------------------------------------------------------------------ public
    def on_color(self, color_id: int) -> bool:
        """Dipanggil tiap frame; hanya bereaksi saat warna berubah."""
        color_id = int(color_id)
        if self.mode == "off" or color_id == self._last_id:
            return False
        self._last_id = color_id
        self._pending = color_id
        return self.tick()

    def tick(self) -> bool:
        """Mainkan suara yang tertunda bila cooldown sudah lewat."""
        if self._pending is None or self.mode == "off":
            return False
        now = time.monotonic()
        if now - self._last_play < self.cooldown:
            return False
        color_id, self._pending = self._pending, None
        self._last_play = now

        if color_id == 0:
            self.last_audio = "warna hilang"
            self._play_wav("lost.wav")
            return True

        spec = self.palette.get(color_id)
        self.last_audio = f"{spec.name} / {spec.tone_hz} Hz / {spec.beeps} beep"
        log.info("WARNA TERDETEKSI -> %s | %s", spec.name, self.last_audio)

        if self.mode in ("tones", "both"):
            self._play_wav(f"{spec.key}.wav")
        if self.mode in ("speech", "both"):
            speech_file = self.sound_dir / f"{spec.key}_ucapan.wav"
            if speech_file.exists():
                self._play_wav(speech_file.name)
            else:
                self._speak(self.template.format(warna=spec.speech))
        return True

    def test_all(self, delay: float = 0.6) -> None:
        """Uji semua warna secara berurutan (tidak butuh kamera)."""
        for spec in self.palette:
            self._last_id = -1
            self.on_color(spec.id)
            time.sleep(delay)

    # ------------------------------------------------------------------ nada
    def _play_wav(self, filename: str) -> None:
        path = self.sound_dir / filename
        if not path.exists():
            self._warn_once(f"file suara tidak ada: {path}")
            return
        try:
            if IS_WINDOWS:
                import winsound  # type: ignore
                winsound.PlaySound(str(path), winsound.SND_FILENAME |
                                   winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            elif shutil.which("afplay"):
                subprocess.Popen(["afplay", str(path)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif shutil.which("aplay"):
                subprocess.Popen(["aplay", "-q", str(path)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                self._warn_once("pemutar audio sistem tidak ditemukan (afplay/aplay)")
        except Exception as exc:
            self._warn_once(f"gagal memutar {filename}: {exc}")

    # ------------------------------------------------------------------ ucapan
    def _speak(self, text: str) -> None:
        if IS_WINDOWS:
            # SAPI bawaan Windows lewat PowerShell: tanpa dependency tambahan,
            # dijalankan async supaya tidak membekukan loop kamera.
            safe = text.replace("'", "''")
            script = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$s.Speak('{safe}'); $s.Dispose()"
            )
            try:
                kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
                if hasattr(subprocess, "CREATE_NO_WINDOW"):
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                    **kwargs,
                )
                return
            except Exception as exc:
                log.debug("SAPI gagal (%s), coba pyttsx3", exc)

        def _tts():
            try:
                import pyttsx3  # type: ignore
                engine = pyttsx3.init()
                engine.say(text)
                engine.runAndWait()
            except Exception as exc:
                self._warn_once(f"TTS tidak tersedia ({exc}); memakai nada saja")

        threading.Thread(target=_tts, daemon=True).start()

    def _warn_once(self, message: str) -> None:
        if not self._warned:
            log.warning("Audio: %s", message)
            self._warned = True
